import hashlib
import secrets
import uuid
from datetime import timedelta
from decimal import Decimal
from django.utils import timezone

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction, models
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .forms import FieldEventForm
from .calculation import calculate_event
from .communication_forms import CommunicationMessageForm, CommunicationThreadForm
from .models import AdmissionFieldDefinition, AdmissionFieldValue, AdmissionRequest, AuditLog, CalculationResult, CalculationRule, CommunicationMessage, CommunicationThread, Competency, FieldEvent, MonthlyCompensationResult, Notification, PaymentCycle, PaymentEntry, ReportEmission, Tenant
from .reporting import build_report_data, create_pdf, create_xlsx, response_file
from .quality import health_summary
from .compensation import calculate_monthly_compensation
from .payments import generate_monthly_entries
from .import_forms import ImportWorkbookForm
from .importer import inspect_payroll_pdf, inspect_workbook, sha256_file, validate_payroll_pdf, validate_workbook
from .models import ImportBatch
from .admission_forms import AdmissionAccessForm, AdmissionConversionForm, AdmissionRequestForm, AdmissionReviewForm, build_public_form
from .admissions import can_convert_admission, convert_admission
from .import_forms import RosterImportForm
from .models import RosterImportBatch
from .roster_importer import apply_roster_import, create_roster_template, prepare_roster_import
from io import BytesIO
from django.http import FileResponse, Http404
from .models import Rubric
from .rubric_forms import RubricForm
from .competency_forms import CompetencyForm
from .rubric_applications import available_applications
from .access import capability_required, navigation_access, tenant_for_user as _tenant_for_user, user_roles, user_scopes
from .navigation import AREAS, available_tools
from .event_cost_dashboard import build_event_cost_dashboard


@login_required
def workspace_area(request, area_slug):
    area = AREAS.get(area_slug)
    if area is None:
        raise Http404("Área não encontrada.")
    access = navigation_access(request)["platform_access"]
    if not access["office"] or not access[area["capability"]]:
        return render(request, "core/empty_state.html", {"title": "Seu perfil não tem acesso a esta área"}, status=403)
    return render(request, "core/workspace_area.html", {
        "area": area, "tools": available_tools(area, access),
    })


def _allowed_units_for_user(user, tenant):
    if not tenant:
        return tenant.units.none() if tenant else []
    scopes = [scope for scope in user_scopes(user) if scope.tenant_id == tenant.pk]
    if user.is_superuser or any(scope.role == "platform" and not scope.unit_id for scope in scopes):
        return tenant.units.filter(active=True)
    unit_ids = [scope.unit_id for scope in scopes if scope.unit_id]
    return tenant.units.filter(id__in=unit_ids, active=True).distinct()


def _audit(*, tenant, user, action, entity, entity_id, before=None, after=None, reason=""):
    return AuditLog.objects.create(
        tenant=tenant,
        user=user,
        action=action,
        entity=entity,
        entity_id=str(entity_id),
        before=before or {},
        after=after or {},
        reason=reason,
    )


@login_required
def dashboard(request):
    if navigation_access(request)["platform_access"]["leader_only"]:
        return redirect("field_app")
    tenant = _tenant_for_user(request.user)
    if not tenant:
        return render(request, "core/empty_state.html", {"title": "Nenhum cliente configurado"})
    competency = tenant.competencies.order_by("-year", "-month").first()
    units = list(
        _allowed_units_for_user(request.user, tenant)
        .annotate(dashboard_event_count=Count("events", filter=Q(events__tenant=tenant)))
    )
    events = tenant.events.filter(unit__in=units).select_related("unit", "collaborator", "competency").order_by("-event_date", "-created_at")[:8]
    context = {
        "tenant": tenant,
        "competency": competency,
        "units": units,
        "company_count": tenant.companies.count(),
        "unit_count": len(units),
        "events": events,
        "event_count": tenant.events.filter(unit__in=units).count(),
        "pending_count": tenant.events.filter(unit__in=units, status="pending").count(),
        "collaborator_count": tenant.collaborators.filter(active=True, links__unit__in=units).distinct().count(),
    }
    _audit(tenant=tenant, user=request.user, action="access", entity="dashboard", entity_id=tenant.id)
    return render(request, "core/dashboard.html", context)


@login_required
@capability_required("field")
def event_create(request):
    tenant = _tenant_for_user(request.user)
    if not tenant:
        messages.error(request, "Configure um cliente antes de lançar eventos.")
        return redirect("dashboard")
    if request.method == "POST":
        form = FieldEventForm(request.POST)
        allowed_units = _allowed_units_for_user(request.user, tenant)
        form.fields["application"].queryset = available_applications(tenant, allowed_units)
        form.fields["unit"].queryset = allowed_units
        selected_unit_id = request.POST.get("unit")
        collaborator_links = tenant.collaborators.filter(active=True, links__unit__in=allowed_units)
        try:
            selected_unit_id = int(selected_unit_id)
        except (TypeError, ValueError):
            selected_unit_id = None
        if selected_unit_id and allowed_units.filter(id=selected_unit_id).exists():
            collaborator_links = collaborator_links.filter(links__unit_id=selected_unit_id)
        form.fields["collaborator"].queryset = collaborator_links.distinct()
        if form.is_valid():
            event = form.save(commit=False)
            event.tenant = tenant
            event.created_by = request.user
            event.idempotency_key = uuid.uuid4()
            try:
                with transaction.atomic():
                    competency = tenant.competencies.select_for_update().filter(
                        status__in=["open", "review"]
                    ).order_by("-year", "-month").first()
                    if not competency:
                        raise ValidationError("Não existe competência aberta para receber lançamentos.")
                    if (event.event_date.year, event.event_date.month) != (competency.year, competency.month):
                        raise ValidationError("A competência mudou durante o envio. Confira a data e tente novamente.")
                    event.competency = competency
                    invalidated_cycles = _invalidate_approved_payment_cycles(
                        competency,
                        request.user,
                        "Novo lançamento incluído após aprovação do ciclo.",
                    )
                    event.save()
                    _audit(
                        tenant=tenant,
                        user=request.user,
                        action="create",
                        entity="field_event",
                        entity_id=event.id,
                        after={"event_type": event.event_type, "unit_id": event.unit_id, "status": event.status},
                    )
            except ValidationError as exc:
                form.add_error(None, exc)
            except IntegrityError:
                messages.error(request, "Já existe um evento igual para este colaborador e data.")
            else:
                message = "Lançamento registrado e enviado para conferência."
                if invalidated_cycles:
                    message += " A aprovação dos ciclos existentes foi invalidada; confira e aprove novamente."
                messages.success(request, message)
                return redirect("field_app" if navigation_access(request)["platform_access"]["leader_only"] else "dashboard")
    else:
        form = FieldEventForm()
        allowed_units = _allowed_units_for_user(request.user, tenant)
        form.fields["application"].queryset = available_applications(tenant, allowed_units)
        form.fields["unit"].queryset = allowed_units
        form.fields["collaborator"].queryset = tenant.collaborators.filter(active=True, links__unit__in=allowed_units).distinct()
    return render(request, "core/event_form.html", {"form": form, "tenant": tenant})


@login_required
@capability_required("field")
def event_list(request):
    tenant = _tenant_for_user(request.user)
    allowed_units = _allowed_units_for_user(request.user, tenant)
    events = tenant.events.filter(unit__in=allowed_units).select_related("unit", "collaborator", "created_by") if tenant else FieldEvent.objects.none()
    return render(request, "core/event_list.html", {"tenant": tenant, "events": events})


@login_required
@capability_required("field")
def field_app(request):
    tenant = _tenant_for_user(request.user)
    allowed_units = _allowed_units_for_user(request.user, tenant)
    requested_unit = request.GET.get("unit", "")
    try:
        requested_unit_id = int(requested_unit)
    except (TypeError, ValueError):
        requested_unit_id = None
    unit = allowed_units.filter(id=requested_unit_id).first() if tenant and requested_unit_id else None
    if tenant and not request.GET.get("unit") and allowed_units.count() == 1:
        unit = allowed_units.first()
    collaborators = tenant.collaborators.filter(active=True, links__unit=unit).distinct() if tenant and unit else []
    return render(
        request,
        "core/field_app.html",
        {
            "tenant": tenant,
            "units": allowed_units,
            "unit": unit,
            "collaborators": collaborators,
            "event_types": [item for item in FieldEvent.EVENT_CHOICES if item[0] != "rubric"],
            "rubric_applications": available_applications(tenant, [unit]) if tenant and unit else [],
        },
    )


