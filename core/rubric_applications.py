from calendar import monthrange
from datetime import date

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q

from .models import (
    AuditLog, CollaboratorRubric, Competency, EmploymentLink, FieldEvent,
    PaymentCycle, PaymentEntry, RubricApplication,
)


def period(competency):
    return (
        date(competency.year, competency.month, 1),
        date(competency.year, competency.month, monthrange(competency.year, competency.month)[1]),
    )


def overlaps(queryset, start, end):
    if end:
        queryset = queryset.filter(effective_from__lte=end)
    return queryset.filter(Q(effective_to__isnull=True) | Q(effective_to__gte=start))


def available_applications(tenant, units):
    return RubricApplication.objects.filter(
        tenant=tenant, unit__in=units, status="approved",
        rubric__active=True, mode="event", leader_available=True,
    ).select_related("rubric", "unit")


def validate_event_application(application, tenant, unit, collaborator, event_date, quantity):
    if (
        application.tenant_id != tenant.pk or application.unit_id != unit.pk
        or collaborator.tenant_id != tenant.pk
        or application.status != "approved" or application.mode != "event"
        or not application.leader_available or not application.rubric.active
    ):
        raise ValidationError("Regra indisponível para lançamento nesta unidade.")
    if event_date < application.effective_from or (application.effective_to and event_date > application.effective_to):
        raise ValidationError("A regra não está vigente na data do evento.")
    if not collaborator.active or not unit.active:
        raise ValidationError("Unidade ou colaborador inativo para lançamento.")
    if quantity != 1:
        raise ValidationError("Evento de valor fixo aceita somente uma ocorrência por lançamento.")
    if not EmploymentLink.objects.filter(
        collaborator=collaborator, company=unit.company, unit=unit,
        admission_date__lte=event_date,
    ).filter(Q(termination_date__isnull=True) | Q(termination_date__gte=event_date)).exists():
        raise ValidationError("Colaborador sem vínculo ativo com esta unidade na data do evento.")


def _approval_period_guard(tenant, start, end):
    for competency in Competency.objects.select_for_update().filter(tenant=tenant):
        first, last = period(competency)
        if last < start or (end and first > end):
            continue
        if competency.status == "closed" or competency.payment_cycles.filter(status__in=["approved", "closed"]).exists():
            raise ValidationError("A vigência alcança competência fechada ou ciclo aprovado. Ajuste a vigência ou reabra pelo fluxo autorizado.")


@transaction.atomic
def approve_application(application, user, reason):
    application = RubricApplication.objects.select_for_update().get(pk=application.pk)
    # Serialize approvals for the same rubric, including concurrent new versions.
    type(application.rubric).objects.select_for_update().get(pk=application.rubric_id)
    if application.status != "draft":
        raise ValidationError("Somente regras em rascunho podem ser aprovadas.")
    application.full_clean()
    if not application.rubric.active or not application.unit.active:
        raise ValidationError("Ative a rubrica e a unidade antes de aprovar a aplicação.")
    other = RubricApplication.objects.filter(
        tenant=application.tenant, rubric__code__iexact=application.rubric.code, unit=application.unit, status="approved",
    ).exclude(pk=application.pk)
    if overlaps(other, application.effective_from, application.effective_to).exists():
        raise ValidationError("Já existe regra aprovada desta rubrica/unidade no período.")
    _approval_period_guard(application.tenant, application.effective_from, application.effective_to)
    application.status = "approved"
    application.approved_by = user
    application.save(update_fields=["status", "approved_by", "updated_at"])
    AuditLog.objects.create(
        tenant=application.tenant, user=user, action="approve",
        entity="rubric_application", entity_id=str(application.pk),
        before={"status": "draft"}, after={"status": "approved"}, reason=reason,
    )


