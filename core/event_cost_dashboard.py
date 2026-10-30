from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Count, Sum

from .models import Company, FieldEvent
from .reporting import build_report_data, money

ZERO = Decimal("0.00")


def _safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _status_filtered(queryset, status, event_prefix="event__"):
    valid_statuses = dict(FieldEvent.STATUS_CHOICES)
    if status == "all":
        return queryset
    if status not in valid_statuses:
        return queryset.none()
    return queryset.filter(**{f"{event_prefix}status": status})


def _bar_chart_data(items):
    maximum = max((item["total"] for item in items), default=ZERO)
    output = []
    for item in sorted(items, key=lambda value: (-value["total"], value["label"].casefold())):
        width = (item["total"] * Decimal("100") / maximum).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP) if maximum > ZERO else Decimal("0.0")
        output.append({**item, "width": str(width), "formatted_total": money(item["total"])})
    return output


def _comparison(rows, competencies):
    headers = [{"label": f"{item.month:02d}/{item.year}"} for item in competencies]
    labels = [item["label"] for item in headers]
    groups = {}
    totals = {label: ZERO for label in labels}
    for row in rows:
        key = (row["unidade"], row["evento"], row["status"])
        values = groups.setdefault(key, {})
        values[row["competencia"]] = values.get(row["competencia"], ZERO) + row["total"]
        totals[row["competencia"]] = totals.get(row["competencia"], ZERO) + row["total"]

    result = []
    for (unit_name, event_name, status), values in sorted(groups.items()):
        cells = [values.get(label) for label in labels]
        result.append({
            "unidade": unit_name,
            "evento": event_name,
            "status": status,
            "cells": cells,
            "period_total": sum((value for value in cells if value is not None), ZERO),
        })
    return headers, result, [totals[label] for label in labels]


def _trend_data(grouped_rows, competencies):
    amount_by_period = defaultdict(lambda: ZERO)
    count_by_period = defaultdict(int)
    for row in grouped_rows:
        key = (row["competency__year"], row["competency__month"])
        amount_by_period[key] += row["total"] or ZERO
        count_by_period[key] += row["event_count"] or 0

    chronological = list(reversed(competencies))
    raw_points = []
    for competency in chronological:
        key = (competency.year, competency.month)
        has_data = count_by_period[key] > 0
        value = amount_by_period[key] if has_data else None
        raw_points.append({
            "label": f"{competency.month:02d}/{str(competency.year)[-2:]}",
            "full_label": f"{competency.month:02d}/{competency.year}",
            "total": value,
            "amount_label": money(value) if value is not None else "Sem cálculo registrado",
            "has_data": has_data,
        })

    values = [item["total"] for item in raw_points if item["has_data"]]
    maximum = max(values, default=ZERO)
    scale = maximum if maximum > ZERO else Decimal("1.00")
    left, right, top, bottom = 72.0, 980.0, 24.0, 218.0
    count = len(raw_points)
    segments, current_segment = [], []
    points = []
    for index, item in enumerate(raw_points):
        x = left + ((right - left) * index / max(count - 1, 1))
        y = bottom - (float(item["total"] / scale) * (bottom - top)) if item["has_data"] else None
        point = {**item, "x": round(x, 1), "y": round(y, 1) if y is not None else None}
        points.append(point)
        if point["has_data"]:
            current_segment.append(f"{point['x']},{point['y']}")
        else:
            if len(current_segment) > 1:
                segments.append(" ".join(current_segment))
            current_segment = []
    if len(current_segment) > 1:
        segments.append(" ".join(current_segment))

    axis = []
    for ratio in (Decimal("1.00"), Decimal("0.50"), Decimal("0.00")):
        axis.append({
            "y": round(bottom - float(ratio) * (bottom - top), 1),
            "label": money(maximum * ratio),
        })
    return points, segments, axis, any(item["has_data"] for item in points)