@login_required
@capability_required("field")
def event_calendar(request):
    tenant = _tenant_for_user(request.user)
    competency = tenant.competencies.order_by("-year", "-month").first() if tenant else None
    allowed_units = _allowed_units_for_user(request.user, tenant)
    events = tenant.events.filter(unit__in=allowed_units).select_related("unit", "collaborator").order_by("event_date", "collaborator__name") if tenant else FieldEvent.objects.none()
    grouped = []
    current_date = None
    for event in events:
        if event.event_date != current_date:
            current_date = event.event_date
            grouped.append({"date": current_date, "events": []})
        grouped[-1]["events"].append(event)
    return render(request, "core/event_calendar.html", {"tenant": tenant, "competency": competency, "days": grouped})


def _can_manage_rules(user, tenant):
    return user.is_superuser or bool(user_roles(user, tenant).intersection(["dp", "platform"]))


@login_required
def rule_list(request):
    tenant = _tenant_for_user(request.user)
    if not tenant or not _can_manage_rules(request.user, tenant):
        return render(request, "core/empty_state.html", {"title": "Acesso restrito às regras"}, status=403)
    rules = tenant.calculation_rules.select_related("company", "unit", "created_by", "approved_by")
    rubrics = tenant.rubrics.all()
    units = _allowed_units_for_user(request.user, tenant)
    return render(request, "core/rule_list.html", {
        "tenant": tenant, "rules": rules, "rubrics": rubrics,
        "applications": tenant.rubric_applications.filter(unit__in=units).select_related("rubric", "unit"),
        "agreements": tenant.collaborator_rubrics.filter(application__unit__in=units).select_related("application__rubric", "application__unit", "collaborator"),
        "generation_competencies": tenant.competencies.filter(status__in=["open", "review"]),
    })


def _rubric_snapshot(rubric):
    return {
        "code": rubric.code,
        "name": rubric.name,
        "category": rubric.category,
        "active": rubric.active,
        "cycle_type": rubric.cycle_type,
        "effective_from": rubric.effective_from.isoformat(),
        "effective_to": rubric.effective_to.isoformat() if rubric.effective_to else None,
        "description": rubric.description,
        "version": rubric.version,
    }


@login_required
def rubric_edit(request, rubric_id=None):
    tenant = _tenant_for_user(request.user)
    if not tenant or not _can_manage_rules(request.user, tenant):
        return render(request, "core/empty_state.html", {"title": "Acesso restrito às rubricas"}, status=403)
    if request.method not in {"GET", "POST"}:
        from django.http import HttpResponseNotAllowed
        return HttpResponseNotAllowed(["GET", "POST"])
    with transaction.atomic():
        rubric = (
            get_object_or_404(Rubric.objects.select_for_update(), pk=rubric_id, tenant=tenant)
            if rubric_id else Rubric(tenant=tenant)
        )
        before = _rubric_snapshot(rubric) if rubric.pk else {}
        form = RubricForm(request.POST if request.method == "POST" else None, instance=rubric, tenant=tenant)
        if request.method == "POST" and form.is_valid():
            try:
                with transaction.atomic():
                    saved = form.save(commit=False)
                    if not saved.pk:
                        saved.created_by = request.user
                    saved.save()
                    _audit(
                        tenant=tenant, user=request.user,
                        action="update" if before else "create",
                        entity="rubric", entity_id=saved.pk,
                        before=before, after=_rubric_snapshot(saved),
                        reason=form.cleaned_data["change_reason"],
                    )
            except IntegrityError:
                if not Rubric.objects.filter(tenant=tenant, code__iexact=rubric.code).exclude(pk=rubric.pk).exists():
                    raise
                form.add_error(None, "Não foi possível salvar: o código/versão já está cadastrado. Atualize a página e confira os dados.")
            else:
                messages.success(request, "Rubrica salva no catálogo. Nenhuma regra de cálculo ou pagamento foi alterada.")
                return redirect("rule_list")
    return render(request, "core/rubric_form.html", {"tenant": tenant, "form": form, "rubric": rubric})


@login_required
def rule_publish(request, rule_id):
    tenant = _tenant_for_user(request.user)
    if request.method != "POST" or not tenant or not _can_manage_rules(request.user, tenant):
        return render(request, "core/empty_state.html", {"title": "Ação não autorizada"}, status=403)
    rule = tenant.calculation_rules.get(id=rule_id)
    if rule.status not in {"draft", "review"}:
        messages.error(request, "Somente regras em rascunho ou revisão podem ser publicadas.")
    elif not rule.parameters:
        messages.error(request, "A regra precisa ter parâmetros antes da publicação.")
    else:
        rule.status = "published"
        rule.approved_by = request.user
        rule.published_at = timezone.now()
        rule.approval_reason = rule.approval_reason or "Publicação administrativa registrada no sistema."
        rule.save(update_fields=["status", "approved_by", "published_at", "approval_reason", "updated_at"])
        _audit(tenant=tenant, user=request.user, action="approve", entity="calculation_rule", entity_id=rule.id, after={"status": rule.status, "version": rule.version})
        messages.success(request, f"Regra {rule.code} v{rule.version} publicada.")
    return redirect("rule_list")


@login_required
def calculation_run(request):
    tenant = _tenant_for_user(request.user)
    if request.method != "POST" or not tenant or not _can_manage_rules(request.user, tenant):
        return render(request, "core/empty_state.html", {"title": "Ação não autorizada"}, status=403)
    competency = tenant.competencies.filter(status__in=["open", "review"]).order_by("-year", "-month").first()
    if not competency:
        messages.error(request, "Não existe competência aberta para calcular.")
        return redirect("dashboard")
    if PaymentCycle.objects.filter(competency=competency, status__in=["approved", "closed"]).exists():
        messages.error(request, "Há ciclo de pagamento aprovado. Reabra a competência antes de recalcular.")
        return redirect("dashboard")
    allowed_unit_ids = set(_allowed_units_for_user(request.user, tenant).values_list("pk", flat=True))
    from .rubric_applications import application_unit_ids
    required_units = application_unit_ids(competency) | set(competency.events.values_list("unit_id", flat=True))
    if not required_units.issubset(allowed_unit_ids):
        return render(request, "core/empty_state.html", {"title": "Cálculo exige acesso às unidades dos vínculos e eventos da competência"}, status=403)
    events = tenant.events.filter(competency=competency, status__in=["pending", "approved"])
    calculated, errors = 0, []
    for event in events:
        if event.event_type in {"rain_release", "rubric", "occurrence", "advance"}:
            continue
        try:
            calculate_event(event)
            calculated += 1
        except ValueError as exc:
            errors.append(str(exc))
    monthly_pairs = events.exclude(event_type__in=["rubric", "occurrence", "advance"]).values_list("collaborator_id", "unit_id").distinct()
    monthly_calculated = 0
    for collaborator_id, unit_id in monthly_pairs:
        try:
            collaborator = tenant.collaborators.get(id=collaborator_id)
            unit = tenant.units.get(id=unit_id)
            result = calculate_monthly_compensation(competency, collaborator, unit)
            generate_monthly_entries(result, request.user)
            monthly_calculated += 1
        except ValueError as exc:
            errors.append(str(exc))
    from .payments import generate_day10_entries
    try:
        generate_day10_entries(competency, request.user)
    except ValueError as exc:
        errors.append(str(exc))
    from .rubric_applications import generate_application_entries
    try:
        generate_application_entries(competency, request.user)
    except ValueError as exc:
        errors.append(str(exc))
    competency.status = "review"
    competency.save(update_fields=["status", "updated_at"])
    if errors:
        for error in errors:
            messages.warning(request, error)
        messages.warning(request, f"{calculated} evento(s) e {monthly_calculated} composição(ões) mensal(is) calculados; {len(errors)} pendência(s) precisam de configuração.")
    else:
        messages.success(request, f"{calculated} evento(s) e {monthly_calculated} composição(ões) mensal(is) calculados com sucesso.")
    return redirect("dashboard")


def _can_review(user, tenant):
    return user.is_superuser or bool(user_roles(user, tenant).intersection(["dp", "management", "platform"]))


def _can_close(user, tenant):
    return user.is_superuser or bool(user_roles(user, tenant).intersection(["management", "platform"]))


def _invalidate_approved_payment_cycles(competency, user, reason):
    cycles = PaymentCycle.objects.filter(competency=competency, status="approved")
    cycle_ids = list(cycles.values_list("id", flat=True))
    if not cycle_ids:
        return 0
    cycles.update(status="draft", approved_by=None)
    PaymentEntry.objects.filter(cycle_id__in=cycle_ids, status="approved").update(status="draft")
    _audit(
        tenant=competency.tenant,
        user=user,
        action="update",
        entity="payment_cycle",
        entity_id=",".join(str(cycle_id) for cycle_id in cycle_ids),
        after={"status": "draft", "cycle_ids": cycle_ids},
        reason=reason,
    )
    return len(cycle_ids)


