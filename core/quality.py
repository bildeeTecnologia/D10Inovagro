from datetime import date

from django.db.models import Q
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import CalculationRule, DataQualityIssue, Notification


def scan_tenant(tenant, units):
    now = timezone.now()
    fingerprints = set()

    def issue(*, fingerprint, issue_type, severity, title, description, event=None, unit=None, competency=None):
        fingerprints.add(fingerprint)
        obj, created = DataQualityIssue.objects.update_or_create(
            tenant=tenant,
            fingerprint=fingerprint,
            defaults={"issue_type": issue_type, "severity": severity, "status": "open", "title": title, "description": description, "event": event, "unit": unit, "competency": competency},
        )
        if created and severity == "critical":
            recipients = tenant.user_scopes.filter(role__in=["dp", "management", "platform"]).values_list("user_id", flat=True).distinct()
            Notification.objects.bulk_create([Notification(tenant=tenant, recipient_id=user_id, notification_type="system", title="Inconsistência crítica identificada", body=title) for user_id in recipients])
        return obj

    events = tenant.events.filter(unit__in=units).select_related("unit", "collaborator", "competency", "application__rubric")
    for event in events:
        if event.status == "pending":
            issue(fingerprint=f"pending:{event.id}", issue_type="pending_event", severity="warning", title="Evento aguardando conferência", description=f"{event.get_event_type_display()} de {event.collaborator.name} ainda não foi conferido.", event=event, unit=event.unit, competency=event.competency)
        if event.status == "rejected":
            issue(fingerprint=f"rejected:{event.id}", issue_type="rejected_event", severity="warning", title="Evento rejeitado", description=f"{event.get_event_type_display()} de {event.collaborator.name} precisa de providência.", event=event, unit=event.unit, competency=event.competency)
        if event.event_date.year != event.competency.year or event.event_date.month != event.competency.month:
            issue(fingerprint=f"date:{event.id}", issue_type="outside_competency", severity="critical", title="Evento fora da competência", description=f"O evento de {event.event_date:%d/%m/%Y} está vinculado à competência {event.competency.month:02d}/{event.competency.year}.", event=event, unit=event.unit, competency=event.competency)
        if not event.collaborator.links.filter(unit=event.unit, admission_date__lte=event.event_date).filter(Q(termination_date__isnull=True) | Q(termination_date__gte=event.event_date)).exists():
            issue(fingerprint=f"link:{event.id}", issue_type="missing_link", severity="critical", title="Colaborador sem vínculo válido", description=f"Não existe vínculo ativo de {event.collaborator.name} para {event.unit.name} na data do evento.", event=event, unit=event.unit, competency=event.competency)
        if event.status in {"pending", "approved"} and event.event_type == "rubric":
            from .rubric_applications import validate_event_application
            try:
                validate_event_application(event.application, tenant, event.unit, event.collaborator, event.event_date, event.quantity)
            except ValidationError as exc:
                issue(fingerprint=f"rule:{event.id}", issue_type="missing_rule", severity="critical", title="Regra de rubrica indisponível", description=" ".join(exc.messages), event=event, unit=event.unit, competency=event.competency)
        elif event.status in {"pending", "approved"} and event.event_type not in {"occurrence", "advance"} and not CalculationRule.objects.filter(tenant=tenant, event_type=event.event_type, status="published", effective_from__lte=event.event_date).filter(Q(effective_to__isnull=True) | Q(effective_to__gte=event.event_date)).filter(Q(unit=event.unit) | Q(unit__isnull=True)).exists():
            issue(fingerprint=f"rule:{event.id}", issue_type="missing_rule", severity="critical", title="Regra publicada não encontrada", description=f"Não há regra publicada para {event.get_event_type_display()} na data do evento.", event=event, unit=event.unit, competency=event.competency)

    DataQualityIssue.objects.filter(tenant=tenant, status="open").exclude(fingerprint__in=fingerprints).update(status="resolved", updated_at=now)
    return DataQualityIssue.objects.filter(tenant=tenant, status="open", unit__in=units).select_related("unit", "competency", "event")


def health_summary(tenant, units):
    issues = scan_tenant(tenant, units)
    threads = tenant.communication_threads.filter(unit__in=units).exclude(status__in=["resolved", "closed"])
    overdue = threads.filter(due_at__lt=timezone.now()).count()
    return {
        "issues": issues,
        "critical_count": issues.filter(severity="critical").count(),
        "warning_count": issues.filter(severity="warning").count(),
        "pending_events": tenant.events.filter(unit__in=units, status="pending").count(),
        "rejected_events": tenant.events.filter(unit__in=units, status="rejected").count(),
        "open_threads": threads.count(),
        "overdue_threads": overdue,
        "unsynced_events": tenant.events.filter(unit__in=units, sync_received_at__isnull=False, status="pending").count(),
    }