def _variation(tenant, units, selected, current_total, status):
    if not selected:
        return {"display": "—", "detail": "Nenhuma competência disponível", "direction": "neutral"}

    previous_month = selected.month - 1 if selected.month > 1 else 12
    previous_year = selected.year if selected.month > 1 else selected.year - 1
    previous = tenant.competencies.filter(year=previous_year, month=previous_month).first()
    if not previous:
        return {"display": "—", "detail": "Competência anterior não cadastrada", "direction": "neutral"}

    previous_query = tenant.calculation_results.filter(event__unit__in=units, competency=previous)
    previous_query = _status_filtered(previous_query, status)
    previous_count = previous_query.count()
    previous_total = previous_query.aggregate(total=Sum("calculated_amount"))["total"]
    if not previous_count or previous_total is None:
        return {"display": "Sem base", "detail": f"Sem cálculos em {previous.month:02d}/{previous.year}", "direction": "neutral"}
    if previous_total == ZERO:
        if current_total == ZERO:
            return {"display": "0,0%", "detail": f"Sem variação sobre {previous.month:02d}/{previous.year}", "direction": "neutral"}
        return {"display": "Novo custo", "detail": f"A base de {previous.month:02d}/{previous.year} era R$ 0,00", "direction": "up"}

    percentage = ((current_total - previous_total) * Decimal("100") / previous_total).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    rendered = f"{percentage:+.1f}%".replace(".", ",")
    direction = "up" if percentage > 0 else ("down" if percentage < 0 else "neutral")
    return {"display": rendered, "detail": f"Comparado a {previous.month:02d}/{previous.year}", "direction": direction}