@login_required
@capability_required("review")
def conference(request):
    tenant = _tenant_for_user(request.user)
    units = _allowed_units_for_user(request.user, tenant)
    competencies = tenant.competencies.all() if tenant else Competency.objects.none()
    competency_id = request.GET.get("competency", "")
    try:
        competency_id = int(competency_id)
    except (TypeError, ValueError):
        competency_id = None
    competency = competencies.filter(id=competency_id).first() if competency_id else competencies.first()
    unit_id = request.GET.get("unit", "")
    try:
        unit_id = int(unit_id)
    except (TypeError, ValueError):
        unit_id = None
    selected_unit = units.filter(id=unit_id).first() if unit_id else None
    status = request.GET.get("status", "pending")
    valid_statuses = {choice[0] for choice in FieldEvent.STATUS_CHOICES}

    scoped_events = (
        tenant.events.filter(unit__in=units)
        .select_related("unit", "collaborator", "created_by", "competency", "calculation_result", "calculation_result__rule", "application__rubric")
        .prefetch_related("payment_entries")
        .order_by("unit__name", "collaborator__name", "event_date", "created_at")
        if tenant else FieldEvent.objects.none()
    )
    monthly_results = tenant.monthly_compensation_results.filter(unit__in=units).select_related(
        "unit", "collaborator", "compensation", "competency"
    ) if tenant else MonthlyCompensationResult.objects.none()
    if competency:
        scoped_events = scoped_events.filter(competency=competency)
        monthly_results = monthly_results.filter(competency=competency)
    if selected_unit:
        scoped_events = scoped_events.filter(unit=selected_unit)
        monthly_results = monthly_results.filter(unit=selected_unit)
    status_totals = dict(scoped_events.order_by().values_list("status").annotate(total=Count("id")))
    event_counts = {event_status: status_totals.get(event_status, 0) for event_status in ("pending", "approved", "rejected")}
    events = scoped_events
    if status in valid_statuses:
        events = events.filter(status=status)
    elif status != "all":
        status = "pending"
        events = events.filter(status=status)

    event_list = list(events)
    context = {
        "tenant": tenant,
        "events": event_list,
        "monthly_results": monthly_results,
        "competencies": competencies,
        "selected_competency": competency,
        "units": units,
        "selected_unit": selected_unit,
        "selected_status": status,
        "return_url": request.get_full_path(),
        "status_choices": [("all", "Todos os status"), *FieldEvent.STATUS_CHOICES],
        "can_review": _can_review(request.user, tenant) if tenant else False,
        "pending_count": event_counts["pending"],
        "approved_count": event_counts["approved"],
        "rejected_count": event_counts["rejected"],
    }
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        response = render(request, "core/partials/conference_events.html", context)
        response["Cache-Control"] = "private, no-store"
        return response
    return render(request, "core/conference.html", context)


def _conference_redirect(request):
    """Volta à Conferência mantendo os filtros em que o analista estava trabalhando."""
    target = request.POST.get("next", "")
    if target.startswith("/conferencia/") and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return redirect(target)
    return redirect("conference")


@login_required
def conference_decision(request, event_id, decision):
    tenant = _tenant_for_user(request.user)
    if request.method != "POST" or not tenant or not _can_review(request.user, tenant):
        return render(request, "core/empty_state.html", {"title": "Ação não autorizada"}, status=403)
    if decision not in {"approve", "reject"}:
        return render(request, "core/empty_state.html", {"title": "Decisão inválida"}, status=400)
    allowed_units = _allowed_units_for_user(request.user, tenant)
    event_stub = get_object_or_404(tenant.events.filter(unit__in=allowed_units), id=event_id)
    reason = request.POST.get("reason", "").strip()
    if len(reason) < 5:
        messages.error(request, "Informe uma justificativa com pelo menos 5 caracteres.")
        return _conference_redirect(request)
    with transaction.atomic():
        competency = tenant.competencies.select_for_update().get(id=event_stub.competency_id)
        if competency.status == "closed":
            messages.error(request, "A competência está fechada. Solicite reabertura autorizada antes de alterar o evento.")
            return _conference_redirect(request)
        event = tenant.events.select_for_update().filter(
            id=event_id,
            unit__in=allowed_units,
            competency=competency,
            status="pending",
        ).first()
        if not event:
            messages.error(request, "O evento já foi alterado ou não está mais pendente; atualize a conferência.")
            return _conference_redirect(request)
        event.competency = competency
        event.status = "approved" if decision == "approve" else "rejected"
        event.approved_by = request.user
        event.save(update_fields=["status", "approved_by", "updated_at"])
        invalidated_cycles = _invalidate_approved_payment_cycles(
            event.competency,
            request.user,
            f"Evento {event.id} alterado na conferência.",
        )
        _audit(
            tenant=tenant,
            user=request.user,
            action="approve" if decision == "approve" else "update",
            entity="field_event",
            entity_id=event.id,
            before={"status": "pending"},
            after={"status": event.status},
            reason=reason,
        )
    if event.created_by_id != request.user.id:
        Notification.objects.create(tenant=tenant, recipient=event.created_by, event=event, notification_type="event", title="Evento atualizado na conferência", body=f"{event.get_event_type_display()} de {event.collaborator.name}: {event.get_status_display()}")
    if invalidated_cycles:
        messages.warning(request, "A decisão foi registrada; ciclos de pagamento anteriormente aprovados voltaram para conferência.")
    messages.success(request, f"Evento {event.get_status_display().lower()} com sucesso.")
    return _conference_redirect(request)


@login_required
@capability_required("office")
def closing(request):
    tenant = _tenant_for_user(request.user)
    if not tenant:
        return render(request, "core/empty_state.html", {"title": "Nenhum cliente configurado"})
    competencies = list(tenant.competencies.all())
    for competency in competencies:
        status_issue = _competency_status_issue(competency) if competency.status != "review" else None
        competency.issues = [] if competency.status == "closed" else [i for i in [status_issue] if i] + _competency_closing_issues(competency)
    can_close = _can_close(request.user, tenant)
    return render(request, "core/closing.html", {"tenant": tenant, "competencies": competencies, "can_close": can_close})


@login_required
def close_competency(request, competency_id, action):
    tenant = _tenant_for_user(request.user)
    if request.method != "POST" or not tenant or not _can_close(request.user, tenant):
        return render(request, "core/empty_state.html", {"title": "Ação não autorizada"}, status=403)
    competency = get_object_or_404(tenant.competencies, id=competency_id)
    reason = request.POST.get("reason", "").strip()
    if len(reason) < 5:
        messages.error(request, "Informe uma justificativa com pelo menos 5 caracteres.")
        return redirect("closing")
    label = f"{competency.month:02d}/{competency.year}"
    if action == "close":
        with transaction.atomic():
            competency = tenant.competencies.select_for_update().get(id=competency_id)
            status_issue = _competency_status_issue(competency) if competency.status != "review" else None
            issues = [i for i in [status_issue] if i] + _competency_closing_issues(competency)
            if issues:
                messages.error(request, f"Não foi possível fechar {label}: {len(issues)} pendência(s). Veja abaixo o que resolver e onde.")
            else:
                competency.close()
                _audit(tenant=tenant, user=request.user, action="close", entity="competency", entity_id=competency.id, after={"status": competency.status}, reason=reason)
                messages.success(request, f"Competência {label} fechada e protegida contra alterações diretas.")
    elif action == "reopen":
        with transaction.atomic():
            competency = tenant.competencies.select_for_update().get(id=competency_id)
            if competency.status != "closed":
                messages.error(request, f"{label} não está fechada; só competências fechadas podem ser reabertas.")
            else:
                competency.status = "review"
                competency.closed_at = None
                competency.save(update_fields=["status", "closed_at", "updated_at"])
                _invalidate_approved_payment_cycles(competency, request.user, reason)
                _audit(tenant=tenant, user=request.user, action="update", entity="competency", entity_id=competency.id, after={"status": competency.status}, reason=reason)
                messages.success(request, f"Competência {label} reaberta com auditoria.")
    return redirect("closing")


def _issue(message, action, url_name, query=""):
    """Pendência do fechamento: o que está errado, o que fazer e onde fazer."""
    return {"message": message, "action": action, "url": reverse(url_name) + query}


def _sample(names, limit=3):
    names = sorted(set(names))
    text = ", ".join(names[:limit])
    return f"{text} e mais {len(names) - limit}" if len(names) > limit else text


def _current_competency(tenant):
    """Competência que recebe os lançamentos novos (a mais recente aberta ou em conferência)."""
    return tenant.competencies.filter(status__in=["open", "review"]).order_by("-year", "-month").first()


