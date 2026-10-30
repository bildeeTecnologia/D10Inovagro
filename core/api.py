import json
import uuid
from datetime import date
from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import AuditLog, FieldEvent
from .views import _allowed_units_for_user, _audit, _invalidate_approved_payment_cycles, _tenant_for_user


@login_required
@require_POST
def sync_events(request):
    tenant = _tenant_for_user(request.user)
    if not tenant:
        return JsonResponse({"error": "Usuário sem escopo de cliente."}, status=403)
    allowed_units = _allowed_units_for_user(request.user, tenant)
    try:
        payload = json.loads(request.body.decode("utf-8"))
        items = payload.get("events", [])
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"error": "JSON inválido."}, status=400)

    if not isinstance(items, list) or len(items) > 100:
        return JsonResponse({"error": "Envie uma lista com até 100 eventos."}, status=400)

    synced, conflicts, errors = [], [], []
    for item in items:
        try:
            key = uuid.UUID(str(item["idempotency_key"]))
            event = FieldEvent.objects.select_related("unit", "collaborator").filter(
                tenant=tenant, idempotency_key=key
            ).first()
            if event:
                synced.append({"client_id": item.get("client_id"), "event_id": event.id, "status": "already_synced"})
                continue
        except (KeyError, ValueError, TypeError):
            pass

        try:
            from .models import Collaborator, Competency, Unit
            key = uuid.UUID(str(item["idempotency_key"]))
            unit = Unit.objects.get(id=item["unit_id"], tenant=tenant, active=True, id__in=allowed_units)
            collaborator = Collaborator.objects.get(id=item["collaborator_id"], tenant=tenant, active=True, links__unit=unit)
            competency = Competency.objects.filter(tenant=tenant, status__in=["open", "review"]).order_by("-year", "-month").first()
            if not competency:
                raise ValueError("Não existe competência aberta.")
            event_date = date.fromisoformat(item["event_date"])
            if (event_date.year, event_date.month) != (competency.year, competency.month):
                raise ValueError("A data do evento não corresponde à competência aberta; peça ao DP orientação para regularizar o lançamento atrasado.")
            event_type = str(item["event_type"])
            valid_types = {choice[0] for choice in FieldEvent.EVENT_CHOICES}
            if event_type not in valid_types:
                raise ValueError("Tipo de evento inválido.")
            try:
                quantity = Decimal(str(item.get("quantity", "1")))
            except (InvalidOperation, TypeError):
                raise ValueError("Quantidade inválida.")
            if not quantity.is_finite() or quantity <= 0:
                raise ValueError("A quantidade deve ser maior que zero.")
            if event_type == "additional_12h" and quantity != Decimal("1"):
                raise ValueError("O Adicional 12h aceita somente uma ocorrência por lançamento.")
            application = None
            if event_type == "rubric":
                if (event_date.year, event_date.month) != (competency.year, competency.month):
                    raise ValueError("A data deve pertencer à competência aberta de trabalho.")
                from .models import RubricApplication
                from .rubric_applications import validate_event_application
                application = RubricApplication.objects.filter(
                    pk=item.get("application_id"), tenant=tenant, unit=unit,
                ).first()
                if not application:
                    raise ValueError("Regra de rubrica não encontrada nesta unidade.")
                validate_event_application(application, tenant, unit, collaborator, event_date, quantity)
            elif item.get("application_id"):
                raise ValueError("Regra de rubrica incompatível com o tipo de evento.")
            reason = str(item.get("reason", "")).strip()
            if len(reason) < 5:
                raise ValueError("O motivo precisa ter pelo menos 5 caracteres.")
            with transaction.atomic():
                locked_competency = Competency.objects.select_for_update().filter(
                    tenant=tenant,
                    status__in=["open", "review"],
                ).order_by("-year", "-month").first()
                if not locked_competency:
                    raise ValueError("Não existe competência aberta.")
                if (event_date.year, event_date.month) != (locked_competency.year, locked_competency.month):
                    raise ValueError("A competência mudou durante a sincronização; atualize os dados e tente novamente.")
                competency = locked_competency
                _invalidate_approved_payment_cycles(
                    competency,
                    request.user,
                    "Novo evento sincronizado após aprovação do ciclo.",
                )
                event = FieldEvent.objects.create(
                    tenant=tenant,
                    competency=competency,
                    unit=unit,
                    collaborator=collaborator,
                    event_type=event_type,
                    application=application,
                    event_date=event_date,
                    quantity=quantity,
                    reason=reason,
                    idempotency_key=key,
                    created_by=request.user,
                    sync_received_at=timezone.now(),
                )
                _audit(
                    tenant=tenant,
                    user=request.user,
                    action="create",
                    entity="field_event_sync",
                    entity_id=event.id,
                    after={"event_type": event.event_type, "unit_id": event.unit_id, "offline": True},
                )
            synced.append({"client_id": item.get("client_id"), "event_id": event.id, "status": "created"})
        except IntegrityError:
            conflicts.append({"client_id": item.get("client_id"), "reason": "Evento duplicado para colaborador, tipo e data."})
        except ValidationError as exc:
            errors.append({"client_id": item.get("client_id"), "reason": " ".join(exc.messages)})
        except (KeyError, ValueError, TypeError, Unit.DoesNotExist, Collaborator.DoesNotExist) as exc:
            errors.append({"client_id": item.get("client_id"), "reason": str(exc)})

    return JsonResponse({"synced": synced, "conflicts": conflicts, "errors": errors})
