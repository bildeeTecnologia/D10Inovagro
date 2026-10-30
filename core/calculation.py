from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction

from .models import CalculationResult, CalculationRule, FieldEvent

CENT = Decimal("0.01")


def _decimal(value, default):
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal(default)


def published_rule_for(event):
    candidates = CalculationRule.objects.filter(
        tenant=event.tenant,
        event_type=event.event_type,
        status="published",
        effective_from__lte=event.event_date,
    ).filter(
        models_q_end_date(event.event_date)
    ).select_related("company", "unit").order_by("-version")
    candidates = list(candidates)
    scoped = [rule for rule in candidates if rule.unit_id == event.unit_id]
    scoped += [rule for rule in candidates if rule.unit_id is None and rule.company_id == event.unit.company_id]
    scoped += [rule for rule in candidates if rule.unit_id is None and rule.company_id is None]
    return scoped[0] if scoped else None


def models_q_end_date(event_date):
    from django.db.models import Q
    return Q(effective_to__isnull=True) | Q(effective_to__gte=event_date)


def calculate_event(event):
    if event.status not in {"pending", "approved"}:
        raise ValueError("Somente eventos pendentes ou aprovados podem ser calculados.")
    rule = published_rule_for(event)
    if not rule:
        raise ValueError(f"Nenhuma regra publicada para {event.get_event_type_display()} em {event.event_date:%d/%m/%Y}.")
    link = event.collaborator.links.filter(unit=event.unit, admission_date__lte=event.event_date).order_by("-admission_date").first()
    if not link or link.termination_date and link.termination_date < event.event_date or (link.monthly_salary is None and event.event_type != "additional_12h"):
        raise ValueError("Colaborador sem vínculo ou remuneração mensal configurada para a data do evento.")
    params = rule.parameters or {}
    if event.event_type == "additional_12h":
        amount = _decimal(params.get("amount"), "50.00").quantize(CENT, rounding=ROUND_HALF_UP)
        if amount < 0:
            raise ValueError("O valor do Adicional 12h não pode ser negativo.")
        memory = {"rule_code": rule.code, "rule_version": rule.version, "event_type": event.event_type, "fixed_amount": str(amount), "quantity": "1", "formula": "fixed_amount_per_occurrence", "payment_cycle": "day10"}
        with transaction.atomic():
            result, _ = CalculationResult.objects.update_or_create(event=event, defaults={"tenant": event.tenant, "competency": event.competency, "collaborator": event.collaborator, "rule": rule, "base_amount": amount, "factor": Decimal("1"), "calculated_amount": amount, "memory": memory})
        return result
    base_days = _decimal(params.get("base_days"), "30")
    if base_days <= 0:
        raise ValueError("base_days precisa ser maior que zero.")
    if event.event_type == "daily":
        base = link.monthly_salary / base_days
        factor = _decimal(params.get("factor"), "1")
    elif event.event_type == "overtime":
        base_hours = _decimal(params.get("base_hours"), "220")
        if base_hours <= 0:
            raise ValueError("base_hours precisa ser maior que zero.")
        base = link.monthly_salary / base_hours
        factor = _decimal(params.get("factor"), "1.5")
    else:
        raise ValueError("Esta primeira versão calcula apenas diária e hora extra.")
    amount = (base * factor * event.quantity).quantize(CENT, rounding=ROUND_HALF_UP)
    memory = {
        "rule_code": rule.code,
        "rule_version": rule.version,
        "event_type": event.event_type,
        "monthly_salary": str(link.monthly_salary),
        "quantity": str(event.quantity),
        "base_days": str(base_days),
        "base_amount": str(base.quantize(CENT, rounding=ROUND_HALF_UP)),
        "factor": str(factor),
        "formula": "monthly_salary / base_days * quantity * factor" if event.event_type == "daily" else "monthly_salary / base_hours * quantity * factor",
    }
    with transaction.atomic():
        result, _ = CalculationResult.objects.update_or_create(
            event=event,
            defaults={
                "tenant": event.tenant,
                "competency": event.competency,
                "collaborator": event.collaborator,
                "rule": rule,
                "base_amount": base.quantize(CENT, rounding=ROUND_HALF_UP),
                "factor": factor,
                "calculated_amount": amount,
                "memory": memory,
            },
        )
    return result
