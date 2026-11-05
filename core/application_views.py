from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from .application_forms import AgreementEndForm, AgreementForm, ApplicationForm
from .bonus_forms import BonusForm
from .event_releases import fixed_event_types
from .models import CollaboratorRubric, Competency, EventTypeSetting, RubricApplication
from .rubric_applications import (
    application_unit_ids, approve_agreement, approve_application, end_agreement, end_application,
    generate_application_entries,
)
from .views import _allowed_units_for_user, _audit, _can_manage_rules, _rubric_snapshot, _tenant_for_user, rule_list_context


@login_required
@require_http_methods(["GET", "POST"])
def application_edit(request, kind, object_id=None):
    tenant = _tenant_for_user(request.user)
    if not tenant or not _can_manage_rules(request.user, tenant):
        return render(request, "core/empty_state.html", {"title": "Acesso restrito ao DP"}, status=403)
    units = _allowed_units_for_user(request.user, tenant)
    is_agreement = kind == "agreement"
    model = CollaboratorRubric if is_agreement else RubricApplication
    queryset = model.objects.filter(tenant=tenant)
    queryset = queryset.filter(application__unit__in=units) if is_agreement else queryset.filter(unit__in=units)
    with transaction.atomic():
        obj = get_object_or_404(queryset.select_for_update(), pk=object_id) if object_id else model(tenant=tenant)
        if obj.pk and obj.status != "draft":
            messages.error(request, "Cadastro aprovado é imutável. Encerre o vínculo ou crie nova regra sem sobrepor vigências.")
            return redirect("rule_list")
        form_class = AgreementForm if is_agreement else ApplicationForm
        before = {
            key: str(getattr(obj, key)) for key in form_class.Meta.fields
        } if obj.pk else {}
        form = form_class(
            request.POST if request.method == "POST" else None,
            instance=obj, tenant=tenant, units=units,
        )
        if request.method == "POST" and form.is_valid():
            saved = form.save(commit=False)
            if not saved.pk:
                saved.created_by = request.user
            saved.save()
            _audit(
                tenant=tenant, user=request.user, entity="collaborator_rubric" if is_agreement else "rubric_application",
                entity_id=saved.pk, action="update" if before else "create", before=before,
                after={key: str(getattr(saved, key)) for key in form_class.Meta.fields},
                reason=form.cleaned_data["reason"],
            )
            messages.success(request, "Rascunho salvo. A aplicação só entra em vigor após aprovação.")
            return redirect("rule_list")
    return render(request, "core/application_form.html", {
        "tenant": tenant, "form": form,
        "title": "Vínculo de rubrica ao colaborador" if is_agreement else "Regra de aplicação",
    })


@login_required
@require_POST
def application_approve(request, kind, object_id):
    tenant = _tenant_for_user(request.user)
    if not tenant or not _can_manage_rules(request.user, tenant):
        return render(request, "core/empty_state.html", {"title": "Acesso restrito ao DP"}, status=403)
    units = _allowed_units_for_user(request.user, tenant)
    is_agreement = kind == "agreement"
    queryset = (
        CollaboratorRubric.objects.filter(tenant=tenant, application__unit__in=units)
        if is_agreement else RubricApplication.objects.filter(tenant=tenant, unit__in=units)
    )
    obj = get_object_or_404(queryset, pk=object_id)
    reason = request.POST.get("reason", "").strip()
    if len(reason) < 5:
        messages.error(request, "Informe justificativa de aprovação com pelo menos 5 caracteres.")
        return redirect("rule_list")
    try:
        (approve_agreement if is_agreement else approve_application)(obj, request.user, reason)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, "Aprovação registrada. Use Gerar rubricas para aplicar na competência.")
    return redirect("rule_list")


@login_required
@require_http_methods(["GET", "POST"])
def agreement_end(request, object_id, kind="agreement"):
    tenant = _tenant_for_user(request.user)
    if not tenant or not _can_manage_rules(request.user, tenant):
        return render(request, "core/empty_state.html", {"title": "Acesso restrito ao DP"}, status=403)
    units = _allowed_units_for_user(request.user, tenant)
    queryset = (
        CollaboratorRubric.objects.filter(tenant=tenant, application__unit__in=units)
        if kind == "agreement" else RubricApplication.objects.filter(tenant=tenant, unit__in=units)
    )
    obj = get_object_or_404(queryset, pk=object_id)
    form = AgreementEndForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            (end_agreement if kind == "agreement" else end_application)(
                obj, form.cleaned_data["effective_to"], request.user, form.cleaned_data["reason"],
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "Data final registrada sem apagar o histórico.")
            return redirect("rule_list")
    return render(request, "core/application_form.html", {"tenant": tenant, "title": f"Definir encerramento: {obj}", "form": form})


