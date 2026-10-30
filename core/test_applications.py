import json
import uuid
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from .models import (
    AuditLog, Collaborator, CollaboratorRubric, Company, Competency, EmploymentLink,
    FieldEvent, PaymentCycle, PaymentEntry, Rubric, RubricApplication, Tenant, Unit, UserScope,
)
from .rubric_applications import (
    application_blockers, approve_agreement, approve_application, end_agreement,
    end_application, generate_application_entries,
)
from .views import _competency_closing_blockers


class RubricApplicationTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Aplicações teste", slug="aplicacoes-teste")
        self.company = Company.objects.create(tenant=self.tenant, legal_name="Empresa teste", cnpj="22.222.222/0001-22")
        self.unit = Unit.objects.create(tenant=self.tenant, company=self.company, name="Unidade autorizada")
        self.other_unit = Unit.objects.create(tenant=self.tenant, company=self.company, name="Unidade restrita")
        self.person = Collaborator.objects.create(tenant=self.tenant, name="Pessoa teste", employee_code="SINT-1")
        self.employment = EmploymentLink.objects.create(
            collaborator=self.person, company=self.company, unit=self.unit,
            job_title="Auxiliar", admission_date=date(2026, 1, 1),
        )
        self.dp = User.objects.create_user(username="dp-aplicacoes")
        UserScope.objects.create(user=self.dp, tenant=self.tenant, role="dp", unit=self.unit)
        self.leader = User.objects.create_user(username="lider-aplicacoes")
        UserScope.objects.create(user=self.leader, tenant=self.tenant, role="leader", unit=self.unit)
        self.competency = Competency.objects.create(tenant=self.tenant, year=2026, month=10)
        self.client.force_login(self.dp)

    def application(self, *, code="FROTA_FIXA", mode="recurring", cycle="day10", unit=None, approve=True, **extra):
        rubric, _ = Rubric.objects.get_or_create(
            tenant=self.tenant, code=code, version=1,
            defaults={
                "name": f"Rubrica {code}", "category": "informative" if mode == "informative" else "earning",
                "cycle_type": cycle, "effective_from": date(2026, 1, 1), "created_by": self.dp,
            },
        )
        app = RubricApplication.objects.create(
            tenant=self.tenant, rubric=rubric, unit=unit or self.unit, mode=mode,
            amount=None if mode == "informative" else Decimal("80.00"), cycle_type=cycle,
            leader_available=mode == "event", effective_from=date(2026, 1, 1),
            instructions="Pagamento fixo autorizado para teste.", created_by=self.dp, **extra,
        )
        if approve:
            approve_application(app, self.dp, "Regra homologada em teste")
            app.refresh_from_db()
        return app

    def agreement(self, app, *, approve=True, **extra):
        values = {
            "tenant": self.tenant, "application": app, "collaborator": self.person,
            "effective_from": date(2026, 1, 1), "created_by": self.dp,
        }
        agreement = CollaboratorRubric.objects.create(**{**values, **extra})
        if approve:
            approve_agreement(agreement, self.dp, "Acordo homologado em teste")
            agreement.refresh_from_db()
        return agreement

    def event(self, app, **extra):
        values = {
            "tenant": self.tenant, "competency": self.competency, "unit": self.unit,
            "collaborator": self.person, "event_type": "rubric", "application": app,
            "event_date": date(2026, 10, 5), "quantity": 1, "reason": "Ocorrência autorizada",
            "status": "approved", "idempotency_key": uuid.uuid4(), "created_by": self.leader,
        }
        return FieldEvent.objects.create(**{**values, **extra})

    def payload(self, app, **extra):
        return {
            "client_id": "sintetico-1", "idempotency_key": str(uuid.uuid4()),
            "unit_id": self.unit.pk, "collaborator_id": self.person.pk,
            "event_type": "rubric", "application_id": app.pk, "event_date": "2026-10-05",
            "quantity": "1", "reason": "Ocorrência de teste", **extra,
        }

    def sync(self, payload):
        return self.client.post(reverse("sync_events"), json.dumps({"events": [payload]}), content_type="application/json")

    def test_recurring_without_events_is_idempotent_and_next_month_day10(self):
        agreement = self.agreement(self.application())
        self.assertTrue(application_blockers(self.competency))
        first = generate_application_entries(self.competency, self.dp)
        second = generate_application_entries(self.competency, self.dp)
        self.assertEqual([entry.pk for entry in first], [entry.pk for entry in second])
        entry = PaymentEntry.objects.get()
        self.assertEqual(entry.amount, Decimal("80.00"))
        self.assertEqual(entry.source_agreement, agreement)
        self.assertIsNone(entry.source_event)
        self.assertEqual(entry.cycle.payment_date, date(2026, 11, 10))
        self.assertEqual(entry.memory["rubric_code"], "FROTA_FIXA")
        self.assertFalse(application_blockers(self.competency))
        self.assertTrue(_competency_closing_blockers(self.competency))

    def test_informative_pension_never_creates_payment(self):
        app = self.application(code="PENSAO_REF", mode="informative", cycle="none")
        agreement = self.agreement(app, expected_amount=Decimal("123.45"), reference="Conferir folha oficial")
        self.assertIsNone(agreement.effective_to)
        self.assertEqual(generate_application_entries(self.competency, self.dp), [])
        self.assertFalse(PaymentCycle.objects.exists())
        self.assertFalse(application_blockers(self.competency))
        response = self.client.get(reverse("rule_list"))
        self.assertContains(response, "Conferir folha oficial")
        self.assertContains(response, "123,45")

    def test_partial_agreement_or_employment_explicitly_blocks_generation(self):
        agreement = self.agreement(self.application(), effective_from=date(2026, 10, 2))
        with self.assertRaisesMessage(ValueError, "mês parcial"):
            generate_application_entries(self.competency, self.dp)
        self.assertFalse(PaymentEntry.objects.exists())
        agreement.effective_from = date(2026, 1, 1)
        agreement.save()
        self.employment.termination_date = date(2026, 10, 15)
        self.employment.save()
        self.assertIn("mês parcial", " ".join(application_blockers(self.competency)))

    def test_only_approved_event_generates_fixed_payment_without_legacy_salary(self):
        app = self.application(mode="event", code="LIMPEZA_EVENTO", cycle="monthly")
        event = self.event(app, status="pending")
        self.assertFalse(generate_application_entries(self.competency, self.dp))
        event.status = "approved"
        event.save()
        self.assertTrue(application_blockers(self.competency))
        generate_application_entries(self.competency, self.dp)
        generate_application_entries(self.competency, self.dp)
        entry = PaymentEntry.objects.get()
        self.assertEqual(entry.source_event, event)
        self.assertIsNone(entry.source_agreement)
        self.assertEqual(entry.cycle.cycle_type, "monthly")
        self.assertFalse(application_blockers(self.competency))
        self.assertEqual(event.get_event_type_display(), app.rubric.name)
        self.assertFalse(hasattr(event, "calculation_result"))
        self.assertIn("não foi aprovado", " ".join(_competency_closing_blockers(self.competency)))

    def test_draft_overlap_immutability_and_controlled_end(self):
        app = self.application(approve=False)
        agreement = self.agreement(app, approve=False)
        with self.assertRaises(ValidationError):
            approve_agreement(agreement, self.dp, "Regra ainda não aprovada")
        approve_application(app, self.dp, "Regra homologada")
        approve_agreement(agreement, self.dp, "Vínculo homologado")
        duplicate_app = self.application(approve=False)
        with self.assertRaisesMessage(ValidationError, "Já existe regra"):
            approve_application(duplicate_app, self.dp, "Tentativa duplicada")
        duplicate = self.agreement(app, approve=False)
        with self.assertRaisesMessage(ValidationError, "já possui"):
            approve_agreement(duplicate, self.dp, "Tentativa duplicada")
        response = self.client.post(reverse("application_edit", args=[app.pk]), {"amount": "999"})
        self.assertRedirects(response, reverse("rule_list"))
        app.refresh_from_db()
        self.assertEqual(app.amount, Decimal("80"))
        with self.assertRaisesMessage(ValidationError, "Defina primeiro"):
            end_application(app, date(2026, 10, 31), self.dp, "Encerrar regra")
        duplicate.delete()
        end_agreement(agreement, date(2026, 10, 31), self.dp, "Encerramento autorizado")
        end_application(app, date(2026, 10, 31), self.dp, "Troca de valor a partir de novembro")
        app.refresh_from_db()
        app2 = RubricApplication.objects.create(
            tenant=self.tenant, unit=self.unit, rubric=app.rubric, mode="recurring",
            amount="100", cycle_type="day10", effective_from=date(2026, 11, 1),
            instructions="Novo valor aprovado", created_by=self.dp,
        )
        approve_application(app2, self.dp, "Novo período")
        self.assertTrue(AuditLog.objects.filter(entity="rubric_application", action="update").exists())

    def test_approved_closed_cycles_and_competency_block_writes(self):
        app = self.application()
        agreement = self.agreement(app)
        generate_application_entries(self.competency, self.dp)
        cycle = PaymentCycle.objects.get()
        cycle.status = "approved"
        cycle.save()
        with self.assertRaisesMessage(ValueError, "Ciclo aprovado"):
            generate_application_entries(self.competency, self.dp)
        with self.assertRaisesMessage(ValidationError, "ciclo aprovado"):
            end_agreement(agreement, date(2026, 10, 15), self.dp, "Fim indevido")
        draft = self.application(code="OUTRO", approve=False)
        with self.assertRaisesMessage(ValidationError, "ciclo aprovado"):
            approve_application(draft, self.dp, "Vigência retroativa indevida")
        self.competency.status = "closed"
        self.competency.save()
        with self.assertRaisesMessage(ValueError, "Competência fechada"):
            generate_application_entries(self.competency, self.dp)
        self.assertEqual(PaymentEntry.objects.get().amount, Decimal("80"))

    def test_offline_event_validation_and_duplicate_replay(self):
        app = self.application(mode="event", code="EVENTO")
        self.client.force_login(self.leader)
        payload = self.payload(app)
        response = self.sync(payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["synced"][0]["status"], "created")
        self.assertEqual(self.sync(payload).json()["synced"][0]["status"], "already_synced")
        self.assertEqual(FieldEvent.objects.count(), 1)
        self.assertEqual(FieldEvent.objects.get().application, app)
        self.assertTrue(self.sync(self.payload(app)).json()["conflicts"])
        another_app = self.application(mode="event", code="OUTRA_OCORRENCIA")
        self.assertEqual(self.sync(self.payload(another_app)).json()["synced"][0]["status"], "created")
        self.assertEqual(FieldEvent.objects.count(), 2)
        for extra in [
            {"quantity": "2"}, {"quantity": "NaN"}, {"application_id": None},
            {"event_date": "2026-11-05"}, {"event_type": "advance"},
        ]:
            with self.subTest(extra=extra):
                self.assertTrue(self.sync(self.payload(app, **extra)).json()["errors"])
        self.assertFalse(PaymentEntry.objects.exists())

    def test_offline_rejects_foreign_unit_draft_disabled_or_expired_rule(self):
        foreign = self.application(mode="event", unit=self.other_unit, code="RESTRITA")
        self.client.force_login(self.leader)
        self.assertTrue(self.sync(self.payload(foreign)).json()["errors"])
        draft = self.application(mode="event", code="RASCUNHO", approve=False)
        self.assertTrue(self.sync(self.payload(draft)).json()["errors"])
        inactive = self.application(mode="event", code="INATIVA")
        inactive.rubric.active = False
        inactive.rubric.save()
        self.assertTrue(self.sync(self.payload(inactive)).json()["errors"])
        expired = self.application(mode="event", code="EXPIRADA", effective_to=date(2026, 9, 30))
        self.assertTrue(self.sync(self.payload(expired)).json()["errors"])
        self.assertFalse(FieldEvent.objects.exists())

    def test_manual_event_and_leader_panel_use_configured_rule(self):
        app = self.application(mode="event", code="LIDER")
        foreign = self.application(mode="event", code="OUTRA_UNIDADE", unit=self.other_unit)
        self.client.force_login(self.leader)
        response = self.client.get(reverse("field_app"))
        self.assertContains(response, f'data-application-id="{app.pk}"')
        self.assertNotContains(response, foreign.rubric.name)
        payload = {
            "unit": self.unit.pk, "collaborator": self.person.pk, "event_type": "rubric",
            "application": app.pk, "event_date": "2026-10-07", "quantity": "1", "reason": "Evento manual configurado",
        }
        response = self.client.post(reverse("event_create"), payload)
        self.assertRedirects(response, reverse("field_app"))
        self.assertEqual(FieldEvent.objects.get().application, app)
        for extra in [{"application": foreign.pk}, {"quantity": "2"}, {"event_date": "2026-09-10"}]:
            response = self.client.post(reverse("event_create"), {**payload, **extra})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context["form"].errors)

    def test_rule_form_approval_and_scope_protect_forged_requests(self):
        rubric = Rubric.objects.create(
            tenant=self.tenant, code="VINCULAVEL", name="Frota sintética", category="earning",
            cycle_type="monthly", effective_from=date(2026, 1, 1), created_by=self.dp,
        )
        payload = {
            "rubric": rubric.pk, "unit": self.unit.pk, "mode": "recurring", "amount": "55.00",
            "cycle_type": "monthly", "effective_from": "2026-01-01",
            "instructions": "Limpeza mensal autorizada", "reason": "Criar regra para frota",
        }
        response = self.client.post(reverse("application_create"), {**payload, "unit": self.other_unit.pk})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)
        self.assertFalse(RubricApplication.objects.exists())
        response = self.client.post(reverse("application_create"), payload)
        self.assertRedirects(response, reverse("rule_list"))
        app = RubricApplication.objects.get()
        self.assertEqual(app.status, "draft")
        self.assertFalse(PaymentEntry.objects.exists())
        self.client.post(reverse("application_approve", args=[app.pk]), {"reason": "Aprovar regra de teste"})
        app.refresh_from_db()
        self.assertEqual(app.status, "approved")
        response = self.client.post(reverse("agreement_create"), {
            "application": app.pk, "collaborator": self.person.pk, "effective_from": "2026-01-01",
            "reference": "Acordo sintético", "reason": "Vincular colaborador",
        })
        self.assertRedirects(response, reverse("rule_list"))
        agreement = CollaboratorRubric.objects.get()
        self.client.post(reverse("agreement_approve", args=[agreement.pk]), {"reason": "Aprovar acordo de teste"})
        agreement.refresh_from_db()
        self.assertEqual(agreement.status, "approved")
        response = self.client.post(reverse("application_generate"), {"competency": self.competency.pk})
        self.assertRedirects(response, reverse("rule_list"))
        self.assertEqual(PaymentEntry.objects.get().amount, Decimal("55.00"))
        self.competency.refresh_from_db()
        self.assertEqual(self.competency.status, "review")
        cycle = PaymentCycle.objects.get()
        self.client.post(reverse("payment_cycle_approve", args=[cycle.pk]), {"reason": "Conferência final de teste"})
        cycle.refresh_from_db()
        self.assertEqual(cycle.status, "approved")
        self.assertFalse(_competency_closing_blockers(self.competency))
        self.client.force_login(self.leader)
        self.assertEqual(self.client.get(reverse("application_create")).status_code, 403)
        self.assertEqual(self.client.post(reverse("agreement_approve", args=[agreement.pk])).status_code, 403)

    def test_foreign_tenant_rule_is_rejected_and_catalog_protected(self):
        app = self.application()
        another = Tenant.objects.create(name="Outro cliente", slug="outro-cliente")
        foreign = Rubric.objects.create(
            tenant=another, code="OUTRA", name="Rubrica de outro cliente", category="earning",
            cycle_type="day10", effective_from=date(2026, 1, 1), created_by=self.dp,
        )
        app.rubric = foreign
        with self.assertRaisesMessage(ValidationError, "mesmo cliente"):
            app.full_clean()
        response = self.client.get(reverse("rubric_edit", args=[app.rubric_id]))
        self.assertEqual(response.status_code, 404)
        app.refresh_from_db()
        response = self.client.get(reverse("rubric_edit", args=[app.rubric_id]))
        self.assertTrue(response.context["form"].protected)
        self.assertTrue(response.context["form"].fields["category"].disabled)

    def test_generation_is_atomic_on_partial_source_and_future_end_preserves_history(self):
        app = self.application()
        agreement = self.agreement(app)
        partial_app = self.application(code="PARCIAL")
        partial = self.agreement(partial_app, effective_from=date(2026, 10, 2))
        with self.assertRaisesMessage(ValueError, "mês parcial"):
            generate_application_entries(self.competency, self.dp)
        self.assertFalse(PaymentEntry.objects.exists())
        partial.delete()
        generate_application_entries(self.competency, self.dp)
        with self.assertRaisesMessage(ValidationError, "já gerado"):
            end_agreement(agreement, date(2026, 10, 15), self.dp, "Não pode cortar mês pago")
        end_agreement(agreement, date(2026, 10, 31), self.dp, "Encerrar no fim do mês")
        november = Competency.objects.create(tenant=self.tenant, year=2026, month=11)
        self.assertFalse(generate_application_entries(november, self.dp))
        self.assertEqual(PaymentEntry.objects.count(), 1)

    def test_december_payment_is_january_and_scope_cannot_generate_another_unit(self):
        app = self.application(mode="event")
        december = Competency.objects.create(tenant=self.tenant, year=2026, month=12)
        self.event(app, competency=december, event_date=date(2026, 12, 31))
        entry = generate_application_entries(december, self.dp)[0]
        self.assertEqual(entry.cycle.payment_date, date(2027, 1, 10))
        entry.cycle.payment_date = date(2026, 12, 10)
        entry.cycle.save()
        self.assertIn("mês seguinte", " ".join(application_blockers(december)))
        with self.assertRaisesMessage(ValueError, "data incompatível"):
            generate_application_entries(december, self.dp)
        foreign_app = self.application(code="RESTRITA", unit=self.other_unit, approve=False)
        for route in ["application_edit", "application_approve", "application_end"]:
            response = self.client.post(reverse(route, args=[foreign_app.pk]), {"reason": "Solicitação não autorizada"})
            self.assertEqual(response.status_code, 404)
        foreign_app.status = "approved"
        foreign_app.save()
        foreign_person = Collaborator.objects.create(tenant=self.tenant, name="Outra pessoa sintética", employee_code="SINT-2")
        EmploymentLink.objects.create(
            collaborator=foreign_person, company=self.company, unit=self.other_unit,
            job_title="Auxiliar", admission_date=date(2026, 1, 1),
        )
        self.agreement(foreign_app, collaborator=foreign_person)
        response = self.client.post(reverse("application_generate"), {"competency": self.competency.pk})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(PaymentEntry.objects.filter(cycle__competency=self.competency).exists())
        self.assertEqual(self.client.post(reverse("calculation_run")).status_code, 403)

    def test_invalid_financial_definitions_and_missing_employment_are_rejected(self):
        app = self.application(approve=False)
        for changes in [
            {"amount": 0}, {"cycle_type": "monthly"},
            {"mode": "recurring", "leader_available": True}, {"mode": "informative"},
        ]:
            with self.subTest(changes=changes):
                app.refresh_from_db()
                for key, value in changes.items():
                    setattr(app, key, value)
                with self.assertRaises(ValidationError):
                    app.full_clean()
        app.refresh_from_db()
        app.rubric.category = "deduction"
        app.rubric.save()
        with self.assertRaisesMessage(ValidationError, "somente proventos"):
            approve_application(app, self.dp, "Desconto exige outro fluxo")
        app.rubric.category = "earning"
        app.rubric.save()
        approve_application(app, self.dp, "Aprovar provento")
        self.employment.admission_date = date(2026, 2, 1)
        self.employment.save()
        agreement = self.agreement(app, approve=False)
        with self.assertRaisesMessage(ValidationError, "vínculo de emprego"):
            approve_agreement(agreement, self.dp, "Sem vínculo no início")

    def test_health_and_conference_show_configured_event_not_missing_legacy_rule(self):
        from .quality import scan_tenant
        app = self.application(mode="event")
        event = self.event(app)
        issues = scan_tenant(self.tenant, [self.unit])
        self.assertFalse(issues.filter(event=event, issue_type="missing_rule").exists())
        generate_application_entries(self.competency, self.dp)
        response = self.client.get(reverse("conference"), {"competency": self.competency.pk, "status": "approved"})
        self.assertContains(response, "Memória de aplicação")
        response = self.client.get(reverse("payment_cycles"))
        self.assertContains(response, f"Evento #{event.pk}")
        self.assertContains(response, "Memória do lançamento")
