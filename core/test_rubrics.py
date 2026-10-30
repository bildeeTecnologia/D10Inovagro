from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import (
    AuditLog, Collaborator, Company, Competency, PaymentCycle, PaymentEntry,
    Rubric, Tenant, Unit, UserScope,
)
from .payments import ensure_default_rubrics


class RubricCatalogTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Cliente Rubricas", slug="cliente-rubricas")
        self.user = User.objects.create_user(username="dp-rubricas")
        UserScope.objects.create(user=self.user, tenant=self.tenant, role="dp")
        self.client.force_login(self.user)
        self.payload = {
            "code": "FROTA_LIMPEZA",
            "name": "Adicional por limpeza de veículo",
            "category": "earning",
            "cycle_type": "none",
            "effective_from": "2026-10-01",
            "effective_to": "",
            "description": "Valor e periodicidade aguardando definição do DP.",
            "change_reason": "Catalogar para validação do DP.",
        }

    def create_rubric(self, **overrides):
        values = {
            key: value for key, value in self.payload.items()
            if key != "change_reason"
        }
        values.update(effective_from=date(2026, 10, 1), effective_to=None, active=False)
        values.update(overrides)
        return Rubric.objects.create(tenant=self.tenant, created_by=self.user, **values)

    def test_create_catalog_and_show_examples_without_financial_writes(self):
        response = self.client.get(reverse("rubric_create"))
        self.assertContains(response, "Como preencher corretamente")
        self.assertContains(response, "PENSAO_CONFERENCIA")
        self.assertFalse(response.context["form"].initial["active"])
        self.assertEqual(response.context["form"].initial["cycle_type"], "none")
        self.assertFalse(Rubric.objects.exists())

        payload = {**self.payload, "code": "frota_limpeza"}
        response = self.client.post(reverse("rubric_create"), payload)
        self.assertRedirects(response, reverse("rule_list"))
        rubric = Rubric.objects.get()
        self.assertEqual(rubric.code, "FROTA_LIMPEZA")
        self.assertFalse(rubric.active)
        self.assertEqual(rubric.tenant, self.tenant)
        self.assertEqual(rubric.created_by, self.user)
        self.assertEqual(rubric.version, 1)
        audit = AuditLog.objects.get(entity="rubric")
        self.assertEqual(audit.action, "create")
        self.assertEqual(audit.after["code"], rubric.code)
        self.assertEqual(audit.reason, payload["change_reason"])
        self.assertFalse(PaymentEntry.objects.exists())
        self.assertFalse(PaymentCycle.objects.exists())
        response = self.client.get(reverse("rule_list"))
        self.assertContains(response, "FROTA_LIMPEZA")
        self.assertContains(response, "Catálogo de rubricas")

    def test_informative_has_no_payment_cycle_and_is_audited(self):
        payload = {
            **self.payload, "code": "PENSAO_CONFERENCIA",
            "name": "Conferência da pensão", "category": "informative",
        }
        response = self.client.post(reverse("rubric_create"), {**payload, "cycle_type": "monthly"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("cycle_type", response.context["form"].errors)
        self.assertFalse(Rubric.objects.exists())
        response = self.client.post(reverse("rubric_create"), payload)
        self.assertRedirects(response, reverse("rule_list"))
        self.assertEqual(Rubric.objects.get().category, "informative")
        self.assertFalse(PaymentEntry.objects.exists())

    def test_validation_duplicate_reserved_code_dates_type_and_reason(self):
        self.create_rubric()
        invalid_payloads = [
            {"code": "frota_limpeza"},
            {"code": "ADICIONAL_12H"},
            {"code": "CODIGO COM ESPACO"},
            {"code": "OUTRA", "effective_to": "2026-09-30"},
            {"code": "OUTRA", "category": "invalid"},
            {"code": "OUTRA", "change_reason": ""},
        ]
        for overrides in invalid_payloads:
            with self.subTest(overrides=overrides):
                response = self.client.post(reverse("rubric_create"), {**self.payload, **overrides})
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["form"].errors)
        self.assertEqual(Rubric.objects.count(), 1)
        self.assertFalse(AuditLog.objects.filter(entity="rubric").exists())

    def test_edit_unused_preserves_code_owner_and_records_before_after(self):
        rubric = self.create_rubric()
        response = self.client.post(
            reverse("rubric_edit", args=[rubric.pk]),
            {**self.payload, "code": "TROCAR_CODIGO", "name": "Limpeza frota revisada", "active": "on"},
        )
        self.assertRedirects(response, reverse("rule_list"))
        rubric.refresh_from_db()
        self.assertEqual(rubric.code, "FROTA_LIMPEZA")
        self.assertEqual(rubric.name, "Limpeza frota revisada")
        self.assertTrue(rubric.active)
        self.assertEqual(rubric.created_by, self.user)
        audit = AuditLog.objects.get(entity="rubric")
        self.assertFalse(audit.before["active"])
        self.assertTrue(audit.after["active"])

    def test_system_and_used_rubrics_protect_financial_fields(self):
        system = ensure_default_rubrics(self.tenant, self.user)["ADICIONAL_12H"]
        used = self.create_rubric(active=True, cycle_type="monthly")
        company = Company.objects.create(tenant=self.tenant, legal_name="Empresa Teste", cnpj="11.111.111/0001-11")
        unit = Unit.objects.create(tenant=self.tenant, company=company, name="Unidade Teste")
        person = Collaborator.objects.create(tenant=self.tenant, name="Pessoa Teste", employee_code="T01")
        competency = Competency.objects.create(tenant=self.tenant, year=2026, month=10)
        cycle = PaymentCycle.objects.create(
            tenant=self.tenant, competency=competency, cycle_type="monthly", created_by=self.user,
        )
        entry = PaymentEntry.objects.create(
            tenant=self.tenant, cycle=cycle, collaborator=person, unit=unit,
            rubric=used, amount=Decimal("100.00"), created_by=self.user,
        )
        for rubric in (system, used):
            with self.subTest(code=rubric.code):
                original_name, original_cycle = rubric.name, rubric.cycle_type
                response = self.client.post(
                    reverse("rubric_edit", args=[rubric.pk]),
                    {
                        **self.payload, "name": "Tentativa de alteração",
                        "category": "deduction", "cycle_type": "none",
                        "description": "Orientações revisadas pelo DP.",
                    },
                )
                self.assertRedirects(response, reverse("rule_list"))
                rubric.refresh_from_db()
                self.assertEqual(rubric.name, original_name)
                self.assertEqual(rubric.category, "earning")
                self.assertEqual(rubric.cycle_type, original_cycle)
                self.assertTrue(rubric.active)
                self.assertEqual(rubric.description, "Orientações revisadas pelo DP.")
        entry.refresh_from_db()
        self.assertEqual(entry.amount, Decimal("100.00"))
        self.assertEqual(PaymentEntry.objects.count(), 1)

    def test_permissions_tenant_isolation_and_methods(self):
        other_tenant = Tenant.objects.create(name="Outro Cliente", slug="outro-cliente")
        foreign = Rubric.objects.create(
            tenant=other_tenant, created_by=self.user, code="RUBRICA_OUTRO_CLIENTE",
            name="Outra rubrica", category="earning", cycle_type="monthly",
            effective_from=date(2026, 10, 1),
        )
        listing = self.client.get(reverse("rule_list"))
        self.assertNotContains(listing, foreign.code)
        url = reverse("rubric_edit", args=[foreign.pk])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url, self.payload).status_code, 404)
        self.assertEqual(self.client.delete(reverse("rubric_create")).status_code, 405)
        UserScope.objects.filter(user=self.user).update(role="leader")
        for url in (reverse("rule_list"), reverse("rubric_create"), url):
            self.assertEqual(self.client.get(url).status_code, 403)
            self.assertEqual(self.client.post(url, self.payload).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(reverse("rubric_create")).status_code, 302)
        self.assertEqual(Rubric.objects.count(), 1)