def _competency_calculation_issues(competency, events=None):
    issues = []
    if events is None:
        events = list(competency.events.select_related("collaborator", "unit"))
    open_events = [event for event in events if event.status in {"draft", "pending"}]
    if open_events:
        totals = {}
        for event in open_events:
            totals[event.unit.name] = totals.get(event.unit.name, 0) + 1
        by_unit = ", ".join(f"{name} ({total})" for name, total in sorted(totals.items()))
        issues.append(_issue(
            f"{len(open_events)} evento(s) em rascunho ou pendentes de conferência: {by_unit}.",
            "Aprove ou rejeite cada evento na Conferência (já filtrada nesta competência).",
            "conference", f"?competency={competency.id}&status=pending",
        ))

    approved_events = [event for event in events if event.status == "approved"]
    calculated_event_ids = set(CalculationResult.objects.filter(competency=competency).values_list("event_id", flat=True))
    missing_calculations = [
        event for event in approved_events
        if event.event_type not in {"rain_release", "rubric", "occurrence", "advance"} and event.id not in calculated_event_ids
    ]
    if missing_calculations:
        who = _sample(f"{event.collaborator.name} ({event.get_event_type_display()}, {event.event_date:%d/%m})" for event in missing_calculations)
        issues.append(_issue(
            f"{len(missing_calculations)} evento(s) aprovado(s) sem cálculo: {who}.",
            "Execute o cálculo da competência em Regras. Se o erro persistir, publique a regra de cálculo do tipo de evento.",
            "rule_list",
        ))

    pairs = {(event.collaborator_id, event.unit_id) for event in approved_events if event.event_type not in {"rubric", "occurrence", "advance"}}
    calculated_pairs = set(
        MonthlyCompensationResult.objects.filter(competency=competency)
        .values_list("collaborator_id", "unit_id")
    )
    missing_pairs = pairs - calculated_pairs
    if missing_pairs:
        missing_ids = {collaborator_id for collaborator_id, _ in missing_pairs}
        names = [event.collaborator.name for event in approved_events if event.collaborator_id in missing_ids]
        issues.append(_issue(
            f"{len(missing_pairs)} composição(ões) mensal(is) sem resultado: {_sample(names)}.",
            "Execute o cálculo da competência em Regras e confira se o colaborador tem salário vigente cadastrado.",
            "rule_list",
        ))
    from .rubric_applications import application_blockers
    for message in application_blockers(competency):
        issues.append(_issue(message, "Gere as rubricas da competência na tela de Regras.", "rule_list"))
    return issues


def _competency_closing_issues(competency):
    events = list(competency.events.select_related("collaborator", "unit"))
    issues = _competency_calculation_issues(competency, events)
    approved_events = [event for event in events if event.status == "approved"]
    required_cycle_types = set()
    if any(event.event_type not in {"rubric", "occurrence", "advance"} for event in approved_events):
        required_cycle_types.add("monthly")
    if any(event.event_type == "additional_12h" for event in approved_events):
        required_cycle_types.add("day10")
    from .rubric_applications import application_sources
    sources, _ = application_sources(competency)
    required_cycle_types.update(app.cycle_type for app, *_ in sources)

    for cycle_type in sorted(required_cycle_types):
        cycle = PaymentCycle.objects.filter(competency=competency, cycle_type=cycle_type).first()
        label = "mensal" if cycle_type == "monthly" else "do dia 10"
        if not cycle:
            issues.append(_issue(f"O ciclo {label} ainda não foi gerado.", "Execute o cálculo da competência em Regras para gerar o ciclo.", "rule_list"))
            continue
        if cycle.status != "approved":
            issues.append(_issue(f"O ciclo {label} ainda não foi aprovado.", "Revise e aprove o ciclo em Pagamentos.", "payment_cycles"))
        if not cycle.entries.exists():
            issues.append(_issue(f"O ciclo {label} não possui lançamentos.", "Execute o cálculo em Regras; sem lançamentos o ciclo não pode ser aprovado.", "rule_list"))
        elif cycle.entries.exclude(status="approved").exists():
            issues.append(_issue(f"O ciclo {label} contém lançamentos não aprovados.", "Aprove o ciclo em Pagamentos.", "payment_cycles"))

    if PaymentCycle.objects.filter(competency=competency).exclude(status="approved").exists() and not any("ciclo" in issue["message"] for issue in issues):
        issues.append(_issue("Há ciclos de pagamento não aprovados.", "Revise e aprove os ciclos em Pagamentos.", "payment_cycles"))
    return issues


def _competency_status_issue(competency):
    """Pré-requisito de status: só competências em conferência podem ser fechadas."""
    label = f"{competency.month:02d}/{competency.year}"
    if competency.status == "open":
        current = _current_competency(competency.tenant)
        if current and current.pk != competency.pk:
            return _issue(
                f"{label} está Aberta e não é a competência corrente: o cálculo e os lançamentos usam {current.month:02d}/{current.year}.",
                "Se ela foi criada por engano, exclua-a em Configurações (só é possível sem lançamentos); caso contrário, conclua antes a competência corrente.",
                "settings_page",
            )
        return _issue(
            f"{label} ainda está Aberta: o cálculo não foi executado.",
            "Execute o cálculo da competência em Regras para colocá-la em conferência.",
            "rule_list",
        )
    if competency.status == "closed":
        return _issue(f"{label} já está fechada.", "Para alterar, reabra a competência com justificativa.", "closing")
    return None


def _competency_calculation_blockers(competency):
    return [issue["message"] for issue in _competency_calculation_issues(competency)]


def _competency_closing_blockers(competency):
    return [issue["message"] for issue in _competency_closing_issues(competency)]


EVENT_COST_STATUS_CHOICES = [
    ("approved", "Somente aprovados"),
    ("pending", "Somente pendentes"),
    ("draft", "Somente rascunhos"),
    ("rejected", "Somente rejeitados"),
    ("all", "Todos os status"),
]


@login_required
@capability_required("office")
def reports(request):
    tenant = _tenant_for_user(request.user)
    units = _allowed_units_for_user(request.user, tenant)
    filters = {key: request.GET.get(key, "") for key in ["report_type", "company", "unit", "competency", "status"]}
    report_type = filters["report_type"] or "cost"
    if report_type == "event_costs":
        cost_data = build_event_cost_dashboard(tenant, units, filters)
        filters = cost_data["filters"]
        rows = cost_data["rows"]
        inconsistencies = []
    elif report_type == "events":
        cost_data = {}
        queryset = tenant.events.filter(unit__in=units).select_related("unit", "collaborator", "competency") if tenant else FieldEvent.objects.none()
        if filters["status"] in dict(FieldEvent.STATUS_CHOICES):
            queryset = queryset.filter(status=filters["status"])
        elif filters["status"] not in {"", "all"}:
            queryset = queryset.none()
        if filters["unit"]:
            queryset = queryset.filter(unit_id=filters["unit"])
        if filters["competency"]:
            queryset = queryset.filter(competency_id=filters["competency"])
    elif report_type == "monthly":
        cost_data = {}
        queryset = tenant.monthly_compensation_results.filter(unit__in=units) if tenant else []
        if filters["unit"]:
            queryset = queryset.filter(unit_id=filters["unit"])
        if filters["competency"]:
            queryset = queryset.filter(competency_id=filters["competency"])
    else:
        cost_data = {}
        queryset = tenant.calculation_results.filter(event__unit__in=units).values("event__unit__name", "competency__year", "competency__month").annotate(total=Sum("calculated_amount")).order_by("-competency__year", "-competency__month", "event__unit__name") if tenant else []
        if filters["unit"]:
            queryset = queryset.filter(event__unit_id=filters["unit"])
        if filters["competency"]:
            queryset = queryset.filter(competency_id=filters["competency"])
    if report_type != "event_costs":
        rows, inconsistencies = build_report_data(queryset, report_type)
    context = {
        "tenant": tenant,
        "rows": rows,
        "inconsistencies": inconsistencies,
        "report_type": report_type,
        "filters": filters,
        "units": units,
        "competencies": tenant.competencies.all() if tenant else [],
        "status_choices": FieldEvent.STATUS_CHOICES,
        "cost_status_choices": EVENT_COST_STATUS_CHOICES,
    }
    if cost_data:
        context.update(cost_data)
        context["units"] = cost_data["units_for_filter"]
    return render(request, "core/reports.html", context)


