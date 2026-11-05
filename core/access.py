from functools import wraps

from django.shortcuts import render
from .navigation import AREAS, area_for_path


OPERATIONAL_ROLES = {"leader", "dp", "management", "finance", "accountant", "platform"}
OFFICE_ROLES = OPERATIONAL_ROLES - {"leader"}
CAPABILITY_ROLES = {
    "office": OFFICE_ROLES,
    "field": OPERATIONAL_ROLES,
    "rules": {"dp", "platform"},
    "review": {"dp", "management", "platform"},
    "admissions": {"dp", "management", "platform"},
}

_TENANT_UNSET = object()


def user_scopes(user):
    """Escopos do usuário, lidos uma vez por requisição (o usuário é recarregado a cada requisição)."""
    scopes = getattr(user, "_d10_scopes", None)
    if scopes is None:
        scopes = list(user.scopes.select_related("tenant", "company", "unit").order_by("tenant_id", "id"))
        user._d10_scopes = scopes
    return scopes


def user_roles(user, tenant):
    if tenant is None:
        return set()
    return {scope.role for scope in user_scopes(user) if scope.tenant_id == tenant.pk}


def tenant_for_user(user):
    if not user.is_authenticated:
        return None
    scopes = user_scopes(user)
    scope = scopes[0] if scopes else None
    return scope.tenant if scope and scope.tenant.active else None


def user_access(user, tenant=_TENANT_UNSET):
    if tenant is _TENANT_UNSET:
        tenant = tenant_for_user(user)
    roles = user_roles(user, tenant) if tenant else set()
    capabilities = {
        name: bool(tenant and (user.is_superuser or roles.intersection(allowed_roles)))
        for name, allowed_roles in CAPABILITY_ROLES.items()
    }
    return {
        **capabilities,
        "leader_only": capabilities["field"] and not capabilities["office"],
    }


def navigation_access(request):
    if not hasattr(request, "current_tenant"):
        request.current_tenant = tenant_for_user(request.user)
    if not hasattr(request, "platform_access"):
        request.platform_access = user_access(request.user, tenant=request.current_tenant)
    area = area_for_path(request.path)
    if request.resolver_match and request.resolver_match.url_name == "workspace_area":
        slug = request.resolver_match.kwargs.get("area_slug")
        if slug in AREAS:
            area = {"slug": slug, "title": AREAS[slug]["title"]}
    return {
        "platform_access": request.platform_access,
        "navigation_area": area,
        "current_tenant": request.current_tenant,
    }


def capability_required(capability):
    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            access = navigation_access(request)["platform_access"]
            if not access[capability]:
                return render(
                    request,
                    "core/empty_state.html",
                    {"title": "Seu perfil não tem acesso a esta área"},
                    status=403,
                )
            return view(request, *args, **kwargs)
        return wrapped
    return decorator