@transaction.atomic
def approve_agreement(agreement, user, reason):
    agreement = CollaboratorRubric.objects.select_for_update().get(pk=agreement.pk)
    application = RubricApplication.objects.select_for_update().get(pk=agreement.application_id)
    if agreement.status != "draft":
        raise ValidationError("Somente vínculos em rascunho podem ser aprovados.")
    agreement.full_clean()
    other = CollaboratorRubric.objects.filter(
        tenant=agreement.tenant, collaborator=agreement.collaborator,
        application__rubric__code__iexact=application.rubric.code, status="approved",
    ).exclude(pk=agreement.pk)
    if overlaps(other, agreement.effective_from, agreement.effective_to).exists():
        raise ValidationError("O colaborador já possui esta rubrica no período, inclusive em outra unidade.")
    if not EmploymentLink.objects.filter(
        collaborator=agreement.collaborator, company=application.unit.company,
        unit=application.unit, admission_date__lte=agreement.effective_from,
    ).filter(Q(termination_date__isnull=True) | Q(termination_date__gte=agreement.effective_from)).exists():
        raise ValidationError("Não há vínculo de emprego vigente na data inicial.")
    _approval_period_guard(agreement.tenant, agreement.effective_from, agreement.effective_to)
    agreement.status = "approved"
    agreement.approved_by = user
    agreement.save(update_fields=["status", "approved_by", "updated_at"])
    AuditLog.objects.create(
        tenant=agreement.tenant, user=user, action="approve",
        entity="collaborator_rubric", entity_id=str(agreement.pk),
        before={"status": "draft"}, after={"status": "approved"}, reason=reason,
    )


@transaction.atomic
def end_agreement(agreement, end, user, reason):
    agreement = CollaboratorRubric.objects.select_for_update().get(pk=agreement.pk)
    if agreement.status != "approved" or agreement.effective_to:
        raise ValidationError("Somente vínculo aprovado sem data final pode ser encerrado.")
    _approval_period_guard(agreement.tenant, end, None)
    for entry in agreement.payment_entries.select_related("cycle__competency"):
        if period(entry.cycle.competency)[1] > end:
            raise ValidationError("O encerramento afetaria lançamento já gerado. Revise a competência antes de encerrar.")
    agreement.effective_to = end
    agreement.full_clean()
    agreement.save(update_fields=["effective_to", "updated_at"])
    AuditLog.objects.create(
        tenant=agreement.tenant, user=user, action="update",
        entity="collaborator_rubric", entity_id=str(agreement.pk),
        before={"effective_to": None}, after={"effective_to": end.isoformat()}, reason=reason,
    )


@transaction.atomic
def end_application(application, end, user, reason):
    application = RubricApplication.objects.select_for_update().get(pk=application.pk)
    if application.status != "approved" or application.effective_to:
        raise ValidationError("Somente regra aprovada sem data final pode ser encerrada.")
    if application.agreements.filter(Q(effective_to__isnull=True) | Q(effective_to__gt=end)).exists():
        raise ValidationError("Defina primeiro o fim dos vínculos de colaboradores dentro deste período.")
    if application.events.filter(event_date__gt=end).exists():
        raise ValidationError("Há eventos posteriores ao encerramento solicitado.")
    _approval_period_guard(application.tenant, end, None)
    application.effective_to = end
    application.full_clean()
    application.save(update_fields=["effective_to", "updated_at"])
    AuditLog.objects.create(
        tenant=application.tenant, user=user, action="update",
        entity="rubric_application", entity_id=str(application.pk),
        before={"effective_to": None}, after={"effective_to": end.isoformat()}, reason=reason,
    )


def application_sources(competency):
    first, last = period(competency)
    agreements = overlaps(CollaboratorRubric.objects.filter(
        tenant=competency.tenant, status="approved", application__mode="recurring",
    ).select_related("application__rubric", "application__unit", "collaborator"), first, last)
    events = competency.events.filter(event_type="rubric", status="approved").select_related(
        "application__rubric", "application__unit", "collaborator", "unit",
    )
    sources, errors = [], []
    for agreement in agreements:
        app = agreement.application
        if (
            agreement.effective_from > first or (agreement.effective_to and agreement.effective_to < last)
            or app.effective_from > first or (app.effective_to and app.effective_to < last)
            or not EmploymentLink.objects.filter(
                collaborator=agreement.collaborator, unit=app.unit, company=app.unit.company,
                admission_date__lte=first,
            ).filter(Q(termination_date__isnull=True) | Q(termination_date__gte=last)).exists()
        ):
            errors.append(f"Vínculo #{agreement.pk}: mês parcial exige definição de proporcionalidade pelo DP; geração bloqueada.")
            continue
        if not app.rubric.active or app.status != "approved":
            errors.append(f"Vínculo #{agreement.pk}: rubrica/regra inativa ou não aprovada.")
            continue
        sources.append((app, agreement.collaborator, agreement, None))
    for event in events:
        try:
            if (event.event_date.year, event.event_date.month) != (competency.year, competency.month):
                raise ValidationError("A data do evento não pertence à competência de trabalho.")
            validate_event_application(event.application, competency.tenant, event.unit, event.collaborator, event.event_date, event.quantity)
        except ValidationError as exc:
            errors.append(f"Evento #{event.pk}: {' '.join(exc.messages)}")
        else:
            sources.append((event.application, event.collaborator, None, event))
    return sources, errors


