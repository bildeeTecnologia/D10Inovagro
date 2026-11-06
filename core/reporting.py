from io import BytesIO
from decimal import Decimal, ROUND_HALF_UP

from django.http import HttpResponse
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

from .models import EmploymentLink, FieldEvent


def money(value):
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _event_label(event_type, rubric_name=""):
    if event_type == "rubric":
        return rubric_name or "Evento de rubrica configurada"
    return dict(FieldEvent.EVENT_CHOICES).get(event_type, event_type)


def build_report_data(queryset, report_type):
    if report_type == "monthly":
        results = list(queryset.select_related("competency", "collaborator", "unit", "unit__company"))
        collaborator_ids = {r.collaborator_id for r in results}
        unit_ids = {r.unit_id for r in results}
        links = {}
        if collaborator_ids:
            for link in EmploymentLink.objects.filter(
                collaborator_id__in=collaborator_ids, unit_id__in=unit_ids,
            ).order_by("admission_date"):
                links[(link.collaborator_id, link.unit_id)] = link
        rows = []
        for r in results:
            link = links.get((r.collaborator_id, r.unit_id))
            rows.append({
                "competencia": f"{r.competency.month:02d}/{r.competency.year}",
                "colaborador": r.collaborator.name,
                "empresa": r.unit.company.legal_name,
                "cnpj": r.unit.company.cnpj,
                "admissao": link.admission_date.strftime("%d/%m/%Y") if link else "",
                "funcao": link.job_title if link else "",
                "cpf": r.collaborator.cpf_masked or "***.***.***-**",
                "unidade": r.unit.name,
                "dias_normais": r.normal_days, "dias_chuva": r.rain_days,
                "normal": r.normal_amount, "chuva": r.rain_amount, "total": r.total_amount,
            })
        return rows, []
    if report_type == "events":
        rows = [{"competencia": f"{e.competency.month:02d}/{e.competency.year}", "unidade": e.unit.name, "colaborador": e.collaborator.name, "tipo": e.get_event_type_display(), "data": e.event_date.strftime("%d/%m/%Y"), "quantidade": float(e.quantity), "status": e.get_status_display(), "motivo": e.reason} for e in queryset.select_related("unit", "collaborator", "competency")]
        inconsistencies = [r for r in rows if r["status"] in {"Pendente", "Rejeitado"}]
        return rows, inconsistencies
    if report_type == "event_costs":
        status_labels = dict(FieldEvent.STATUS_CHOICES)
        rows = []
        for item in queryset:
            total = item["total"] or Decimal("0.00")
            event_count = item["event_count"] or 0
            average = (total / Decimal(event_count)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if event_count else Decimal("0.00")
            rows.append({
                "competencia": f"{item['competency__month']:02d}/{item['competency__year']}",
                "unidade": f"{item['event__unit__name']} — {item['event__unit__company__legal_name']} (CNPJ {item['event__unit__company__cnpj']})",
                "evento": _event_label(item["event__event_type"], item.get("event__application__rubric__name") or ""),
                "status": status_labels.get(item["event__status"], item["event__status"]),
                "quantidade": event_count,
                "total": total,
                "media": average,
            })
        return rows, []
    rows = [{"competencia": f"{r['competency__month']:02d}/{r['competency__year']}", "unidade": r["event__unit__name"], "total": r["total"] or Decimal("0.00")} for r in queryset]
    return rows, []


def legacy_monthly_header(rows):
    """Texto do bloco Empresa/CNPJ/Competência compartilhado entre a tela e o XLSX."""
    companies = {(row["empresa"], row.get("cnpj", "")) for row in rows}
    competencies = {row["competencia"] for row in rows}
    if len(companies) == 1:
        empresa_text, cnpj_text = next(iter(companies))
    else:
        empresa_text = f"{len(companies)} empresas (ver coluna Empresa)" if companies else "—"
        cnpj_text = "—"
    competencia_text = next(iter(competencies)) if len(competencies) == 1 else (", ".join(sorted(competencies)) if competencies else "—")
    return {"empresa": empresa_text, "cnpj": cnpj_text, "competencia": competencia_text}


def create_legacy_monthly_xlsx(rows, metadata):
    """Mesmo molde visual das planilhas de referência do cliente (Pjt_Models/COMBINADO, Liquido):

    bloco de cabeçalho institucional (Empresa/CNPJ/Competência), cabeçalho de colunas em
    negrito sem preenchimento colorido e linha de total ao final.
    """
    columns = [
        ("n", "n", 6),
        ("colaborador", "Colaborador", 42),
        ("empresa", "Empresa", 34),
        ("admissao", "Admissão", 14),
        ("funcao", "Função", 22),
        ("cpf", "CPF", 16),
        ("unidade", "Unidade", 20),
        ("dias_normais", "Dias normais", 12),
        ("dias_chuva", "Dias chuva", 12),
        ("normal", "Valor normal", 16),
        ("chuva", "Valor chuva", 16),
        ("total", "Total", 16),
    ]
    money_keys = {"normal", "chuva", "total"}
    last_col = len(columns)
    last_col_letter = get_column_letter(last_col)

    wb = Workbook()
    ws = wb.active
    ws.title = "Composição Mensal"

    title_font = Font(name="Arial", size=14, bold=True)
    header_block_font = Font(name="Arial", size=11, bold=True)
    column_header_font = Font(name="Arial", size=11, bold=True)
    bottom_border = Border(bottom=Side(style="thin"))

    ws.merge_cells(f"A1:{last_col_letter}1")
    ws["A1"] = metadata["title"]
    ws["A1"].font = title_font
    ws["A1"].alignment = Alignment(horizontal="center")

    header = legacy_monthly_header(rows)
    empresa_text, cnpj_text, competencia_text = header["empresa"], header["cnpj"], header["competencia"]

    for row_index, label, value in (
        (2, "EMPRESA:", empresa_text),
        (3, "CNPJ Nº", cnpj_text),
        (4, "COMPETÊNCIA:", competencia_text),
    ):
        ws.merge_cells(f"A{row_index}:{last_col_letter}{row_index}")
        cell = ws[f"A{row_index}"]
        cell.value = f"{label} {value}"
        cell.font = header_block_font

    header_row = 5
    for col_index, (key, label, width) in enumerate(columns, start=1):
        cell = ws.cell(row=header_row, column=col_index, value=label)
        cell.font = column_header_font
        cell.border = bottom_border
        ws.column_dimensions[get_column_letter(col_index)].width = width

    data_start = header_row + 1
    for offset, row in enumerate(rows):
        excel_row = data_start + offset
        values = [
            offset + 1, row["colaborador"], row["empresa"], row["admissao"], row["funcao"],
            row["cpf"], row["unidade"], row["dias_normais"], row["dias_chuva"],
            row["normal"], row["chuva"], row["total"],
        ]
        for col_index, value in enumerate(values, start=1):
            cell = ws.cell(row=excel_row, column=col_index, value=value)
            if columns[col_index - 1][0] in money_keys:
                cell.number_format = "R$ #,##0.00"

    total_row = data_start + len(rows)
    ws.merge_cells(f"A{total_row}:{get_column_letter(last_col - 1)}{total_row}")
    total_label = ws.cell(row=total_row, column=1, value="TOTAL")
    total_label.font = Font(name="Arial", size=11, bold=True)
    total_value = ws.cell(row=total_row, column=last_col, value=sum((row["total"] for row in rows), Decimal("0.00")))
    total_value.font = Font(name="Arial", size=11, bold=True)
    total_value.number_format = "R$ #,##0.00"

    ws.freeze_panes = f"A{data_start}"
    output = BytesIO()
    wb.save(output)
    return output.getvalue()


def create_xlsx(report_type, rows, inconsistencies, metadata):
    if report_type == "monthly":
        return create_legacy_monthly_xlsx(rows, metadata)
    wb = Workbook()
    summary = wb.active
    summary.title = "Resumo"
    summary.append(["Relatório", metadata["title"]])
    summary.append(["Emissor", metadata["user"]])
    summary.append(["Emissão", metadata["issued_at"]])
    summary.append(["Filtros", metadata["filters_text"]])
    summary.append(["Total de linhas", len(rows)])
    summary.append([])
    detail = wb.create_sheet("Detalhamento")
    if rows:
        headers = list(rows[0].keys())
    elif report_type == "cost":
        headers = ["competencia", "unidade", "total"]
    elif report_type == "event_costs":
        headers = ["competencia", "unidade", "evento", "status", "quantidade", "total", "media"]
    elif report_type == "monthly":
        headers = ["competencia", "colaborador", "unidade", "dias_normais", "dias_chuva", "normal", "chuva", "total"]
    else:
        headers = ["competencia", "unidade", "colaborador", "tipo", "data", "quantidade", "status", "motivo"]
    detail.append(headers)
    for row in rows:
        detail.append([money(value) if key in {"total", "media"} else value for key, value in row.items()])
    issue = wb.create_sheet("Inconsistências")
    issue.append(headers)
    for row in inconsistencies:
        issue.append([row.get(key, "") for key in headers])
    for ws in wb.worksheets:
        ws.freeze_panes = "A2"
        for cell in ws[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="116149")
            cell.alignment = Alignment(horizontal="center")
        for column in ws.columns:
            width = min(max(max(len(str(c.value or "")) for c in column) + 2, 12), 42)
            ws.column_dimensions[column[0].column_letter].width = width
    output = BytesIO()
    wb.save(output)
    return output.getvalue()


def create_pdf(report_type, rows, inconsistencies, metadata):
    output = BytesIO()
    doc = SimpleDocTemplate(output, pagesize=landscape(A4), rightMargin=12 * mm, leftMargin=12 * mm, topMargin=12 * mm, bottomMargin=12 * mm)
    styles = getSampleStyleSheet()
    story = [Paragraph(metadata["title"], styles["Title"]), Paragraph(f"Emissor: {metadata['user']} | Emissão: {metadata['issued_at']}", styles["Normal"]), Paragraph(f"Filtros: {metadata['filters_text']}", styles["Normal"]), Spacer(1, 8)]
    if report_type == "monthly":
        header = ["Competência", "Colaborador", "Unidade", "Dias normais", "Dias chuva", "Valor normal", "Valor chuva", "Total"]
        data = [header] + [[r["competencia"], r["colaborador"], r["unidade"], r["dias_normais"], r["dias_chuva"], money(r["normal"]), money(r["chuva"]), money(r["total"])] for r in rows]
    elif report_type == "event_costs":
        header = ["Competência", "Unidade", "Evento", "Status", "Qtd. eventos", "Valor calculado", "Média/evento"]
        data = [header] + [[r["competencia"], r["unidade"], r["evento"], r["status"], r["quantidade"], money(r["total"]), money(r["media"])] for r in rows]
    elif report_type == "cost":
        header = ["Competência", "Unidade", "Total"]
        data = [header] + [[r["competencia"], r["unidade"], money(r["total"])] for r in rows]
    else:
        header = ["Competência", "Unidade", "Colaborador", "Tipo", "Data", "Qtd.", "Status"]
        data = [header] + [[r["competencia"], r["unidade"], r["colaborador"], r["tipo"], r["data"], r["quantidade"], r["status"]] for r in rows]
    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#116149")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("GRID", (0, 0), (-1, -1), 0.25, colors.grey), ("FONTSIZE", (0, 0), (-1, -1), 8), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(table)
    story.append(Spacer(1, 8))
    story.append(Paragraph(f"Linhas emitidas: {len(rows)} | Inconsistências identificadas: {len(inconsistencies)}", styles["Normal"]))
    if inconsistencies:
        story.append(Paragraph("Atenção: existem eventos pendentes ou rejeitados. Este relatório não representa fechamento definitivo.", styles["Normal"]))
    if report_type == "event_costs":
        story.append(Paragraph("Valores calculados registrados no sistema; não comprovam pagamento efetuado. Eventos sem resultado de cálculo não entram no total.", styles["Normal"]))
    doc.build(story)
    return output.getvalue()


def response_file(content, content_type, filename):
    response = HttpResponse(content, content_type=content_type)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
