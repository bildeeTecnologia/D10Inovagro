import calendar
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.db.models import Q

from .models import CompensationVersion, FieldEvent, MonthlyCompensationResult, MonthlyBaseConfiguration

CENT = Decimal("0.01")


def compensation_for(collaborator, unit, event_date):
    return CompensationVersion.objects.filter(collaborator=collaborator, unit=unit, effective_from__lte=event_date).filter(Q(effective_to__isnull=True) | Q(effective_to__gte=event_date)).order_by("-effective_from", "-created_at").first()


def monthly_base_days(company, event_date):
    configuration = MonthlyBaseConfiguration.objects.filter(
        company=company,
        effective_from__lte=event_date,
    ).filter(Q(effective_to__isnull=True) | Q(effective_to__gte=event_date)).order_by("-effective_from", "-created_at").first()
    if configuration and configuration.base_type == "calendar_days":
        return calendar.monthrange(event_date.year, event_date.month)[1], configuration
    return 30, configuration


def calculate_monthly_compensation(competency, collaborator, unit):
    events = FieldEvent.objects.filter(tenant=competency.tenant, competency=competency, collaborator=collaborator, unit=unit)
    rain_events = events.filter(event_type="rain_release", status="approved")
    rain_days = rain_events.values("event_date").distinct().count()
    compensation = compensation_for(collaborator, unit, competency.cutoff_date or competency.created_at.date())
    if not compensation:
        raise ValueError(f"Não existe salário combinado e CLT vigente para {collaborator.name}.")
    if compensation.combined_salary < 0 or compensation.clt_salary < 0:
        raise ValueError("Os salários não podem ser negativos.")
    base_date = date(competency.year, competency.month, 1)
    base_days_int, base_configuration = monthly_base_days(compensation.company, base_date)
    if rain_days > base_days_int:
        raise ValueError(f"A quantidade de dias afetados não pode ultrapassar a base de {base_days_int} dias.")
    base_days = Decimal(str(base_days_int))
    normal_days = base_days_int - rain_days
    combined_daily = compensation.combined_salary / base_days
    clt_daily = compensation.clt_salary / base_days
    normal_amount = combined_daily * normal_days
    rain_amount = clt_daily * rain_days
    total_amount = (normal_amount + rain_amount).quantize(CENT, rounding=ROUND_HALF_UP)
    memory = {
        "rule": "salario_combinado_nos_dias_normais_e_clt_nos_dias_de_dispensa_por_chuva",
        "base_days": str(base_days_int),
        "base_type": base_configuration.base_type if base_configuration else "fixed_30",
        "base_configuration_id": base_configuration.id if base_configuration else None,
        "combined_salary": str(compensation.combined_salary),
        "clt_salary": str(compensation.clt_salary),
        "normal_days": normal_days,
        "rain_days": rain_days,
        "combined_daily": str(combined_daily),
        "clt_daily": str(clt_daily),
        "rounding": "arredondar somente o total final",
        "payment_cycle": "monthly",
        "approved_rain_event_ids": list(rain_events.values_list("id", flat=True)),
    }
    with transaction.atomic():
        result, _ = MonthlyCompensationResult.objects.update_or_create(
            competency=competency,
            collaborator=collaborator,
            unit=unit,
            defaults={"tenant": competency.tenant, "compensation": compensation, "normal_days": normal_days, "rain_days": rain_days, "combined_daily": combined_daily, "clt_daily": clt_daily, "normal_amount": normal_amount.quantize(CENT, rounding=ROUND_HALF_UP), "rain_amount": rain_amount.quantize(CENT, rounding=ROUND_HALF_UP), "total_amount": total_amount, "payment_cycle": "monthly", "memory": memory},
        )
    return result
