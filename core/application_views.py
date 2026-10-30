from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from .application_forms import AgreementEndForm, AgreementForm, ApplicationForm
from .models import CollaboratorRubric, Competency, RubricApplication
from .rubric_applications import (
    application_unit_ids, approve_agreement, approve_application, end_agreement, end_application,
    generate_application_entries,
)
from .views import _allowed_units_for_user, _audit, _can_manage_rules, _tenant_for_user


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
