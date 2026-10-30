from datetime import date
from decimal import Decimal

from django.db import transaction

from .models import CalculationResult, PaymentCycle, PaymentEntry, Rubric


DEFAULT_RUBRIC_DEFINITIONS = [
    ("SAL_COMBINADO_NORMAL", "Salário combinado — dias normais", "earning", "monthly"),
    ("SAL_CLT_CHUVA", "Salário CLT — dias de dispensa por chuva", "earning", "monthly"),
    ("ADICIONAL_12H", "Adicional 12h", "earning", "day10"),
    ("BONIFICACAO_DIA10", "Bonificação — pagamento do dia 10", "earning", "day10"),
    ("PENSAO", "Pensão", "deduction", "monthly"),
    ("DESCONTO", "Desconto", "deduction", "monthly"),
]


def ensure_default_rubrics(tenant, user):
    result = {}
    for code, name, category, cycle_type in DEFAULT_RUBRIC_DEFINITIONS:
        rubric, _ = Rubric.objects.get_or_create(tenant=tenant, code=code, version=1, defaults={"name": name, "category": category, "cycle_type": cycle_type, "effective_from": date.today(), "created_by": user})
        result[code] = rubric
    return result


def generate_monthly_entries(result, user):
    with transaction.atomic():
        cycle, _ = PaymentCycle.objects.get_or_create(tenant=result.tenant, competency=result.competency, cycle_type="monthly", defaults={"payment_date": None, "cutoff_date": result.competency.cutoff_date, "created_by": user})
        if cycle.status in {"approved", "closed"}:
            raise ValueError("O ciclo mensal já foi aprovado e não pode ser recalculado.")
        rubrics = ensure_default_rubrics(result.tenant, user)
        common = {"tenant": result.tenant, "cycle": cycle, "collaborator": result.collaborator, "unit": result.unit, "created_by": user, "status": "draft"}
        normal, _ = PaymentEntry.objects.update_or_create(cycle=cycle, collaborator=result.collaborator, unit=result.unit, rubric=rubrics["SAL_COMBINADO_NORMAL"], source_event=None, defaults={**common, "amount": result.normal_amount, "memory": {"source": "monthly_compensation_result", "result_id": result.id, "days": result.normal_days, "salary_basis": "combined"}})
        rain = None
        if result.rain_amount > Decimal("0"):
            rain, _ = PaymentEntry.objects.update_or_create(cycle=cycle, collaborator=result.collaborator, unit=result.unit, rubric=rubrics["SAL_CLT_CHUVA"], source_event=None, defaults={**common, "amount": result.rain_amount, "memory": {"source": "monthly_compensation_result", "result_id": result.id, "days": result.rain_days, "salary_basis": "clt"}})
        return cycle, [normal] + ([rain] if rain else [])


def generate_day10_entries(competency, user):
    events = competency.events.filter(event_type="additional_12h", status="approved").select_related("unit", "collaborator")
    if not events.exists():
        return None, []
    cycle, _ = PaymentCycle.objects.get_or_create(tenant=competency.tenant, competency=competency, cycle_type="day10", defaults={"created_by": user})
    if cycle.status in {"approved", "closed"}:
        raise ValueError("O ciclo do dia 10 já foi aprovado e não pode ser recalculado.")
    rubrics = ensure_default_rubrics(competency.tenant, user)
    entries = []
    for event in events:
        result = CalculationResult.objects.filter(event=event).first()
        if not result:
            raise ValueError("Adicional 12h aprovado ainda não foi calculado.")
        entry, _ = PaymentEntry.objects.update_or_create(cycle=cycle, collaborator=event.collaborator, unit=event.unit, rubric=rubrics["ADICIONAL_12H"], source_event=event, defaults={"tenant": competency.tenant, "unit": event.unit, "amount": result.calculated_amount, "status": "draft", "memory": {"source": "calculation_result", "event_id": event.id, "rule_version": result.rule.version, "payment_cycle": "day10"}, "created_by": user})
        entries.append(entry)
    return cycle, entries