@login_required
@require_POST
def application_generate(request):
    tenant = _tenant_for_user(request.user)
    if not tenant or not _can_manage_rules(request.user, tenant):
        return render(request, "core/empty_state.html", {"title": "Acesso restrito ao DP"}, status=403)
    competency = get_object_or_404(Competency, tenant=tenant, pk=request.POST.get("competency"))
    allowed = set(_allowed_units_for_user(request.user, tenant).values_list("pk", flat=True))
    required = application_unit_ids(competency)
    if not required.issubset(allowed):
        return render(request, "core/empty_state.html", {"title": "A geração exige acesso às unidades dos vínculos e eventos"}, status=403)
    try:
        entries = generate_application_entries(competency, request.user)
    except ValueError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"{len(entries)} lançamento(s) de rubricas gerado(s)/atualizado(s), sem duplicar origens.")
    return redirect("rule_list")


@login_required
def bonus_create(request):
    tenant = _tenant_for_user(request.user)
    if request.method != "POST" or not tenant or not _can_manage_rules(request.user, tenant):
        return render(request, "core/empty_state.html", {"title": "Acesso restrito ao DP"}, status=403)
    units = _allowed_units_for_user(request.user, tenant)
    form = BonusForm(request.POST, tenant=tenant, units=units)
    if form.is_valid():
        try:
            rubric, applications = form.save(request.user, _rubric_snapshot)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            tail = (
                " e aprovada. Use Gerar rubricas para aplicá-la na competência."
                if form.cleaned_data["approve_now"] else " como rascunho; aprove para valer."
            )
            messages.success(request, f"Bonificação {rubric.name} criada para {len(applications)} unidade(s){tail}")
            return redirect("rule_list")
    return render(request, "core/rule_list.html", rule_list_context(request, tenant, bonus_form=form), status=400)


@login_required
@require_POST
def event_type_release(request, event_type):
    tenant = _tenant_for_user(request.user)
    if not tenant or not _can_manage_rules(request.user, tenant):
        return render(request, "core/empty_state.html", {"title": "Acesso restrito ao DP"}, status=403)
    if event_type not in dict(fixed_event_types()):
        return render(request, "core/empty_state.html", {"title": "Tipo de evento inválido"}, status=400)
    release = request.POST.get("leader_available") == "1"
    setting, _ = EventTypeSetting.objects.get_or_create(tenant=tenant, event_type=event_type)
    before = {"leader_available": setting.leader_available}
    setting.leader_available = release
    setting.updated_by = request.user
    setting.save(update_fields=["leader_available", "updated_by", "updated_at"])
    _audit(
        tenant=tenant, user=request.user, action="update", entity="event_type_setting", entity_id=setting.pk,
        before=before, after={"event_type": event_type, "leader_available": release},
        reason="Liberação do tipo de evento para líderes alterada na tela de Regras.",
    )
    verb = "liberado para os líderes" if release else "removido do app dos líderes"
    messages.success(request, f"{setting.get_event_type_display()} {verb}.")
    return redirect("rule_list")


@login_required
@require_POST
def application_leader_release(request, object_id):
    tenant = _tenant_for_user(request.user)
    if not tenant or not _can_manage_rules(request.user, tenant):
        return render(request, "core/empty_state.html", {"title": "Acesso restrito ao DP"}, status=403)
    units = _allowed_units_for_user(request.user, tenant)
    with transaction.atomic():
        application = get_object_or_404(
            RubricApplication.objects.select_for_update().filter(tenant=tenant, unit__in=units, mode__in=["event", "cumulative"]),
            pk=object_id,
        )
        release = request.POST.get("leader_available") == "1"
        before = {"leader_available": application.leader_available}
        application.leader_available = release
        try:
            application.full_clean()
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
            return redirect("rule_list")
        application.save(update_fields=["leader_available", "updated_at"])
        _audit(
            tenant=tenant, user=request.user, action="update", entity="rubric_application", entity_id=application.pk,
            before=before, after={"leader_available": release},
            reason="Liberação para líderes alterada na tela de Regras; valores e vigência não são afetados.",
        )
    verb = "liberada para os líderes" if release else "removida do app dos líderes"
    messages.success(request, f"{application.rubric.name} ({application.unit.name}) {verb}.")
    return redirect("rule_list")