@login_required
@capability_required("office")
def report_export(request, file_format):
    tenant = _tenant_for_user(request.user)
    units = _allowed_units_for_user(request.user, tenant)
    report_type = request.GET.get("report_type", "cost")
    filters = {key: request.GET.get(key, "") for key in ["report_type", "company", "unit", "competency", "status"]}
    if report_type == "event_costs":
        cost_data = build_event_cost_dashboard(tenant, units, filters)
        filters = cost_data["filters"]
        rows = cost_data["rows"]
        inconsistencies = []
    elif report_type == "events":
        cost_data = {}
        queryset = tenant.events.filter(unit__in=units).select_related("unit", "collaborator", "competency")
        if filters["status"] in dict(FieldEvent.STATUS_CHOICES): queryset = queryset.filter(status=filters["status"])
        elif filters["status"] not in {"", "all"}: queryset = queryset.none()
        if filters["unit"]: queryset = queryset.filter(unit_id=filters["unit"])
        if filters["competency"]: queryset = queryset.filter(competency_id=filters["competency"])
    elif report_type == "monthly":
        cost_data = {}
        queryset = tenant.monthly_compensation_results.filter(unit__in=units)
        if filters["unit"]: queryset = queryset.filter(unit_id=filters["unit"])
        if filters["competency"]: queryset = queryset.filter(competency_id=filters["competency"])
    else:
        cost_data = {}
        queryset = tenant.calculation_results.filter(event__unit__in=units).values("event__unit__name", "competency__year", "competency__month").annotate(total=Sum("calculated_amount")).order_by("-competency__year", "-competency__month", "event__unit__name")
        if filters["unit"]: queryset = queryset.filter(event__unit_id=filters["unit"])
        if filters["competency"]: queryset = queryset.filter(competency_id=filters["competency"])
    if report_type != "event_costs":
        rows, inconsistencies = build_report_data(queryset, report_type)
    if report_type == "event_costs":
        title = "Custos calculados por evento"
    elif report_type == "events":
        title = "Relatório de eventos"
    elif report_type == "monthly":
        title = "Composição mensal CLT e combinado"
    else:
        title = "Relatório de custo por unidade"
    issued_at = timezone.localtime().strftime("%d/%m/%Y %H:%M")
    metadata = {"title": title, "user": request.user.get_full_name() or request.user.username, "issued_at": issued_at, "filters_text": ", ".join(f"{k}: {v}" for k, v in filters.items() if v) or "Sem filtros"}
    extension = file_format if file_format in {"xlsx", "pdf"} else "pdf"
    filename = f"fechamento_campo_{report_type}_{timezone.localtime():%Y%m%d_%H%M%S}.{extension}"
    ReportEmission.objects.create(tenant=tenant, user=request.user, report_type=report_type, file_format=extension, filters=filters, row_count=len(rows), file_name=filename)
    _audit(tenant=tenant, user=request.user, action="export", entity="report", entity_id=filename, after={"report_type": report_type, "format": extension, "row_count": len(rows), "filters": filters})
    if extension == "xlsx":
        return response_file(create_xlsx(report_type, rows, inconsistencies, metadata), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", filename)
    return response_file(create_pdf(report_type, rows, inconsistencies, metadata), "application/pdf", filename)


COMPETENCY_DEPENDENCY_LABELS = {
    "fieldevent": "lançamentos de campo",
    "paymentcycle": "ciclos de pagamento",
    "calculationresult": "resultados de cálculo",
    "monthlycompensationresult": "composições mensais",
    "importbatch": "importações",
    "communicationthread": "conversas de comunicação",
    "dataqualityissue": "inconsistências de qualidade",
}


def _competencies_dependencies(competencies):
    """Registros que impedem excluir cada competência: {id: [("lançamentos de campo", 3)]}, com uma consulta por tabela."""
    found = {competency.pk: [] for competency in competencies}
    for relation in Competency._meta.related_objects:
        totals = (
            relation.related_model._default_manager
            .filter(**{f"{relation.field.name}__in": list(found)})
            .order_by().values_list(relation.field.name).annotate(total=Count("pk"))
        )
        label = COMPETENCY_DEPENDENCY_LABELS.get(relation.related_model._meta.model_name, str(relation.related_model._meta.verbose_name_plural))
        for competency_id, total in totals:
            found[competency_id].append((label, total))
    return found


def _competency_dependencies(competency):
    return _competencies_dependencies([competency])[competency.pk]


def _settings_context(request, tenant, competency_form=None):
    scopes = [scope for scope in user_scopes(request.user) if scope.tenant_id == tenant.pk] if tenant else []
    can_manage = bool(tenant and _can_manage_rules(request.user, tenant))
    context = {"tenant": tenant, "scopes": scopes, "can_manage_competencies": can_manage}
    if can_manage:
        competencies = list(tenant.competencies.all())
        current = next((item for item in competencies if item.status in {"open", "review"}), None)
        dependencies = _competencies_dependencies(competencies)
        for competency in competencies:
            competency.is_current = bool(current and current.pk == competency.pk)
            competency.dependencies = dependencies[competency.pk]
            competency.can_delete = competency.status == "open" and not competency.dependencies
        context.update(
            competencies=competencies,
            current_competency=current,
            competency_form=competency_form or CompetencyForm(tenant=tenant),
        )
    return context


@login_required
def settings_page(request):
    tenant = _tenant_for_user(request.user)
    return render(request, "core/settings.html", _settings_context(request, tenant))


@login_required
@require_POST
def competency_delete(request, competency_id):
    tenant = _tenant_for_user(request.user)
    if not tenant or not _can_manage_rules(request.user, tenant):
        return render(request, "core/empty_state.html", {"title": "Acesso restrito às competências"}, status=403)
    with transaction.atomic():
        competency = get_object_or_404(tenant.competencies.select_for_update(), id=competency_id)
        label = f"{competency.month:02d}/{competency.year}"
        dependencies = _competency_dependencies(competency)
        if competency.status != "open":
            messages.error(request, f"{label} está {competency.get_status_display().lower()} e não pode ser excluída; apenas competências abertas e sem movimentação.")
        elif dependencies:
            found = ", ".join(f"{count} {name}" for name, count in dependencies)
            messages.error(request, f"{label} não pode ser excluída: já possui {found}. Esses registros fazem parte do histórico auditável da folha.")
        else:
            before = {"year": competency.year, "month": competency.month, "status": competency.status}
            entity_id = competency.pk
            competency.delete()
            _audit(
                tenant=tenant, user=request.user, action="delete", entity="competency", entity_id=entity_id,
                before=before, reason="Competência aberta e sem movimentação excluída pela tela de Configurações.",
            )
            messages.success(request, f"Competência {label} excluída.")
    return redirect("settings_page")


@login_required
@require_POST
def competency_create(request):
    tenant = _tenant_for_user(request.user)
    if not tenant or not _can_manage_rules(request.user, tenant):
        return render(request, "core/empty_state.html", {"title": "Acesso restrito às competências"}, status=403)
    form = CompetencyForm(request.POST, tenant=tenant)
    if not form.is_valid():
        return render(request, "core/settings.html", _settings_context(request, tenant, form), status=400)
    with transaction.atomic():
        competency = form.save()
        _audit(
            tenant=tenant,
            user=request.user,
            action="create",
            entity="competency",
            entity_id=competency.pk,
            after={"year": competency.year, "month": competency.month, "status": "open"},
            reason="Competência criada com status inicial aberto pela tela de Configurações.",
        )
    messages.success(request, f"Competência {competency.month:02d}/{competency.year} criada.")
    return redirect("settings_page")


@login_required
@capability_required("office")
def health_dashboard(request):
    tenant = _tenant_for_user(request.user)
    if not tenant:
        return render(request, "core/empty_state.html", {"title": "Nenhum cliente configurado"})
    units = _allowed_units_for_user(request.user, tenant)
    summary = health_summary(tenant, units)
    return render(request, "core/health.html", {"tenant": tenant, "units": units, **summary})


@login_required
@capability_required("office")
def payment_cycles(request):
    tenant = _tenant_for_user(request.user)
    if not tenant:
        return render(request, "core/empty_state.html", {"title": "Nenhum cliente configurado"})
    units = _allowed_units_for_user(request.user, tenant)
    unit_ids = set(units.values_list("id", flat=True))
    cycles = tenant.payment_cycles.prefetch_related("entries__collaborator", "entries__rubric", "entries__unit").all()
    visible = []
    for cycle in cycles:
        entries = [entry for entry in cycle.entries.all() if entry.unit_id in unit_ids]
        cycle_unit_ids = set(cycle.entries.values_list("unit_id", flat=True))
        visible.append({
            "cycle": cycle,
            "entries": entries,
            "total": sum((entry.amount for entry in entries), Decimal("0.00")),
            "can_approve": _can_review(request.user, tenant) and cycle_unit_ids.issubset(unit_ids),
        })
    return render(request, "core/payment_cycles.html", {"tenant": tenant, "cycles": visible})


@login_required
@require_POST
def payment_cycle_approve(request, cycle_id):
    tenant = _tenant_for_user(request.user)
    if not tenant or not _can_review(request.user, tenant):
        return render(request, "core/empty_state.html", {"title": "Ação não autorizada"}, status=403)
    cycle = get_object_or_404(PaymentCycle.objects.select_related("competency"), id=cycle_id, tenant=tenant)
    reason = request.POST.get("reason", "").strip()
    if len(reason) < 5:
        messages.error(request, "Informe uma justificativa com pelo menos 5 caracteres.")
        return redirect("payment_cycles")
    with transaction.atomic():
        competency = tenant.competencies.select_for_update().get(pk=cycle.competency_id)
        cycle = PaymentCycle.objects.select_for_update().get(pk=cycle.pk, tenant=tenant)
        cycle.competency = competency
        if cycle.status not in {"draft", "review"}:
            messages.error(request, "Somente ciclos em rascunho ou conferência podem ser aprovados.")
            return redirect("payment_cycles")
        if competency.status != "review":
            messages.error(request, "A competência precisa estar em conferência antes da aprovação do ciclo.")
            return redirect("payment_cycles")
        allowed_unit_ids = set(_allowed_units_for_user(request.user, tenant).values_list("id", flat=True))
        cycle_unit_ids = set(cycle.entries.values_list("unit_id", flat=True))
        if not cycle_unit_ids or not cycle_unit_ids.issubset(allowed_unit_ids):
            return render(request, "core/empty_state.html", {"title": "A aprovação exige acesso a todas as unidades do ciclo"}, status=403)
        blockers = _competency_calculation_blockers(competency)
        if blockers:
            messages.error(request, "Aprovação bloqueada: " + " ".join(blockers))
            return redirect("payment_cycles")
        if not cycle.entries.exists():
            messages.error(request, "Não é possível aprovar um ciclo sem lançamentos.")
            return redirect("payment_cycles")
        if cycle.entries.exclude(status__in=["draft", "review"]).exists():
            messages.error(request, "O ciclo contém lançamentos em estado que não pode ser aprovado.")
            return redirect("payment_cycles")
        cycle.entries.update(status="approved")
        cycle.status = "approved"
        cycle.approved_by = request.user
        cycle.save(update_fields=["status", "approved_by", "updated_at"])
        _audit(
            tenant=tenant,
            user=request.user,
            action="approve",
            entity="payment_cycle",
            entity_id=cycle.id,
            after={"status": cycle.status, "entry_count": cycle.entries.count()},
            reason=reason,
        )
    messages.success(request, "Ciclo de pagamento aprovado.")
    return redirect("payment_cycles")


def _can_import(user, tenant):
    return user.is_superuser or bool(user_roles(user, tenant).intersection(["dp", "platform", "management"]))


def _can_admission(user, tenant):
    return user.is_superuser or bool(user_roles(user, tenant).intersection(["dp", "platform", "management"]))


def _ensure_admission_fields(tenant):
    defaults = [
        ("full_name", "Nome completo", "Dados pessoais", "text", True, []),
        ("social_name", "Nome social", "Dados pessoais", "text", False, []),
        ("cpf", "CPF", "Dados pessoais", "text", True, []),
        ("birth_date", "Data de nascimento", "Dados pessoais", "date", True, []),
        ("sex", "Sexo", "Dados pessoais", "choice", False, ["Feminino", "Masculino", "Outro", "Prefiro não informar"]),
        ("marital_status", "Estado civil", "Dados pessoais", "choice", False, ["Solteiro(a)", "Casado(a)", "Divorciado(a)", "Viúvo(a)", "União estável"]),
        ("nationality", "Nacionalidade", "Dados pessoais", "text", False, []),
        ("birthplace", "Naturalidade", "Dados pessoais", "text", False, []),
        ("mother_name", "Nome da mãe", "Dados pessoais", "text", False, []),
        ("email", "E-mail", "Contato", "email", False, []),
        ("phone_secondary", "Telefone alternativo", "Contato", "phone", False, []),
        ("postal_code", "CEP", "Endereço", "text", False, []),
        ("street", "Logradouro", "Endereço", "text", False, []),
        ("address_number", "Número", "Endereço", "text", False, []),
        ("address_complement", "Complemento", "Endereço", "text", False, []),
        ("neighborhood", "Bairro", "Endereço", "text", False, []),
        ("city", "Cidade", "Endereço", "text", False, []),
        ("state", "Estado", "Endereço", "text", False, []),
        ("employment_type", "Tipo de contrato", "Dados profissionais", "choice", False, ["Experiência", "Prazo determinado", "Prazo indeterminado", "Safra", "Outro"]),
        ("previous_experience", "Experiência profissional relevante", "Dados profissionais", "long_text", False, []),
        ("emergency_name", "Nome do contato de emergência", "Contato de emergência", "text", False, []),
        ("emergency_relationship", "Grau de parentesco", "Contato de emergência", "text", False, []),
        ("emergency_phone", "Telefone do contato de emergência", "Contato de emergência", "phone", False, []),
    ]
    for order, (code, label, section, field_type, required, choices) in enumerate(defaults, start=1):
        AdmissionFieldDefinition.objects.get_or_create(tenant=tenant, code=code, defaults={"label": label, "section": section, "field_type": field_type, "required": required, "choices": choices, "sort_order": order})
    # Campos da primeira versão foram substituídos por endereço detalhado e contato de emergência dividido.
    AdmissionFieldDefinition.objects.filter(tenant=tenant, code__in=["address", "emergency_contact"]).update(active=False)


@login_required
def admission_list(request):
    tenant = _tenant_for_user(request.user)
    if not tenant or not _can_admission(request.user, tenant):
        return render(request, "core/empty_state.html", {"title": "Acesso restrito à pré-admissão"}, status=403)
    _ensure_admission_fields(tenant)
    requests = tenant.admission_requests.select_related("company", "unit", "created_by").all()
    return render(request, "core/admission_list.html", {"tenant": tenant, "admissions": requests})


@login_required
def admission_create(request):
    tenant = _tenant_for_user(request.user)
    if not tenant or not _can_admission(request.user, tenant):
        return render(request, "core/empty_state.html", {"title": "Acesso restrito à pré-admissão"}, status=403)
    form = AdmissionRequestForm(request.POST or None, tenant=tenant)
    if request.method == "POST" and form.is_valid():
        raw_key = secrets.token_hex(4).upper()
        admission = form.save(commit=False)
        admission.tenant = tenant
        admission.created_by = request.user
        admission.access_key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        admission.access_key_hint = raw_key[-2:]
        admission.expires_at = timezone.now() + timedelta(days=15)
        admission.status = "in_progress"
        admission.save()
        _audit(tenant=tenant, user=request.user, action="create", entity="admission_request", entity_id=admission.id, after={"candidate_name": admission.candidate_name, "company_id": admission.company_id, "unit_id": admission.unit_id})
        return render(request, "core/admission_created.html", {"tenant": tenant, "admission": admission, "access_key": raw_key})
    return render(request, "core/admission_form.html", {"tenant": tenant, "form": form})


def admission_public(request, token):
    admission = get_object_or_404(AdmissionRequest.objects.select_related("company", "unit", "tenant"), token=token)
    if admission.expires_at and admission.expires_at < timezone.now() and admission.status not in ["submitted", "approved"]:
        admission.status = "expired"
        admission.save(update_fields=["status", "updated_at"])
    if admission.status in ["cancelled", "expired", "approved"]:
        return render(request, "core/admission_public_closed.html", {"admission": admission})
    _ensure_admission_fields(admission.tenant)
    access_session_key = f"admission_access_{admission.id}"
    if request.session.get(access_session_key) != str(admission.token):
        access_form = AdmissionAccessForm(request.POST or None)
        if request.method == "POST" and access_form.is_valid() and hashlib.sha256(access_form.cleaned_data["chave"].upper().encode()).hexdigest() == admission.access_key_hash:
            request.session[access_session_key] = str(admission.token)
            return redirect("admission_public", token=admission.token)
        if request.method == "POST":
            access_form.add_error("chave", "Chave inválida. Confira a chave enviada pelo RH.")
        return render(request, "core/admission_access.html", {"admission": admission, "form": access_form})
    if admission.status == "submitted":
        return render(request, "core/admission_public_closed.html", {"admission": admission})
    fields = list(admission.tenant.admission_fields.filter(active=True).filter(models.Q(company__isnull=True) | models.Q(company=admission.company)).filter(models.Q(unit__isnull=True) | models.Q(unit=admission.unit)))
    public_form = build_public_form(request, fields, request.POST or None)
    if request.method == "POST" and public_form.is_valid():
        action = request.POST.get("action")
        if action not in {"save", "submit"}:
            public_form.add_error(None, "Ação inválida. Atualize a página e tente novamente.")
            return render(request, "core/admission_public_form.html", {"admission": admission, "form": public_form, "fields": fields})
        for field in fields:
            value = public_form.cleaned_data.get(field.code)
            if hasattr(value, "isoformat"):
                value = value.isoformat()
            AdmissionFieldValue.objects.update_or_create(request=admission, field=field, defaults={"value": value, "changed_by": None})
        admission.status = "submitted" if action == "submit" else "in_progress"
        if admission.status == "submitted":
            admission.submitted_at = timezone.now()
        admission.save(update_fields=["status", "submitted_at", "updated_at"])
        return render(request, "core/admission_public_success.html", {"admission": admission, "submitted": action == "submit"})
    values = {item.field.code: item.value for item in admission.field_values.select_related("field")}
    for code, value in values.items():
        if code in public_form.fields:
            public_form.fields[code].initial = value
    return render(request, "core/admission_public_form.html", {"admission": admission, "form": public_form, "fields": fields})


@login_required
@require_POST
def admission_review(request, admission_id, action):
    tenant = _tenant_for_user(request.user)
    if not tenant or not _can_admission(request.user, tenant):
        return render(request, "core/empty_state.html", {"title": "Acesso restrito à pré-admissão"}, status=403)
    admission = get_object_or_404(AdmissionRequest, id=admission_id, tenant=tenant)
    if action not in ["approve", "return", "cancel"]:
        return redirect("admission_list")
    allowed_statuses = {
        "approve": {"submitted", "returned"},
        "return": {"submitted"},
        "cancel": {"draft", "in_progress", "submitted", "returned"},
    }
    if admission.status not in allowed_statuses[action]:
        messages.error(request, "A pré-admissão não está em um estado válido para esta ação.")
        return redirect("admission_detail", admission_id=admission.id)
    if action == "approve" and request.POST.get("review_confirmed") != "1":
        messages.error(request, "A aprovação exige a conferência das respostas do candidato.")
        return redirect("admission_detail", admission_id=admission.id)
    admission.status = {"approve": "approved", "return": "returned", "cancel": "cancelled"}[action]
    admission.reviewed_by = request.user
    admission.reviewed_at = timezone.now()
    admission.review_note = request.POST.get("note", "")
    admission.save(update_fields=["status", "reviewed_by", "reviewed_at", "review_note", "updated_at"])
    _audit(tenant=tenant, user=request.user, action="approve" if action == "approve" else "update", entity="admission_request", entity_id=admission.id, after={"status": admission.status}, reason=admission.review_note)
    messages.success(request, f"Pré-admissão {admission.get_status_display().lower()}.")
    return redirect("admission_list")


@login_required
@transaction.atomic
def admission_edit(request, admission_id):
    tenant = _tenant_for_user(request.user)
    if not tenant or not _can_admission(request.user, tenant):
        return render(request, "core/empty_state.html", {"title": "Acesso restrito à pré-admissão"}, status=403)
    admission = get_object_or_404(AdmissionRequest.objects.select_for_update(), id=admission_id, tenant=tenant)
    if admission.converted_link_id:
        messages.error(request, "A pré-admissão convertida não pode ser editada. Consulte o vínculo gerado.")
        return redirect("admission_detail", admission_id=admission.pk)
    form = AdmissionReviewForm(request.POST or None, instance=admission, tenant=tenant)
    if request.method == "POST" and form.is_valid():
        form.save()
        _audit(tenant=tenant, user=request.user, action="update", entity="admission_request", entity_id=admission.id, after={"candidate_name": admission.candidate_name, "company_id": admission.company_id, "unit_id": admission.unit_id}, reason="Edição administrativa da pré-admissão")
        messages.success(request, "Pré-admissão atualizada.")
        return redirect("admission_list")
    return render(request, "core/admission_edit.html", {"admission": admission, "form": form})


@login_required
def admission_detail(request, admission_id):
    tenant = _tenant_for_user(request.user)
    if not tenant or not _can_admission(request.user, tenant):
        return render(request, "core/empty_state.html", {"title": "Acesso restrito à pré-admissão"}, status=403)
    admission = get_object_or_404(AdmissionRequest.objects.select_related("company", "unit", "created_by", "converted_by", "converted_link__collaborator"), id=admission_id, tenant=tenant)
    values = admission.field_values.select_related("field").order_by("field__section", "field__sort_order", "field__label")
    return render(request, "core/admission_detail.html", {
        "admission": admission, "values": values,
        "can_convert": can_convert_admission(request.user, admission),
    })


@login_required
@capability_required("admissions")
def admission_convert(request, admission_id):
    tenant = _tenant_for_user(request.user)
    admission = get_object_or_404(AdmissionRequest, pk=admission_id, tenant=tenant)
    if not can_convert_admission(request.user, admission):
        return render(request, "core/empty_state.html", {"title": "Acesso restrito à conversão nesta unidade"}, status=403)
    if admission.status != "approved" or admission.converted_link_id:
        messages.error(request, "A conversão exige uma pré-admissão aprovada e ainda não convertida.")
        return redirect("admission_detail", admission_id=admission.pk)
    values = {item.field.code: item.value for item in admission.field_values.select_related("field")}
    form = AdmissionConversionForm(
        request.POST if request.method == "POST" else None,
        initial={
            "full_name": values.get("full_name") or admission.candidate_name,
            "cpf": values.get("cpf") or "",
            "job_title": admission.job_title,
            "admission_date": admission.expected_admission_date,
        },
    )
    if request.method == "POST" and form.is_valid():
        try:
            convert_admission(admission_id=admission.pk, user=request.user, data=form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc)
        except IntegrityError:
            form.add_error(None, "O cadastro foi alterado por outra operação. Atualize a página e confira os dados antes de tentar novamente.")
        else:
            messages.success(request, "Pré-admissão convertida em colaborador e vínculo. Nenhum salário ou pagamento foi gerado.")
            return redirect("admission_detail", admission_id=admission.pk)
    return render(request, "core/admission_convert.html", {"admission": admission, "form": form})


@login_required
def admission_regenerate_access(request, admission_id):
    tenant = _tenant_for_user(request.user)
    if not tenant or not _can_admission(request.user, tenant):
        return render(request, "core/empty_state.html", {"title": "Acesso restrito à pré-admissão"}, status=403)
    admission = get_object_or_404(AdmissionRequest, id=admission_id, tenant=tenant)
    if request.method != "POST":
        return redirect("admission_list")
    if admission.converted_link_id:
        messages.error(request, "A pré-admissão convertida permanece encerrada para o candidato.")
        return redirect("admission_detail", admission_id=admission.pk)
    raw_key = secrets.token_hex(4).upper()
    admission.access_key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    admission.access_key_hint = raw_key[-2:]
    admission.expires_at = timezone.now() + timedelta(days=15)
    if admission.status in ["expired", "cancelled"]:
        admission.status = "in_progress"
    admission.save(update_fields=["access_key_hash", "access_key_hint", "expires_at", "status", "updated_at"])
    _audit(tenant=tenant, user=request.user, action="update", entity="admission_access", entity_id=admission.id, after={"access_key_hint": admission.access_key_hint}, reason="Regeneração de acesso")
    return render(request, "core/admission_created.html", {"tenant": tenant, "admission": admission, "access_key": raw_key})


@login_required
def import_workbook(request):
    tenant = _tenant_for_user(request.user)
    if not tenant or not _can_import(request.user, tenant):
        return render(request, "core/empty_state.html", {"title": "Acesso restrito à importação"}, status=403)
    form = ImportWorkbookForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        uploaded = form.cleaned_data["file"]
        batch = ImportBatch.objects.create(tenant=tenant, original_name=uploaded.name, file=uploaded, sha256="pending", created_by=request.user)
        try:
            batch.sha256 = sha256_file(batch.file.path)
            if batch.original_name.lower().endswith(".pdf"):
                inspection = inspect_payroll_pdf(batch.file.path)
                validation = validate_payroll_pdf(inspection, tenant)
                batch.detected = validation["detected"]
                batch.preview = inspection["preview"]
                batch.validation_rows = validation["validation_rows"]
                batch.errors = validation["errors"]
            else:
                inspection = inspect_workbook(batch.file.path, form.cleaned_data.get("sheet_name") or None)
                validation = validate_workbook(batch.file.path, tenant, inspection["sheet_name"], inspection["header_row"])
                batch.sheet_name = inspection["sheet_name"]
                batch.header_row = inspection["header_row"]
                batch.detected = {**inspection["detected"], "source_format": "XLSX", "sheet_names": inspection["sheet_names"], "row_count": inspection["row_count"], "matched_rows": validation["matched_rows"]}
                batch.preview = inspection["preview"]
                batch.validation_rows = validation["validation_rows"]
                batch.errors = inspection["errors"] + validation["errors"]
                batch.company = validation["company"]
                batch.competency = validation["competency"]
            if batch.original_name.lower().endswith(".pdf"):
                batch.company = validation["company"]
                batch.competency = validation["competency"]
            batch.save(update_fields=["sha256", "sheet_name", "header_row", "detected", "preview", "validation_rows", "errors", "company", "competency", "updated_at"])
            messages.success(request, "Arquivo analisado. A prévia não grava nem confirma dados financeiros.")
            return render(request, "core/import_preview.html", {"tenant": tenant, "form": ImportWorkbookForm(), "batch": batch})
        except Exception as exc:
            batch.errors = [str(exc)]
            batch.status = "rejected"
            batch.save(update_fields=["sha256", "errors", "status", "updated_at"])
            messages.error(request, f"Não foi possível analisar o arquivo: {exc}")
    batches = tenant.import_batches.select_related("created_by").all()[:10]
    return render(request, "core/import_workbook.html", {"tenant": tenant, "form": form, "batches": batches})


@login_required
def roster_import_template(request):
    tenant = _tenant_for_user(request.user)
    if not tenant or not _can_import(request.user, tenant):
        return render(request, "core/empty_state.html", {"title": "Acesso restrito à importação cadastral"}, status=403)
    buffer = BytesIO()
    create_roster_template().save(buffer)
    buffer.seek(0)
    return FileResponse(buffer, as_attachment=True, filename="Modelo_Carga_Cadastral.xlsx", content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@login_required
def roster_import(request):
    tenant = _tenant_for_user(request.user)
    if not tenant or not _can_import(request.user, tenant):
        return render(request, "core/empty_state.html", {"title": "Acesso restrito à importação cadastral"}, status=403)
    form = RosterImportForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        uploaded = form.cleaned_data["file"]
        try:
            result = prepare_roster_import(uploaded, tenant)
            preview = [{key: row.get(key) for key in ("row", "source_rows", "name", "company_name", "company_cnpj", "unit", "employee_code", "job_title", "admission_date", "termination_date", "status", "message")} for row in result["rows"]]
            batch = RosterImportBatch.objects.create(
                tenant=tenant,
                original_name=uploaded.name,
                sha256=result["sha256"],
                sheet_name=result["sheet_name"],
                row_count=result["row_count"],
                detected={key: result[key] for key in ("ready_count", "existing_count", "error_count", "unit_count", "person_count", "warnings")},
                validation_rows=result["rows"],
                preview=preview,
                errors=result["errors"],
                created_by=request.user,
            )
            return render(request, "core/roster_import_preview.html", {"tenant": tenant, "batch": batch})
        except Exception as exc:
            form.add_error("file", str(exc))
    batches = tenant.roster_import_batches.select_related("created_by", "confirmed_by").all()[:10]
    return render(request, "core/roster_import.html", {"tenant": tenant, "form": form, "batches": batches})


@login_required
@require_POST
def roster_import_confirm(request, batch_id):
    tenant = _tenant_for_user(request.user)
    if not tenant or not _can_import(request.user, tenant):
        return render(request, "core/empty_state.html", {"title": "Ação não autorizada"}, status=403)
    batch = get_object_or_404(RosterImportBatch, pk=batch_id, tenant=tenant)
    try:
        result = apply_roster_import(batch, request.user)
    except (ValueError, IntegrityError) as exc:
        messages.error(request, f"Carga não confirmada: {exc}")
        return redirect("roster_import")
    _audit(tenant=tenant, user=request.user, action="create", entity="roster_import_batch", entity_id=batch.id, after=result, reason="Confirmação explícita de carga cadastral XLSX")
    messages.success(request, f"Carga concluída: {result['created_units']} unidades, {result['created_people']} pessoas e {result['created_links']} vínculos novos; {result['skipped_links']} já existentes ignorados.")
    return redirect("roster_import")


def _thread_scope(user, tenant):
    units = _allowed_units_for_user(user, tenant)
    return tenant.communication_threads.filter(unit__isnull=True) | tenant.communication_threads.filter(unit__in=units)


@login_required
def communications(request):
    tenant = _tenant_for_user(request.user)
    units = _allowed_units_for_user(request.user, tenant)
    threads = _thread_scope(request.user, tenant).select_related("unit", "competency", "assigned_to", "created_by").distinct() if tenant else CommunicationThread.objects.none()
    if request.GET.get("unit"):
        threads = threads.filter(unit_id=request.GET["unit"])
    if request.GET.get("competency"):
        threads = threads.filter(competency_id=request.GET["competency"])
    if request.GET.get("status"):
        threads = threads.filter(status=request.GET["status"])
    if request.GET.get("priority"):
        threads = threads.filter(priority=request.GET["priority"])
    notifications = request.user.notifications.filter(tenant=tenant, read_at__isnull=True)[:8] if tenant else []
    return render(request, "core/communications.html", {"tenant": tenant, "threads": threads, "notifications": notifications, "units": units, "competencies": tenant.competencies.all() if tenant else [], "status_choices": CommunicationThread.STATUS_CHOICES, "priority_choices": CommunicationThread.PRIORITY_CHOICES})


@login_required
def communication_new(request):
    tenant = _tenant_for_user(request.user)
    if not tenant:
        return render(request, "core/empty_state.html", {"title": "Nenhum cliente configurado"})
    units = _allowed_units_for_user(request.user, tenant)
    form = CommunicationThreadForm(request.POST or None)
    form.fields["unit"].queryset = units
    form.fields["competency"].queryset = tenant.competencies.all()
    form.fields["assigned_to"].queryset = User.objects.filter(scopes__tenant=tenant, is_active=True).distinct()
    if request.method == "POST" and form.is_valid():
        thread = form.save(commit=False)
        thread.tenant = tenant
        thread.created_by = request.user
        if thread.unit_id and not units.filter(id=thread.unit_id).exists():
            form.add_error("unit", "Você não possui acesso a esta unidade.")
        else:
            thread.save()
            CommunicationMessage.objects.create(thread=thread, author=request.user, body=f"Pendência criada: {thread.title}")
            _audit(tenant=tenant, user=request.user, action="create", entity="communication_thread", entity_id=thread.id, after={"title": thread.title, "priority": thread.priority, "unit_id": thread.unit_id})
            if thread.assigned_to_id and thread.assigned_to_id != request.user.id:
                Notification.objects.create(tenant=tenant, recipient=thread.assigned_to, thread=thread, title="Nova pendência atribuída", body=thread.title)
            messages.success(request, "Pendência criada e encaminhada.")
            return redirect("communication_detail", thread.id)
    return render(request, "core/communication_form.html", {"form": form})


@login_required
def communication_detail(request, thread_id):
    tenant = _tenant_for_user(request.user)
    thread = get_object_or_404(_thread_scope(request.user, tenant), id=thread_id) if tenant else None
    if not thread:
        return render(request, "core/empty_state.html", {"title": "Pendência não encontrada"}, status=404)
    form = CommunicationMessageForm(request.POST or None)
    can_manage = _can_review(request.user, tenant)
    if request.method == "POST" and form.is_valid():
        CommunicationMessage.objects.create(thread=thread, author=request.user, body=form.cleaned_data["body"])
        if thread.assigned_to_id and thread.assigned_to_id != request.user.id:
            Notification.objects.create(tenant=tenant, recipient=thread.assigned_to, thread=thread, title="Nova mensagem em pendência", body=thread.title)
        _audit(tenant=tenant, user=request.user, action="update", entity="communication_thread", entity_id=thread.id, after={"message_added": True})
        messages.success(request, "Mensagem registrada.")
        return redirect("communication_detail", thread.id)
    timeline = list(AuditLog.objects.filter(tenant=tenant, entity_id=str(thread.id), entity__in=["communication_thread", "field_event"]))
    if thread.status != "closed":
        Notification.objects.filter(recipient=request.user, thread=thread, read_at__isnull=True).update(read_at=timezone.now())
    return render(request, "core/communication_detail.html", {"thread": thread, "form": form, "timeline": timeline, "can_manage": can_manage})


@login_required
def communication_action(request, thread_id, action):
    tenant = _tenant_for_user(request.user)
    if request.method != "POST" or not tenant or not _can_review(request.user, tenant):
        return render(request, "core/empty_state.html", {"title": "Ação não autorizada"}, status=403)
    thread = get_object_or_404(_thread_scope(request.user, tenant), id=thread_id)
    reason = request.POST.get("reason", "").strip()
    if len(reason) < 5:
        messages.error(request, "Informe uma justificativa com pelo menos 5 caracteres.")
        return redirect("communication_detail", thread.id)
    status_map = {"analysis": "analysis", "waiting": "waiting", "resolve": "resolved", "close": "closed"}
    if action in status_map:
        thread.status = status_map[action]
        thread.resolved_at = timezone.now() if thread.status in {"resolved", "closed"} else None
        thread.save(update_fields=["status", "resolved_at", "updated_at"])
        _audit(tenant=tenant, user=request.user, action="update", entity="communication_thread", entity_id=thread.id, after={"status": thread.status}, reason=reason)
        messages.success(request, "Status da pendência atualizado.")
    return redirect("communication_detail", thread.id)


@login_required
def notification_read(request, notification_id):
    notification = get_object_or_404(request.user.notifications, id=notification_id)
    notification.read_at = timezone.now()
    notification.save(update_fields=["read_at", "updated_at"])
    return redirect("communication_detail", notification.thread_id) if notification.thread_id else redirect("communications")