def application_unit_ids(competency):
    first, last = period(competency)
    units = set(overlaps(
        competency.tenant.collaborator_rubrics.filter(status="approved", application__mode="recurring"), first, last,
    ).values_list("application__unit_id", flat=True))
    units.update(competency.events.filter(event_type="rubric").values_list("unit_id", flat=True))
    return units


def application_blockers(competency):
    sources, errors = application_sources(competency)
    for app, collaborator, agreement, event in sources:
        entry = PaymentEntry.objects.filter(
            tenant=competency.tenant, cycle__competency=competency,
            cycle__cycle_type=app.cycle_type, rubric=app.rubric,
            collaborator=collaborator, unit=app.unit, source_agreement=agreement,
            source_event=event, amount=app.amount,
        ).first()
        if not entry:
            errors.append(f"Rubrica {app.rubric.code}: geração pendente na competência.")
        elif app.cycle_type == "day10":
            _, last = period(competency)
            expected_date = date(last.year + (last.month == 12), 1 if last.month == 12 else last.month + 1, 10)
            if entry.cycle.payment_date != expected_date:
                errors.append(f"Rubrica {app.rubric.code}: data do ciclo deve ser dia 10 do mês seguinte à competência.")
    return errors


@transaction.atomic
def generate_application_entries(competency, user):
    competency = Competency.objects.select_for_update().get(pk=competency.pk)
    if competency.status == "closed":
        raise ValueError("Competência fechada não pode gerar rubricas.")
    sources, errors = application_sources(competency)
    if errors:
        raise ValueError(" ".join(errors))
    entries = []
    for app, collaborator, agreement, event in sources:
        first, last = period(competency)
        next_month = date(last.year + (last.month == 12), 1 if last.month == 12 else last.month + 1, 10)
        cycle, _ = PaymentCycle.objects.get_or_create(
            tenant=competency.tenant, competency=competency, cycle_type=app.cycle_type,
            defaults={"created_by": user, "payment_date": next_month if app.cycle_type == "day10" else None},
        )
        cycle = PaymentCycle.objects.select_for_update().get(pk=cycle.pk)
        if cycle.status in {"approved", "closed"}:
            raise ValueError("Ciclo aprovado/fechado impede geração de rubricas.")
        if app.cycle_type == "day10" and cycle.payment_date and cycle.payment_date != next_month:
            raise ValueError("O ciclo dia 10 possui data incompatível com o mês seguinte à competência. Revise o ciclo antes de gerar.")
        if app.cycle_type == "day10" and cycle.payment_date is None:
            cycle.payment_date = next_month
            cycle.save(update_fields=["payment_date", "updated_at"])
        entry, _ = PaymentEntry.objects.update_or_create(
            cycle=cycle, source_event=event, source_agreement=agreement,
            collaborator=collaborator, unit=app.unit, rubric=app.rubric,
            defaults={
                "tenant": competency.tenant, "amount": app.amount, "created_by": user, "status": "draft",
                "memory": {
                    "source": "rubric_application", "application_id": app.pk,
                    "agreement_id": agreement.pk if agreement else None,
                    "event_id": event.pk if event else None,
                    "mode": app.mode, "fixed_amount": str(app.amount),
                    "competency": f"{competency.month:02d}/{competency.year}",
                    "payment_cycle": app.cycle_type, "proration": "not_supported",
                    "rubric_code": app.rubric.code, "rubric_name": app.rubric.name,
                    "instructions": app.instructions,
                    "effective_from": (agreement.effective_from if agreement else app.effective_from).isoformat(),
                    "effective_to": str(agreement.effective_to if agreement else app.effective_to),
                },
            },
        )
        entries.append(entry)
    AuditLog.objects.create(
        tenant=competency.tenant, user=user, action="create", entity="rubric_generation",
        entity_id=str(competency.pk), after={"entry_ids": [entry.pk for entry in entries]},
        reason="Geração idempotente de regras aprovadas e origens identificadas.",
    )
    if entries and competency.status == "open":
        competency.status = "review"
        competency.save(update_fields=["status", "updated_at"])
    return entries
