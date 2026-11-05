import time
import uuid

import jwt
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from .access import capability_required, tenant_for_user
from .views import _allowed_units_for_user


TOKEN_TTL_SECONDS = 300


def _error_response(message, status):
    response = JsonResponse({"error": message}, status=status)
    response["Cache-Control"] = "private, no-store"
    response["Pragma"] = "no-cache"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@login_required
@capability_required("review")
@require_GET
def conference_realtime_token(request):
    """Issue a short-lived Realtime token scoped to the current DP view."""
    tenant = tenant_for_user(request.user)
    if tenant is None:
        return _error_response("Acesso indisponível.", 403)

    units = _allowed_units_for_user(request.user, tenant)
    competency_id = request.GET.get("competency", "")
    if competency_id:
        try:
            competency = tenant.competencies.get(pk=int(competency_id))
        except (TypeError, ValueError, tenant.competencies.model.DoesNotExist):
            return _error_response("Competência inválida.", 404)
    else:
        competency = tenant.competencies.order_by("-year", "-month").first()
    if competency is None:
        return _error_response("Nenhuma competência disponível.", 409)

    unit_id = request.GET.get("unit", "")
    if unit_id:
        try:
            unit_id = int(unit_id)
        except (TypeError, ValueError):
            return _error_response("Unidade inválida.", 400)
        if not units.filter(pk=unit_id).exists():
            return _error_response("Unidade fora do escopo.", 403)
        unit_ids = [unit_id]
    else:
        unit_ids = list(units.values_list("id", flat=True))

    private_key = settings.SUPABASE_REALTIME_SIGNING_PRIVATE_KEY
    key_id = settings.SUPABASE_REALTIME_SIGNING_KEY_ID
    supabase_url = settings.SUPABASE_REALTIME_URL
    publishable_key = settings.SUPABASE_PUBLISHABLE_KEY
    issuer = settings.SUPABASE_REALTIME_ISSUER
    if not all((private_key, key_id, supabase_url, publishable_key, issuer)):
        return _error_response("Atualização em tempo real indisponível.", 503)

    now = int(time.time())
    expires_at = now + TOKEN_TTL_SECONDS
    claims = {
        "iss": issuer,
        "sub": str(uuid.uuid5(uuid.NAMESPACE_URL, f"d10-django-user:{tenant.pk}:{request.user.pk}")),
        "role": "authenticated",
        "iat": now,
        "exp": expires_at,
        "tenant_id": str(tenant.pk),
        "unit_ids": [int(value) for value in unit_ids],
        "competency_id": str(competency.pk),
    }
    try:
        token = jwt.encode(
            claims,
            private_key.replace("\\n", "\n"),
            algorithm="ES256",
            headers={"kid": key_id, "typ": "JWT"},
        )
    except (ValueError, TypeError, jwt.InvalidKeyError):
        return _error_response("Atualização em tempo real indisponível.", 503)

    topics = [
        f"conference:tenant:{tenant.pk}:unit:{allowed_unit_id}:competency:{competency.pk}"
        for allowed_unit_id in unit_ids
    ]
    response = JsonResponse({
        "token": token,
        "expires_at": expires_at,
        "supabase_url": supabase_url,
        "publishable_key": publishable_key,
        "topics": topics,
    })
    response["Cache-Control"] = "private, no-store"
    response["Pragma"] = "no-cache"
    response["X-Content-Type-Options"] = "nosniff"
    return response
