from datetime import date
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client, RequestFactory, TestCase

from .admission_forms import AdmissionConversionForm
from .admissions import convert_admission
from .models import (
    AdmissionFieldDefinition, AdmissionFieldValue, AdmissionRequest, AuditLog,
    Collaborator, Company, CompensationVersion, EmploymentLink, PaymentEntry,
    Tenant, Unit, UserScope,
)
from .roster_importer import cpf_fingerprint


class AdmissionConversionTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Cliente Conversão", slug="conversion")
        self.company = Company.objects.create(tenant=self.tenant, legal_name="Empresa Teste", cnpj="11.111.111/0001-11")
        self.unit = Unit.objects.create(tenant=self.tenant, company=self.company, name="Unidade Norte")
        self.user = User.objects.create_user(username="conversion-dp", password="test-password")
        UserScope.objects.create(user=self.user, tenant=self.tenant, company=self.company, unit=self.unit, role="dp")
        self.client.force_login(self.user)
        self.admission = self.make_admission()
        self.url = f"/admissoes/{self.admission.pk}/converter/"
        self.data = {
            "full_name": "Pessoa Exemplo", "cpf": "529.982.247-25",
            "employee_code": "ADM-001", "job_title": "Auxiliar",
            "admission_date": "2026-11-01", "reason": "Conferência cadastral concluída pelo DP.",
            "confirmed": "on",
        }

    def make_admission(self, **overrides):
        values = {
            "tenant": self.tenant, "company": self.company, "unit": self.unit,
            "candidate_name": "Pessoa Exemplo", "candidate_phone": "11999999999",
            "job_title": "Auxiliar", "expected_admission_date": date(2026, 11, 1),
            "status": "approved", "created_by": self.user, "reviewed_by": self.user,
            "access_key_hash": "not-a-public-key", "access_key_hint": "00",
        }
        return AdmissionRequest.objects.create(**(values | overrides))

    def make_person(self, **overrides):
        values = {
            "tenant": self.tenant, "name": "Pessoa Exemplo",
            "cpf_fingerprint": cpf_fingerprint("52998224725"),
        }
        return Collaborator.objects.create(**(values | overrides))

    def test_preview_uses_candidate_answers_and_does_not_create_records(self):
        for code, value in [("full_name", "Pessoa Exemplo Completo"), ("cpf", "529.982.247-25")]:
            field = AdmissionFieldDefinition.objects.create(tenant=self.tenant, code=code, label=code)
            AdmissionFieldValue.objects.create(request=self.admission, field=field, value=value)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["form"].initial["full_name"], "Pessoa Exemplo Completo")
        self.assertContains(response, self.company.cnpj)
        self.assertContains(response, self.unit.name)
        self.assertEqual(Collaborator.objects.count(), 0)
        self.assertEqual(EmploymentLink.objects.count(), 0)

    def test_conversion_creates_audited_records_without_financial_effects(self):
        response = self.client.post(self.url, self.data, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Conversão concluída")
        self.admission.refresh_from_db()
        link = self.admission.converted_link
        self.assertEqual(link.employee_code, "ADM-001")
        self.assertEqual(link.unit, self.unit)
        self.assertEqual(link.company, self.company)
        self.assertEqual(link.job_title, "Auxiliar")
        self.assertEqual(link.admission_date, date(2026, 11, 1))
        self.assertEqual(link.collaborator.cpf_fingerprint, cpf_fingerprint("52998224725"))
        self.assertEqual(link.collaborator.cpf_masked, "***.***.***-**")
        self.assertEqual(self.admission.converted_by, self.user)
        self.assertIsNotNone(self.admission.converted_at)
        self.assertEqual(self.admission.status, "approved")
        log = AuditLog.objects.get(entity="admission_conversion")
        self.assertEqual(log.user, self.user)
        self.assertEqual(log.after["employment_link_id"], link.pk)
        self.assertEqual(log.reason, self.data["reason"])
        self.assertNotIn("529", str(log.after))
        self.assertEqual(CompensationVersion.objects.count(), 0)
        self.assertEqual(PaymentEntry.objects.count(), 0)
        self.assertContains(self.client.get("/admissoes/"), "Ver cadastro gerado")

    def test_second_post_and_direct_service_call_cannot_duplicate(self):
        self.client.post(self.url, self.data)
        self.client.post(self.url, self.data)
        form = AdmissionConversionForm(self.data)
        self.assertTrue(form.is_valid())
        with self.assertRaisesMessage(ValidationError, "já foi convertida"):
            convert_admission(admission_id=self.admission.pk, user=self.user, data=form.cleaned_data)
        self.assertEqual(Collaborator.objects.count(), 1)
        self.assertEqual(EmploymentLink.objects.count(), 1)
        self.assertEqual(AuditLog.objects.filter(entity="admission_conversion").count(), 1)

    def test_only_approved_requests_can_be_converted(self):
        for status, _ in AdmissionRequest.STATUS_CHOICES:
            if status == "approved":
                continue
            with self.subTest(status=status):
                self.admission.status = status
                self.admission.save(update_fields=["status"])
                self.assertEqual(self.client.post(self.url, self.data).status_code, 302)
        self.assertEqual(Collaborator.objects.count(), 0)
        self.assertEqual(EmploymentLink.objects.count(), 0)

    def test_invalid_or_unconfirmed_input_blocks_conversion(self):
        for changes in [
            {"cpf": "123.456.789-00"}, {"cpf": "529982247250"}, {"cpf": ""},
            {"confirmed": ""}, {"reason": ""}, {"job_title": ""}, {"admission_date": "invalid"},
            {"full_name": ""},
        ]:
            with self.subTest(changes=changes):
                response = self.client.post(self.url, self.data | changes)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["form"].errors)
        self.assertEqual(Collaborator.objects.count(), 0)
        self.assertEqual(EmploymentLink.objects.count(), 0)

    def test_existing_person_is_reused_without_overwriting_data(self):
        person = self.make_person(name="PESSOA EXEMPLO", employee_code="LEGACY")
        other_unit = Unit.objects.create(tenant=self.tenant, company=self.company, name="Outra unidade")
        EmploymentLink.objects.create(
            collaborator=person, company=self.company, unit=other_unit,
            employee_code="OTHER", job_title="Operador", admission_date=date(2025, 1, 1),
        )
        self.assertEqual(self.client.post(self.url, self.data).status_code, 302)
        person.refresh_from_db()
        self.assertEqual(person.name, "PESSOA EXEMPLO")
        self.assertEqual(person.employee_code, "LEGACY")
        self.assertEqual(Collaborator.objects.count(), 1)
        self.assertEqual(person.links.count(), 2)
        self.admission.refresh_from_db()
        self.assertEqual(self.admission.converted_link.collaborator, person)

    def test_ambiguous_identity_or_inactive_person_is_rejected(self):
        for changes in [
            {"name": "Outro nome"}, {"active": False}, {"cpf_fingerprint": ""},
        ]:
            with self.subTest(changes=changes):
                person = self.make_person(**changes)
                response = self.client.post(self.url, self.data)
                self.assertTrue(response.context["form"].non_field_errors())
                self.assertEqual(EmploymentLink.objects.count(), 0)
                person.delete()

    def test_overlapping_link_blocks_but_ended_link_allows_readmission(self):
        person = self.make_person()
        link = EmploymentLink.objects.create(
            collaborator=person, company=self.company, unit=self.unit,
            job_title="Auxiliar", admission_date=date(2025, 1, 1),
        )
        for termination in [None, date(2026, 11, 1), date(2026, 12, 1)]:
            link.termination_date = termination
            link.save()
            self.assertContains(self.client.post(self.url, self.data), "Já existe vínculo")
        link.termination_date = date(2026, 10, 31)
        link.save()
        self.assertEqual(self.client.post(self.url, self.data).status_code, 302)
        self.assertEqual(person.links.count(), 2)

    def test_employee_code_used_by_another_person_blocks_and_rolls_back(self):
        other = Collaborator.objects.create(tenant=self.tenant, name="Outra Pessoa", employee_code="ADM-001")
        self.assertContains(self.client.post(self.url, self.data), "matrícula já identifica outro")
        self.assertEqual(Collaborator.objects.count(), 1)
        other.employee_code = ""
        other.save()
        EmploymentLink.objects.create(
            collaborator=other, company=self.company, unit=self.unit,
            employee_code="ADM-001", job_title="Auxiliar", admission_date=date(2025, 1, 1),
        )
        self.assertContains(self.client.post(self.url, self.data), "matrícula já identifica outro")
        self.assertEqual(Collaborator.objects.count(), 1)
        self.assertEqual(EmploymentLink.objects.count(), 1)

    def test_access_requires_admission_role_in_this_unit(self):
        scope = self.user.scopes.get()
        for role in ["leader", "finance", "accountant"]:
            scope.role = role
            scope.save()
            with self.subTest(role=role):
                self.assertEqual(self.client.get(self.url).status_code, 403)
                self.assertEqual(self.client.post(self.url, self.data).status_code, 403)
        other_unit = Unit.objects.create(tenant=self.tenant, company=self.company, name="Outra unidade")
        scope.role = "dp"
        scope.unit = other_unit
        scope.save()
        UserScope.objects.create(user=self.user, tenant=self.tenant, unit=self.unit, role="leader")
        self.assertEqual(self.client.post(self.url, self.data).status_code, 403)
        scope.role = "management"
        scope.unit = self.unit
        scope.save()
        self.assertEqual(self.client.post(self.url, self.data).status_code, 302)

    def test_other_tenant_and_anonymous_access_are_blocked(self):
        other_tenant = Tenant.objects.create(name="Outro cliente", slug="other-conversion")
        self.admission.tenant = other_tenant
        self.admission.save(update_fields=["tenant"])
        self.assertEqual(self.client.post(self.url, self.data).status_code, 404)
        self.client.logout()
        self.assertRedirects(self.client.get(self.url), f"/login/?next={self.url}", fetch_redirect_response=False)
        self.assertEqual(EmploymentLink.objects.count(), 0)

    def test_inactive_or_inconsistent_company_unit_blocks_conversion(self):
        self.company.active = False
        self.company.save()
        self.assertContains(self.client.post(self.url, self.data), "devem estar ativas")
        self.company.active = True
        self.company.save()
        self.unit.active = False
        self.unit.save()
        self.assertContains(self.client.post(self.url, self.data), "devem estar ativas")
        self.unit.active = True
        self.unit.company = Company.objects.create(tenant=self.tenant, legal_name="Outro CNPJ", cnpj="22.222.222/0001-22")
        self.unit.save()
        self.assertContains(self.client.post(self.url, self.data), "mesmo cliente e CNPJ")
        self.assertEqual(Collaborator.objects.count(), 0)

    def test_converted_request_cannot_be_edited_and_candidate_access_stays_closed(self):
        self.client.post(self.url, self.data)
        self.assertRedirects(
            self.client.post(f"/admissoes/{self.admission.pk}/editar/", {"candidate_name": "Alterado"}),
            f"/admissoes/{self.admission.pk}/conferir/",
        )
        self.admission.refresh_from_db()
        self.assertEqual(self.admission.candidate_name, "Pessoa Exemplo")
        previous_token = self.admission.access_key_hash
        self.assertRedirects(
            self.client.post(f"/admissoes/{self.admission.pk}/regenerar-acesso/"),
            f"/admissoes/{self.admission.pk}/conferir/",
        )
        self.admission.refresh_from_db()
        self.assertEqual(self.admission.access_key_hash, previous_token)
        self.client.logout()
        response = self.client.get(f"/admissao/preencher/{self.admission.token}/")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="full_name"')

    def test_admin_cannot_modify_or_delete_converted_admissions(self):
        self.client.post(self.url, self.data)
        self.admission.refresh_from_db()
        self.user.is_superuser = True
        self.user.is_staff = True
        self.user.save()
        request = RequestFactory().get("/admin/")
        request.user = self.user
        model_admin = admin.site._registry[AdmissionRequest]
        self.assertFalse(model_admin.has_change_permission(request, self.admission))
        self.assertFalse(model_admin.has_delete_permission(request, self.admission))
        with self.assertRaises(PermissionDenied):
            model_admin.delete_queryset(request, AdmissionRequest.objects.filter(pk=self.admission.pk))
        self.assertTrue(AdmissionRequest.objects.filter(pk=self.admission.pk).exists())

    def test_post_requires_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post(self.url, self.data).status_code, 403)
        self.assertEqual(EmploymentLink.objects.count(), 0)

    def test_audit_failure_rolls_back_conversion(self):
        form = AdmissionConversionForm(self.data)
        self.assertTrue(form.is_valid())
        with patch("core.admissions.AuditLog.objects.create", side_effect=RuntimeError("audit unavailable")):
            with self.assertRaisesMessage(RuntimeError, "audit unavailable"):
                convert_admission(admission_id=self.admission.pk, user=self.user, data=form.cleaned_data)
        self.admission.refresh_from_db()
        self.assertIsNone(self.admission.converted_link_id)
        self.assertEqual(Collaborator.objects.count(), 0)
        self.assertEqual(EmploymentLink.objects.count(), 0)
