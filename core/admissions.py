from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models, transaction
from django.utils import timezone

from .models import AdmissionRequest, AuditLog, Collaborator, EmploymentLink
from .roster_importer import cpf_fingerprint, normalize_text


def can_convert_admission(user, admission):
    if not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser:
        return True
    scopes = user.scopes.filter(tenant_id=admission.tenant_id)
    return (
        scopes.filter(role="platform", unit__isnull=True).exists()
        or scopes.filter(
            role__in=["dp", "management", "platform"], unit_id=admission.unit_id,
        ).filter(models.Q(company__isnull=True) | models.Q(company_id=admission.company_id)).exists()
    )


@transaction.atomic
def convert_admission(*, admission_id, user, data):
    admission = AdmissionRequest.objects.select_for_update().get(pk=admission_id)
    if not can_convert_admission(user, admission):
        raise PermissionDenied("Seu acesso não permite converter pré-admissões desta unidade.")
    if admission.status != "approved":
        raise ValidationError("Somente uma pré-admissão aprovada pode ser convertida.")
    if admission.converted_link_id:
        raise ValidationError("Esta pré-admissão já foi convertida; nenhum cadastro foi duplicado.")
    if (
        not admission.tenant.active or not admission.company.active or not admission.unit.active
        or admission.company.tenant_id != admission.tenant_id
        or admission.unit.tenant_id != admission.tenant_id
        or admission.unit.company_id != admission.company_id
    ):
        raise ValidationError("Empresa e unidade devem estar ativas e pertencer ao mesmo cliente e CNPJ.")

    fingerprint = cpf_fingerprint(data["cpf"])
    person = Collaborator.objects.select_for_update().filter(
        tenant=admission.tenant, cpf_fingerprint=fingerprint,
    ).first()
    if person is None:
        legacy_people = Collaborator.objects.filter(tenant=admission.tenant, cpf_fingerprint="")
        if any(normalize_text(item.name) == normalize_text(data["full_name"]) for item in legacy_people):
            raise ValidationError("Há um cadastro com este nome sem CPF identificado. Regularize a identidade antes de converter.")
        person, created = Collaborator.objects.get_or_create(
            tenant=admission.tenant, cpf_fingerprint=fingerprint,
            defaults={"name": data["full_name"], "cpf_masked": "***.***.***-**"},
        )
        person = Collaborator.objects.select_for_update().get(pk=person.pk)
    else:
        created = False
    if not person.active or normalize_text(person.name) != normalize_text(data["full_name"]):
        raise ValidationError("O CPF corresponde a um cadastro inativo ou com nome divergente. Revise o cadastro antes de converter.")
    if EmploymentLink.objects.filter(
        collaborator=person, company=admission.company, unit=admission.unit,
    ).filter(models.Q(termination_date__isnull=True) | models.Q(termination_date__gte=data["admission_date"])).exists():
        raise ValidationError("Já existe vínculo neste período para o colaborador nesta empresa/unidade.")
    employee_code = data["employee_code"]
    if employee_code and (
        EmploymentLink.objects.filter(company=admission.company, employee_code=employee_code).exclude(collaborator=person).exists()
        or Collaborator.objects.filter(tenant=admission.tenant, employee_code=employee_code).exclude(pk=person.pk).exists()
    ):
        raise ValidationError("A matrícula já identifica outro colaborador. Confira antes de converter.")

    link = EmploymentLink.objects.create(
        collaborator=person, company=admission.company, unit=admission.unit,
        employee_code=employee_code, job_title=data["job_title"], admission_date=data["admission_date"],
    )
    admission.converted_link = link
    admission.converted_by = user
    admission.converted_at = timezone.now()
    admission.save(update_fields=["converted_link", "converted_by", "converted_at", "updated_at"])
    AuditLog.objects.create(
        tenant=admission.tenant, user=user, action="create", entity="admission_conversion",
        entity_id=str(admission.pk), reason=data["reason"],
        before={"status": "approved", "converted_link_id": None},
        after={
            "collaborator_id": person.pk, "employment_link_id": link.pk,
            "company_id": admission.company_id, "unit_id": admission.unit_id,
            "admission_date": link.admission_date.isoformat(), "created_collaborator": created,
        },
    )
    return link