def build_event_cost_dashboard(tenant, authorized_units, filters):
    filters = dict(filters)
    status = filters.get("status") or "approved"
    if status not in {*dict(FieldEvent.STATUS_CHOICES), "all"}:
        status = "approved"
    filters["status"] = status

    competencies = list(tenant.competencies.order_by("-year", "-month")) if tenant else []
    companies = list(Company.objects.filter(tenant=tenant, units__in=authorized_units).distinct().order_by("legal_name")) if tenant else []
    company_ids = {item.id for item in companies}
    selected_company_id = _safe_int(filters.get("company"))
    if selected_company_id in company_ids:
        company_units = authorized_units.filter(company_id=selected_company_id)
        filters["company"] = str(selected_company_id)
    elif filters.get("company"):
        company_units = authorized_units.none()
    else:
        company_units = authorized_units
        filters["company"] = ""
    units_for_filter = list(company_units.select_related("company").order_by("name", "company__legal_name"))

    selected_unit_id = _safe_int(filters.get("unit"))
    available_unit_ids = {item.id for item in units_for_filter}
    if filters.get("unit"):
        if selected_unit_id in available_unit_ids:
            scoped_units = company_units.filter(pk=selected_unit_id)
            filters["unit"] = str(selected_unit_id)
        else:
            scoped_units = company_units.none()
    else:
        scoped_units = company_units
        filters["unit"] = ""

    selected_id = _safe_int(filters.get("competency"))
    selected = next((item for item in competencies if item.id == selected_id), None)
    if not selected and competencies:
        selected = competencies[0]
    filters["competency"] = str(selected.id) if selected else ""

    empty = {
        "rows": [], "summary_rows": [], "comparison_headers": [], "comparison_rows": [], "comparison_totals": [],
        "comparison_period_total": ZERO,
        "selected_competency": selected, "competencies": competencies, "companies": companies,
        "units_for_filter": units_for_filter, "filters": filters, "has_more_competencies": False,
        "event_cost_total": ZERO, "event_cost_count": 0, "event_cost_unit_count": 0,
        "event_cost_collaborator_count": 0, "uncalculated_event_count": 0,
        "unit_chart": [], "event_chart": [], "trend_points": [], "trend_segments": [], "trend_axis": [], "trend_has_data": False,
        "variation": {"display": "—", "detail": "Sem dados para comparar", "direction": "neutral"},
        "top_unit": None, "top_event": None,
    }
    if not tenant or not selected:
        return empty

    selected_period = (selected.year, selected.month)
    eligible_competencies = [item for item in competencies if (item.year, item.month) <= selected_period]
    comparison_competencies = eligible_competencies[:12]
    has_more_competencies = len(eligible_competencies) > 12
    competency_ids = [item.id for item in comparison_competencies]
    results = tenant.calculation_results.filter(event__unit__in=scoped_units, competency_id__in=competency_ids)
    results = _status_filtered(results, status)
    grouped_rows = list(results.values(
        "competency__year", "competency__month",
        "event__unit__id", "event__unit__name", "event__unit__company__legal_name", "event__unit__company__cnpj",
        "event__event_type", "event__application__rubric__name", "event__status",
    ).annotate(event_count=Count("id"), total=Sum("calculated_amount")).order_by(
        "-competency__year", "-competency__month", "event__unit__name", "event__unit__company__legal_name",
        "event__event_type", "event__application__rubric__name", "event__status",
    ))
    rows, _ = build_report_data(grouped_rows, "event_costs")
    period_label = f"{selected.month:02d}/{selected.year}"
    summary_rows = [row for row in rows if row["competencia"] == period_label]
    total = sum((row["total"] for row in summary_rows), ZERO)
    event_count = sum((row["quantidade"] for row in summary_rows), 0)
    unit_count = len({row["unidade"] for row in summary_rows})
    collaborator_count = results.filter(competency=selected).values("collaborator_id").distinct().count()

    event_query = tenant.events.filter(unit__in=scoped_units, competency=selected)
    if status != "all":
        event_query = event_query.filter(status=status)
    uncalculated_count = event_query.filter(calculation_result__isnull=True).count()

    unit_totals, event_totals = {}, {}
    for row in summary_rows:
        unit_bucket = unit_totals.setdefault(row["unidade"], {"label": row["unidade"], "total": ZERO, "events": 0})
        unit_bucket["total"] += row["total"]
        unit_bucket["events"] += row["quantidade"]
        event_bucket = event_totals.setdefault(row["evento"], {"label": row["evento"], "total": ZERO, "events": 0})
        event_bucket["total"] += row["total"]
        event_bucket["events"] += row["quantidade"]
    unit_chart = _bar_chart_data(list(unit_totals.values()))
    event_chart = _bar_chart_data(list(event_totals.values()))

    trend_points, trend_segments, trend_axis, trend_has_data = _trend_data(grouped_rows, comparison_competencies)
    variation = _variation(tenant, scoped_units, selected, total, status)
    comparison_headers, comparison_rows, comparison_totals = _comparison(rows, comparison_competencies)
    return {
        **empty,
        "rows": rows,
        "summary_rows": summary_rows,
        "comparison_headers": comparison_headers,
        "comparison_rows": comparison_rows,
        "comparison_totals": comparison_totals,
        "comparison_period_total": sum(comparison_totals, ZERO),
        "selected_competency": selected,
        "period_label": period_label,
        "competencies": competencies,
        "companies": companies,
        "units_for_filter": units_for_filter,
        "filters": filters,
        "has_more_competencies": has_more_competencies,
        "event_cost_total": total,
        "event_cost_count": event_count,
        "event_cost_unit_count": unit_count,
        "event_cost_collaborator_count": collaborator_count,
        "uncalculated_event_count": uncalculated_count,
        "unit_chart": unit_chart,
        "event_chart": event_chart,
        "trend_points": trend_points,
        "trend_segments": trend_segments,
        "trend_axis": trend_axis,
        "trend_has_data": trend_has_data,
        "variation": variation,
        "top_unit": unit_chart[0] if unit_chart else None,
        "top_event": event_chart[0] if event_chart else None,
        "status_choices": FieldEvent.STATUS_CHOICES,
    }
