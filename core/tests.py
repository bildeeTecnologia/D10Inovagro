import json
from io import BytesIO
import uuid
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from openpyxl import Workbook
from reportlab.pdfgen import canvas

from .models import AdmissionRequest, CalculationResult, CalculationRule, Collaborator, Company, CompensationVersion, Competency, DataQualityIssue, EmploymentLink, FieldEvent, ImportBatch, MonthlyCompensationResult, PaymentCycle, PaymentEntry, ReportEmission, Rubric, Tenant, Unit, UserScope
from .models import AuditLog
from .compensation import calculate_monthly_compensation
from .calculation import calculate_event
from .payments import ensure_default_rubrics, generate_day10_entries, generate_monthly_entries


class FieldBackendTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Cliente Teste", slug="cliente-teste")
        self.company = Company.objects.create(tenant=self.tenant, legal_name="Cliente Teste Ltda.", cnpj="11.111.111/0001-11")
        self.unit_allowed = Unit.objects.create(tenant=self.tenant, company=self.company, name="Unidade Permitida")
        self.unit_blocked = Unit.objects.create(tenant=self.tenant, company=self.company, name="Unidade Bloqueada")
        self.person_allowed = Collaborator.objects.create(tenant=self.tenant, name="Pessoa Permitida", employee_code="T-001")
        self.person_blocked = Collaborator.objects.create(tenant=self.tenant, name="Pessoa Bloqueada", employee_code="T-002")
        EmploymentLink.objects.create(collaborator=self.person_allowed, company=self.company, unit=self.unit_allowed, job_title="Auxiliar", admission_date=date(2026, 1, 1))
        EmploymentLink.objects.create(collaborator=self.person_blocked, company=self.company, unit=self.unit_blocked, job_title="Auxiliar", admission_date=date(2026, 1, 1))
        Competency.objects.create(tenant=self.tenant, year=2026, month=10, status="open")
        self.user = User.objects.create_user(username="leader", password="secret123")
        UserScope.objects.create(user=self.user, tenant=self.tenant, unit=self.unit_allowed, role="leader")
        self.client.login(username="leader", password="secret123")

    def test_unit_rejects_company_from_another_tenant(self):
        other_tenant = Tenant.objects.create(name="Outro cliente", slug="outro-cliente-unidade")
        other_company = Company.objects.create(tenant=other_tenant, legal_name="Empresa externa Ltda.", cnpj="22.222.222/0001-22")
        unit = Unit(tenant=self.tenant, company=other_company, name="Unidade inconsistente")

        with self.assertRaises(ValidationError):
            unit.save()

        self.assertFalse(Unit.objects.filter(name="Unidade inconsistente").exists())

    def test_employment_link_and_compensation_reject_cross_company_pairing(self):
        other_company = Company.objects.create(tenant=self.tenant, legal_name="Outro CNPJ Ltda.", cnpj="33.333.333/0001-33")
        other_unit = Unit.objects.create(tenant=self.tenant, company=other_company, name="Unidade de outro CNPJ")
        link = EmploymentLink(
            collaborator=self.person_allowed,
            company=self.company,
            unit=other_unit,
            job_title="Auxiliar",
            admission_date=date(2026, 1, 1),
        )
        compensation = CompensationVersion(
            collaborator=self.person_allowed,
            company=self.company,
            unit=other_unit,
            combined_salary="5000.00",
            clt_salary="2316.96",
            effective_from=date(2026, 1, 1),
            reason="Teste sintético",
            created_by=self.user,
        )

        with self.assertRaises(ValidationError):
            link.save()
        with self.assertRaises(ValidationError):
            compensation.save()

        self.assertFalse(EmploymentLink.objects.filter(unit=other_unit, collaborator=self.person_allowed).exists())
        self.assertFalse(CompensationVersion.objects.filter(unit=other_unit, collaborator=self.person_allowed).exists())

    def test_operational_views_and_sync_isolate_all_five_companies(self):
        UserScope.objects.create(user=self.user, tenant=self.tenant, unit=self.unit_allowed, role="dp")
        competency = Competency.objects.get(tenant=self.tenant)
        foreign_records = []
        for index, prefix in enumerate(("44", "55", "66", "77"), start=2):
            company = Company.objects.create(
                tenant=self.tenant,
                legal_name=f"Empresa sintética {index} Ltda.",
                cnpj=f"{prefix}.{prefix}.{prefix}/0001-{prefix}",
            )
            unit = Unit.objects.create(tenant=self.tenant, company=company, name=f"Unidade sintética {index}")
            person = Collaborator.objects.create(
                tenant=self.tenant,
                name=f"Pessoa fora do escopo {index}",
                employee_code=f"SYNTH-{index}",
            )
            EmploymentLink.objects.create(
                collaborator=person,
                company=company,
                unit=unit,
                job_title="Auxiliar",
                admission_date=date(2026, 1, 1),
            )
            event = FieldEvent.objects.create(
                tenant=self.tenant,
                competency=competency,
                unit=unit,
                collaborator=person,
                event_type="daily",
                event_date=date(2026, 10, 15),
                quantity=1,
                reason=f"Evento de CNPJ sintético {index}",
                status="pending",
                idempotency_key=uuid.uuid4(),
                created_by=self.user,
            )
            foreign_records.append((index, unit, person, event))
        self.assertEqual(Company.objects.filter(tenant=self.tenant).count(), 5)

        for path in ["/", "/lancamentos/", "/conferencia/", "/relatorios/?report_type=events"]:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                for index, _unit, person, _event in foreign_records:
                    self.assertNotContains(response, f"Evento de CNPJ sintético {index}")
                    self.assertNotContains(response, person.name)

        for index, unit, person, event in foreign_records:
            attempt_reason = f"Tentativa fora do escopo por CNPJ {index}"
            payload = {"events": [{
                "client_id": f"foreign-company-attempt-{index}",
                "idempotency_key": str(uuid.uuid4()),
                "unit_id": unit.id,
                "collaborator_id": person.id,
                "event_type": "daily",
                "event_date": "2026-10-20",
                "quantity": "1",
                "reason": attempt_reason,
            }]}
            response = self.client.post("/api/v1/events/sync/", data=json.dumps(payload), content_type="application/json")
            with self.subTest(company=index):
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["synced"], [])
                self.assertFalse(FieldEvent.objects.filter(reason=attempt_reason).exists())
                self.assertTrue(FieldEvent.objects.filter(pk=event.pk).exists())

    def test_leader_lands_on_field_app_without_office_navigation(self):
        response = self.client.get("/", follow=True)
        self.assertRedirects(response, "/campo/")
        self.assertContains(response, 'aria-label="Navegação do líder"')
        self.assertNotContains(response, '<aside class="sidebar">')
        self.assertContains(response, "images/inovagro-logo.jpg")
        for path in ["/regras/", "/conferencia/", "/fechamento/", "/relatorios/", "/pagamentos/", "/importacao/", "/admissoes/", "/saude/"]:
            with self.subTest(path=path):
                self.assertNotContains(response, f'href="{path}"')
        self.assertContains(response, "Pessoa Permitida")
        self.assertNotContains(response, "Pessoa Bloqueada")
        for path in ["/lancamentos/", "/lancamentos/novo/", "/calendario/", "/comunicacao/", "/configuracoes/"]:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

    def test_field_app_displays_simple_pwa_install_guides(self):
        response = self.client.get("/campo/")
        self.assertContains(response, 'id="pwa-install-card"')
        self.assertContains(response, 'id="pwa-install-button"')
        self.assertContains(response, "Celular Android")
        self.assertContains(response, "iPhone ou iPad")
        self.assertContains(response, "Computador")
        self.assertContains(response, "Antes de ir para o campo")

    def test_leader_cannot_open_office_pages_or_submit_office_actions(self):
        paths = [
            "/regras/", "/regras/rubricas/nova/", "/regras/aplicacoes/nova/",
            "/regras/vinculos/novo/", "/regras/aplicacoes/gerar/",
            "/regras/999/publicar/", "/calculo/executar/",
            "/conferencia/", "/conferencia/999/approve/",
            "/fechamento/", "/fechamento/999/close/",
            "/relatorios/", "/relatorios/exportar/xlsx/", "/relatorios/exportar/pdf/",
            "/pagamentos/", "/pagamentos/999/aprovar/",
            "/importacao/", "/admissoes/", "/admissoes/nova/",
            "/admissoes/999/editar/", "/admissoes/999/conferir/", "/admissoes/999/converter/",
            "/admissoes/999/regenerar-acesso/", "/admissoes/999/approve/", "/saude/",
        ]
        for path in paths:
            with self.subTest(path=path):
                self.assertIn(self.client.get(path).status_code, [403, 405])
                self.assertEqual(self.client.post(path).status_code, 403)
        self.assertEqual(PaymentEntry.objects.count(), 0)
        self.assertEqual(ReportEmission.objects.count(), 0)
        self.assertEqual(ImportBatch.objects.count(), 0)
        self.assertEqual(AdmissionRequest.objects.count(), 0)

    def test_navigation_respects_office_roles_and_multiple_scopes(self):
        expected = {
            "dp": (True, True, True),
            "management": (False, True, True),
            "finance": (False, False, False),
            "accountant": (False, False, False),
            "platform": (True, True, True),
        }
        for role, (rules, review, admissions) in expected.items():
            scope = UserScope.objects.create(user=self.user, tenant=self.tenant, unit=self.unit_allowed, role=role)
            with self.subTest(role=role):
                response = self.client.get("/")
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, '<aside class="sidebar">')
                self.assertContains(response, 'href="/relatorios/"')
                self.assertContains(response, 'href="/areas/pessoas/"', count=1 if admissions else 0)
                area_response = self.client.get("/areas/fechamento/")
                for path, visible in [("/regras/", rules), ("/conferencia/", review), ("/importacao/", admissions)]:
                    self.assertContains(area_response, f'href="{path}"', count=1 if visible else 0)
                for path in ["/regras/", "/conferencia/", "/admissoes/", "/importacao/"]:
                    self.assertNotContains(response, f'href="{path}"')
            scope.delete()
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/relatorios/").status_code, 200)

    def test_office_role_in_another_tenant_does_not_unlock_leader_access(self):
        other = Tenant.objects.create(name="Outro cliente", slug="outro-cliente")
        UserScope.objects.create(user=self.user, tenant=other, role="platform")
        self.assertRedirects(self.client.get("/"), "/campo/")
        self.assertEqual(self.client.get("/pagamentos/").status_code, 403)

    def test_anonymous_login_remains_available(self):
        self.client.logout()
        response = self.client.get("/login/")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'href="/pagamentos/"')
        self.assertNotContains(response, 'action="/logout/"')
        self.assertRedirects(self.client.get("/campo/"), "/login/?next=/campo/", fetch_redirect_response=False)

    def test_logout_button_submits_a_csrf_protected_form(self):
        response = self.client.get("/campo/")
        self.assertContains(response, '<form class="logout-form" method="post" action="/logout/">')
        self.assertContains(response, 'name="csrfmiddlewaretoken"')
        self.assertContains(response, '<button class="logout-button" type="submit">Sair</button>')
        self.assertNotContains(response, 'href="/logout/"')

    def test_logout_ends_session_and_allows_switching_user(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        client.get("/campo/")
        previous_session = client.cookies["sessionid"].value
        response = client.post("/logout/", {
            "csrfmiddlewaretoken": client.cookies["csrftoken"].value,
        }, follow=True)
        self.assertRedirects(response, "/login/")
        self.assertContains(response, "<h1>Entrar</h1>")
        self.assertNotIn("_auth_user_id", client.session)
        for path in ["/", "/campo/", "/configuracoes/"]:
            with self.subTest(path=path):
                self.assertRedirects(client.get(path), f"/login/?next={path}", fetch_redirect_response=False)
        stale_client = Client()
        stale_client.cookies["sessionid"] = previous_session
        self.assertRedirects(stale_client.get("/campo/"), "/login/?next=/campo/", fetch_redirect_response=False)
        other_user = User.objects.create_user(username="other-leader", password="other-test-password")
        response = client.post("/login/", {
            "username": other_user.username,
            "password": "other-test-password",
            "csrfmiddlewaretoken": client.cookies["csrftoken"].value,
        })
        self.assertRedirects(response, "/", fetch_redirect_response=False)
        self.assertEqual(client.session["_auth_user_id"], str(other_user.pk))

    def test_logout_requires_post_and_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.get("/logout/").status_code, 405)
        self.assertEqual(client.post("/logout/").status_code, 403)
        self.assertEqual(client.session["_auth_user_id"], str(self.user.pk))

    def test_dashboard_does_not_expose_other_unit(self):
        UserScope.objects.create(user=self.user, tenant=self.tenant, unit=self.unit_allowed, role="dp")
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Unidade Permitida")
        self.assertNotContains(response, "Unidade Bloqueada")

    def test_conference_filters_events_and_shows_calculation_details(self):
        UserScope.objects.create(user=self.user, tenant=self.tenant, unit=self.unit_allowed, role="dp")
        competency = Competency.objects.get(tenant=self.tenant)
        rule = CalculationRule.objects.create(
            tenant=self.tenant,
            code="DIARIA",
            version=1,
            name="Diária de teste",
            event_type="daily",
            status="published",
            parameters={"base_days": "30"},
            effective_from=date(2026, 1, 1),
            created_by=self.user,
            approved_by=self.user,
        )
        approved_event = FieldEvent.objects.create(
            tenant=self.tenant,
            competency=competency,
            unit=self.unit_allowed,
            collaborator=self.person_allowed,
            event_type="daily",
            event_date=date(2026, 10, 10),
            quantity=1,
            reason="Diária aprovada",
            status="approved",
            idempotency_key=uuid.uuid4(),
            created_by=self.user,
            approved_by=self.user,
        )
        CalculationResult.objects.create(
            tenant=self.tenant,
            competency=competency,
            event=approved_event,
            collaborator=self.person_allowed,
            rule=rule,
            base_amount="100.00",
            factor="1",
            calculated_amount="100.00",
            memory={"formula": "salário / 30"},
        )
        FieldEvent.objects.create(
            tenant=self.tenant,
            competency=competency,
            unit=self.unit_allowed,
            collaborator=self.person_allowed,
            event_type="overtime",
            event_date=date(2026, 10, 11),
            quantity=1,
            reason="Hora extra pendente",
            status="pending",
            idempotency_key=uuid.uuid4(),
            created_by=self.user,
        )
        FieldEvent.objects.create(
            tenant=self.tenant,
            competency=competency,
            unit=self.unit_blocked,
            collaborator=self.person_blocked,
            event_type="daily",
            event_date=date(2026, 10, 12),
            quantity=1,
            reason="Evento fora do escopo",
            status="pending",
            idempotency_key=uuid.uuid4(),
            created_by=self.user,
        )

        response = self.client.get("/conferencia/?status=all")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["pending_count"], 1)
        self.assertEqual(response.context["approved_count"], 1)
        self.assertContains(response, "Diária aprovada")
        self.assertContains(response, "salário / 30")
        displayed_event = next(item for item in response.context["events"] if item.id == approved_event.id)
        self.assertEqual(displayed_event.calculation_result.calculated_amount, Decimal("100.00"))
        self.assertNotContains(response, "Evento fora do escopo")

        filtered = self.client.get(f"/conferencia/?status=approved&unit={self.unit_allowed.id}")
        self.assertEqual([event.id for event in filtered.context["events"]], [approved_event.id])

    def test_conference_decision_requires_valid_post_and_invalidates_approved_cycle(self):
        UserScope.objects.create(user=self.user, tenant=self.tenant, unit=self.unit_allowed, role="dp")
        competency = Competency.objects.get(tenant=self.tenant)
        event = FieldEvent.objects.create(
            tenant=self.tenant,
            competency=competency,
            unit=self.unit_allowed,
            collaborator=self.person_allowed,
            event_type="daily",
            event_date=date(2026, 10, 13),
            quantity=1,
            reason="Evento em conferência",
            status="pending",
            idempotency_key=uuid.uuid4(),
            created_by=self.user,
        )
        cycle = PaymentCycle.objects.create(
            tenant=self.tenant,
            competency=competency,
            cycle_type="monthly",
            status="approved",
            created_by=self.user,
            approved_by=self.user,
        )
        entry = PaymentEntry.objects.create(
            tenant=self.tenant,
            cycle=cycle,
            collaborator=self.person_allowed,
            unit=self.unit_allowed,
            rubric=ensure_default_rubrics(self.tenant, self.user)["SAL_COMBINADO_NORMAL"],
            amount="100.00",
            status="approved",
            created_by=self.user,
        )

        self.assertEqual(self.client.get(f"/conferencia/{event.id}/approve/").status_code, 403)
        self.assertEqual(self.client.post(f"/conferencia/{event.id}/invalid/").status_code, 400)
        response = self.client.post(f"/conferencia/{event.id}/approve/", {"reason": "Conferido pelo DP"})

        self.assertEqual(response.status_code, 302)
        event.refresh_from_db()
        cycle.refresh_from_db()
        entry.refresh_from_db()
        self.assertEqual(event.status, "approved")
        self.assertEqual(cycle.status, "draft")
        self.assertEqual(cycle.approved_by, None)
        self.assertEqual(entry.status, "draft")

    def test_conference_decision_cannot_change_event_in_closed_competency(self):
        UserScope.objects.create(user=self.user, tenant=self.tenant, unit=self.unit_allowed, role="dp")
        competency = Competency.objects.get(tenant=self.tenant)
        competency.status = "closed"
        competency.save(update_fields=["status"])
        event = FieldEvent.objects.create(
            tenant=self.tenant,
            competency=competency,
            unit=self.unit_allowed,
            collaborator=self.person_allowed,
            event_type="daily",
            event_date=date(2026, 10, 16),
            quantity=1,
            reason="Evento sintético após fechamento",
            status="pending",
            idempotency_key=uuid.uuid4(),
            created_by=self.user,
        )
        cycle = PaymentCycle.objects.create(
            tenant=self.tenant, competency=competency, cycle_type="monthly",
            status="approved", created_by=self.user, approved_by=self.user,
        )

        response = self.client.post(f"/conferencia/{event.id}/approve/", {"reason": "Tentativa posterior ao fechamento"})

        self.assertEqual(response.status_code, 302)
        event.refresh_from_db()
        cycle.refresh_from_db()
        self.assertEqual(event.status, "pending")
        self.assertEqual(cycle.status, "approved")

    def test_admin_cannot_mutate_closed_workflow_records(self):
        competency = Competency.objects.get(tenant=self.tenant)
        competency.status = "closed"
        competency.save(update_fields=["status"])
        cycle = PaymentCycle.objects.create(
            tenant=self.tenant, competency=competency, cycle_type="monthly",
            status="approved", created_by=self.user, approved_by=self.user,
        )
        entry = PaymentEntry.objects.create(
            tenant=self.tenant,
            cycle=cycle,
            collaborator=self.person_allowed,
            unit=self.unit_allowed,
            rubric=ensure_default_rubrics(self.tenant, self.user)["SAL_COMBINADO_NORMAL"],
            amount="100.00",
            status="approved",
            created_by=self.user,
        )
        audit = AuditLog.objects.create(
            tenant=self.tenant, user=self.user, action="close", entity="competency",
            entity_id=str(competency.pk), after={"status": "closed"}, reason="Fechamento de teste",
        )
        admin_user = User.objects.create_superuser("workflow-admin", "workflow-admin@example.test", "test-admin-password")
        admin_client = Client()
        admin_client.force_login(admin_user)

        paths = [
            (f"/admin/core/competency/{competency.pk}/change/", {"status": "open"}),
            (f"/admin/core/paymentcycle/{cycle.pk}/change/", {"status": "draft"}),
            (f"/admin/core/paymententry/{entry.pk}/change/", {"amount": "1.00"}),
        ]
        for path, payload in paths:
            with self.subTest(path=path):
                self.assertEqual(admin_client.post(path, payload).status_code, 403)
        self.assertEqual(admin_client.get(f"/admin/core/auditlog/{audit.pk}/delete/").status_code, 403)

        competency.refresh_from_db()
        cycle.refresh_from_db()
        entry.refresh_from_db()
        self.assertEqual(competency.status, "closed")
        self.assertEqual(cycle.status, "approved")
        self.assertEqual(entry.status, "approved")
        self.assertTrue(AuditLog.objects.filter(pk=audit.pk).exists())

    def test_sync_is_idempotent(self):
        key = str(uuid.uuid4())
        payload = {"events": [{"client_id": "client-1", "idempotency_key": key, "unit_id": self.unit_allowed.id, "collaborator_id": self.person_allowed.id, "event_type": "daily", "event_date": "2026-10-20", "quantity": "1", "reason": "Evento de teste"}]}
        first = self.client.post("/api/v1/events/sync/", data=json.dumps(payload), content_type="application/json")
        second = self.client.post("/api/v1/events/sync/", data=json.dumps(payload), content_type="application/json")
        self.assertEqual(first.json()["synced"][0]["status"], "created")
        self.assertEqual(second.json()["synced"][0]["status"], "already_synced")
        self.assertEqual(FieldEvent.objects.filter(idempotency_key=key).count(), 1)

    def test_sync_rejects_unit_outside_scope(self):
        payload = {"events": [{"client_id": "client-2", "idempotency_key": str(uuid.uuid4()), "unit_id": self.unit_blocked.id, "collaborator_id": self.person_blocked.id, "event_type": "daily", "event_date": "2026-10-20", "quantity": "1", "reason": "Tentativa indevida"}]}
        response = self.client.post("/api/v1/events/sync/", data=json.dumps(payload), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["synced"], [])
        self.assertEqual(len(response.json()["errors"]), 1)
        self.assertEqual(FieldEvent.objects.count(), 0)

    def test_sync_rejects_event_from_closed_competency_instead_of_assigning_latest_open(self):
        october = Competency.objects.get(tenant=self.tenant)
        october.status = "closed"
        october.save(update_fields=["status"])
        Competency.objects.create(tenant=self.tenant, year=2026, month=11, status="open")
        payload = {"events": [{
            "client_id": "late-october-event",
            "idempotency_key": str(uuid.uuid4()),
            "unit_id": self.unit_allowed.id,
            "collaborator_id": self.person_allowed.id,
            "event_type": "daily",
            "event_date": "2026-10-28",
            "quantity": "1",
            "reason": "Lançamento atrasado de teste",
        }]}

        response = self.client.post("/api/v1/events/sync/", data=json.dumps(payload), content_type="application/json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["synced"], [])
        self.assertIn("não corresponde à competência aberta", response.json()["errors"][0]["reason"])
        self.assertEqual(FieldEvent.objects.count(), 0)

    def test_sync_rejects_invalid_additional_12h_quantity(self):
        payload = {"events": [{"client_id": "client-12h", "idempotency_key": str(uuid.uuid4()), "unit_id": self.unit_allowed.id, "collaborator_id": self.person_allowed.id, "event_type": "additional_12h", "event_date": "2026-10-20", "quantity": "2", "reason": "Permanência extraordinária"}]}
        response = self.client.post("/api/v1/events/sync/", data=json.dumps(payload), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["synced"], [])
        self.assertIn("somente uma ocorrência", response.json()["errors"][0]["reason"])

    def test_syncing_new_event_invalidates_approved_payment_cycle(self):
        competency = Competency.objects.get(tenant=self.tenant)
        cycle = PaymentCycle.objects.create(tenant=self.tenant, competency=competency, cycle_type="monthly", status="approved", created_by=self.user, approved_by=self.user)
        rubric = ensure_default_rubrics(self.tenant, self.user)["SAL_COMBINADO_NORMAL"]
        entry = PaymentEntry.objects.create(tenant=self.tenant, cycle=cycle, collaborator=self.person_allowed, unit=self.unit_allowed, rubric=rubric, amount="100.00", status="approved", created_by=self.user)
        payload = {"events": [{"client_id": "new-after-approval", "idempotency_key": str(uuid.uuid4()), "unit_id": self.unit_allowed.id, "collaborator_id": self.person_allowed.id, "event_type": "daily", "event_date": "2026-10-21", "quantity": "1", "reason": "Novo evento após aprovação"}]}

        response = self.client.post("/api/v1/events/sync/", data=json.dumps(payload), content_type="application/json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["synced"][0]["status"], "created")
        cycle.refresh_from_db()
        entry.refresh_from_db()
        self.assertEqual(cycle.status, "draft")
        self.assertEqual(cycle.approved_by, None)
        self.assertEqual(entry.status, "draft")

    def test_reports_export_xlsx_and_pdf_with_audit(self):
        UserScope.objects.create(user=self.user, tenant=self.tenant, unit=self.unit_allowed, role="dp")
        self.assertEqual(self.client.get("/relatorios/?report_type=events").status_code, 200)
        xlsx = self.client.get("/relatorios/exportar/xlsx/?report_type=events&status=pending")
        pdf = self.client.get("/relatorios/exportar/pdf/?report_type=cost")
        event_cost_xlsx = self.client.get("/relatorios/exportar/xlsx/?report_type=event_costs")
        event_cost_pdf = self.client.get("/relatorios/exportar/pdf/?report_type=event_costs")
        self.assertEqual(xlsx.status_code, 200)
        self.assertTrue(xlsx.content.startswith(b"PK"))
        self.assertEqual(pdf.status_code, 200)
        self.assertTrue(pdf.content.startswith(b"%PDF-"))
        self.assertEqual(event_cost_xlsx.status_code, 200)
        self.assertTrue(event_cost_xlsx.content.startswith(b"PK"))
        self.assertEqual(event_cost_pdf.status_code, 200)
        self.assertTrue(event_cost_pdf.content.startswith(b"%PDF-"))
        self.assertEqual(ReportEmission.objects.count(), 4)

    def test_event_cost_report_compares_competencies_and_units_with_approved_values_by_default(self):
        UserScope.objects.create(user=self.user, tenant=self.tenant, unit=self.unit_allowed, role="dp")
        second_unit = Unit.objects.create(tenant=self.tenant, company=self.company, name="Unidade Secundária")
        UserScope.objects.create(user=self.user, tenant=self.tenant, unit=second_unit, role="dp")
        EmploymentLink.objects.create(
            collaborator=self.person_allowed,
            company=self.company,
            unit=second_unit,
            job_title="Auxiliar",
            admission_date=date(2026, 1, 1),
        )
        other_company = Company.objects.create(
            tenant=self.tenant,
            legal_name="Empresa Secundária Ltda.",
            cnpj="22.222.222/0001-22",
        )
        duplicate_name_unit = Unit.objects.create(tenant=self.tenant, company=other_company, name="Unidade Permitida")
        UserScope.objects.create(user=self.user, tenant=self.tenant, unit=duplicate_name_unit, role="dp")
        EmploymentLink.objects.create(
            collaborator=self.person_allowed,
            company=other_company,
            unit=duplicate_name_unit,
            job_title="Auxiliar",
            admission_date=date(2026, 1, 1),
        )
        october = Competency.objects.get(tenant=self.tenant, year=2026, month=10)
        september = Competency.objects.create(tenant=self.tenant, year=2026, month=9)
        rule_12h = CalculationRule.objects.create(
            tenant=self.tenant,
            code="TESTE_12H_RELATORIO",
            name="Adicional 12h de teste",
            event_type="additional_12h",
            status="published",
            effective_from=date(2026, 1, 1),
            created_by=self.user,
            approved_by=self.user,
        )
        rule_overtime = CalculationRule.objects.create(
            tenant=self.tenant,
            code="TESTE_HE_RELATORIO",
            name="Hora extra de teste",
            event_type="overtime",
            status="published",
            effective_from=date(2026, 1, 1),
            created_by=self.user,
            approved_by=self.user,
        )

        def add_calculated_event(competency, unit, collaborator, event_type, event_date, amount, status="approved"):
            event = FieldEvent.objects.create(
                tenant=self.tenant,
                competency=competency,
                unit=unit,
                collaborator=collaborator,
                event_type=event_type,
                event_date=event_date,
                quantity=1,
                reason="Registro sintético para teste de relatório",
                status=status,
                idempotency_key=uuid.uuid4(),
                created_by=self.user,
                approved_by=self.user if status == "approved" else None,
            )
            CalculationResult.objects.create(
                tenant=self.tenant,
                competency=competency,
                event=event,
                collaborator=collaborator,
                rule=rule_overtime if event_type == "overtime" else rule_12h,
                base_amount=amount,
                factor="1",
                calculated_amount=amount,
                memory={"source": "teste"},
            )
            return event

        add_calculated_event(october, self.unit_allowed, self.person_allowed, "additional_12h", date(2026, 10, 10), "50.00")
        add_calculated_event(october, second_unit, self.person_allowed, "additional_12h", date(2026, 10, 11), "75.00")
        add_calculated_event(october, duplicate_name_unit, self.person_allowed, "additional_12h", date(2026, 10, 16), "25.00")
        add_calculated_event(september, self.unit_allowed, self.person_allowed, "overtime", date(2026, 9, 15), "100.00")
        add_calculated_event(october, self.unit_allowed, self.person_allowed, "additional_12h", date(2026, 10, 12), "500.00", status="pending")
        add_calculated_event(october, self.unit_blocked, self.person_blocked, "additional_12h", date(2026, 10, 13), "900.00")
        FieldEvent.objects.create(
            tenant=self.tenant,
            competency=october,
            unit=self.unit_allowed,
            collaborator=self.person_allowed,
            event_type="daily",
            event_date=date(2026, 10, 14),
            quantity=1,
            reason="Evento aprovado sem cálculo para testar o indicador",
            status="approved",
            idempotency_key=uuid.uuid4(),
            created_by=self.user,
            approved_by=self.user,
        )

        response = self.client.get("/relatorios/?report_type=event_costs")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["event_cost_total"], Decimal("150.00"))
        self.assertEqual(response.context["event_cost_count"], 3)
        self.assertEqual(response.context["uncalculated_event_count"], 1)
        self.assertEqual(response.context["event_cost_unit_count"], 3)
        self.assertEqual(response.context["event_cost_collaborator_count"], 1)
        self.assertEqual(response.context["variation"]["display"], "+50,0%")
        self.assertEqual([item["formatted_total"] for item in response.context["unit_chart"]], ["R$ 75,00", "R$ 50,00", "R$ 25,00"])
        self.assertEqual([item["label"] for item in response.context["trend_points"]], ["09/26", "10/26"])
        self.assertEqual(response.context["comparison_period_total"], Decimal("250.00"))
        self.assertContains(response, 'class="trend-svg"')
        self.assertContains(response, "Composição por tipo de evento")
        self.assertEqual([header["label"] for header in response.context["comparison_headers"]], ["10/2026", "09/2026"])
        self.assertEqual(response.context["comparison_totals"], [Decimal("150.00"), Decimal("100.00")])
        approved_12h_units = {
            row["unidade"]
            for row in response.context["comparison_rows"]
            if row["evento"] == "Adicional 12h" and row["status"] == "Aprovado"
        }
        self.assertEqual(len(approved_12h_units), 3)
        self.assertNotContains(response, "Unidade Bloqueada")
        self.assertNotContains(response, "R$ 500,00")
        self.assertNotContains(response, "R$ 900,00")

        company_filtered = self.client.get(f"/relatorios/?report_type=event_costs&company={other_company.id}")
        self.assertEqual(company_filtered.context["event_cost_total"], Decimal("25.00"))
        self.assertEqual(company_filtered.context["event_cost_unit_count"], 1)
        self.assertIn("Empresa Secundária Ltda.", company_filtered.context["top_unit"]["label"])
        self.assertNotContains(company_filtered, "Unidade Secundária")

        all_statuses = self.client.get("/relatorios/?report_type=event_costs&status=all")
        self.assertEqual(all_statuses.context["event_cost_total"], Decimal("650.00"))
        self.assertContains(all_statuses, "Pendente")
        self.assertEqual(all_statuses.context["uncalculated_event_count"], 1)

        all_events = self.client.get("/relatorios/?report_type=events&status=all")
        self.assertEqual(all_events.status_code, 200)
        self.assertEqual(len(all_events.context["rows"]), 6)

    def test_health_detects_event_outside_competency(self):
        UserScope.objects.create(user=self.user, tenant=self.tenant, unit=self.unit_allowed, role="dp")
        competency = Competency.objects.get(tenant=self.tenant)
        FieldEvent.objects.create(
            tenant=self.tenant,
            competency=competency,
            unit=self.unit_allowed,
            collaborator=self.person_allowed,
            event_type="daily",
            event_date=date(2026, 11, 1),
            quantity=1,
            reason="Evento fora da competência para teste",
            idempotency_key=uuid.uuid4(),
            created_by=self.user,
        )
        response = self.client.get("/saude/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(DataQualityIssue.objects.filter(issue_type="outside_competency", status="open").exists())

    def test_monthly_compensation_uses_clt_only_on_rain_days(self):
        competency = Competency.objects.get(tenant=self.tenant)
        CompensationVersion.objects.create(collaborator=self.person_allowed, company=self.company, unit=self.unit_allowed, combined_salary="5000.00", clt_salary="2316.96", effective_from=date(2026, 1, 1), reason="Regra sintética de teste", created_by=self.user)
        for day in range(1, 6):
            FieldEvent.objects.create(tenant=self.tenant, competency=competency, unit=self.unit_allowed, collaborator=self.person_allowed, event_type="rain_release", event_date=date(2026, 10, day), quantity=1, reason="Dispensa por chuva autorizada", status="approved", idempotency_key=uuid.uuid4(), created_by=self.user, approved_by=self.user)
        result = calculate_monthly_compensation(competency, self.person_allowed, self.unit_allowed)
        self.assertEqual(result.normal_days, 25)
        self.assertEqual(result.rain_days, 5)
        self.assertEqual(result.total_amount, Decimal("4552.83"))
        self.assertEqual(MonthlyCompensationResult.objects.count(), 1)
        cycle, entries = generate_monthly_entries(result, self.user)
        self.assertEqual(cycle.cycle_type, "monthly")
        self.assertEqual(PaymentCycle.objects.count(), 1)
        self.assertEqual(PaymentEntry.objects.count(), 2)
        self.assertEqual(sum((entry.amount for entry in entries), Decimal("0.00")), Decimal("4552.83"))

    def test_monthly_compensation_keeps_same_collaborator_separate_by_unit(self):
        UserScope.objects.create(user=self.user, tenant=self.tenant, unit=self.unit_allowed, role="dp")
        competency = Competency.objects.get(tenant=self.tenant)
        second_unit = Unit.objects.create(tenant=self.tenant, company=self.company, name="Unidade Secundária")
        EmploymentLink.objects.create(collaborator=self.person_allowed, company=self.company, unit=second_unit, job_title="Auxiliar", admission_date=date(2026, 1, 1))
        CompensationVersion.objects.create(collaborator=self.person_allowed, company=self.company, unit=self.unit_allowed, combined_salary="5000.00", clt_salary="2316.96", effective_from=date(2026, 1, 1), reason="Regra sintética", created_by=self.user)
        CompensationVersion.objects.create(collaborator=self.person_allowed, company=self.company, unit=second_unit, combined_salary="3000.00", clt_salary="2000.00", effective_from=date(2026, 1, 1), reason="Regra sintética", created_by=self.user)

        first_result = calculate_monthly_compensation(competency, self.person_allowed, self.unit_allowed)
        second_result = calculate_monthly_compensation(competency, self.person_allowed, second_unit)
        cycle, first_entries = generate_monthly_entries(first_result, self.user)
        _, second_entries = generate_monthly_entries(second_result, self.user)

        self.assertEqual(MonthlyCompensationResult.objects.count(), 2)
        self.assertEqual(first_result.total_amount, Decimal("5000.00"))
        self.assertEqual(second_result.total_amount, Decimal("3000.00"))
        self.assertEqual(PaymentEntry.objects.filter(cycle=cycle).count(), 2)
        self.assertEqual(first_entries[0].unit, self.unit_allowed)
        self.assertEqual(second_entries[0].unit, second_unit)
        self.assertEqual(first_entries[0].amount, Decimal("5000.00"))
        self.assertEqual(second_entries[0].amount, Decimal("3000.00"))
        UserScope.objects.create(user=self.user, tenant=self.tenant, unit=second_unit, role="leader")
        report_response = self.client.get("/relatorios/?report_type=monthly")
        self.assertEqual(report_response.status_code, 200)
        self.assertEqual({row["unidade"] for row in report_response.context["rows"]}, {"Unidade Permitida", "Unidade Secundária"})

    def test_manual_event_rejects_collaborator_without_link_to_selected_unit(self):
        second_unit = Unit.objects.create(tenant=self.tenant, company=self.company, name="Unidade Secundária")
        UserScope.objects.create(user=self.user, tenant=self.tenant, unit=second_unit, role="leader")

        response = self.client.post("/lancamentos/novo/", {
            "unit": second_unit.id,
            "collaborator": self.person_allowed.id,
            "event_type": "daily",
            "event_date": "2026-10-20",
            "quantity": "1",
            "reason": "Lançamento de teste",
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(FieldEvent.objects.count(), 0)
        self.assertTrue(response.context["form"].has_error("collaborator"))

    def test_manual_event_rejects_date_from_closed_competency(self):
        october = Competency.objects.get(tenant=self.tenant)
        october.status = "closed"
        october.save(update_fields=["status"])
        Competency.objects.create(tenant=self.tenant, year=2026, month=11, status="open")

        response = self.client.post("/lancamentos/novo/", {
            "unit": self.unit_allowed.id,
            "collaborator": self.person_allowed.id,
            "event_type": "daily",
            "event_date": "2026-10-28",
            "quantity": "1",
            "reason": "Lançamento atrasado de teste",
        })

        self.assertEqual(response.status_code, 200)
        self.assertIn("event_date", response.context["form"].errors)
        self.assertEqual(FieldEvent.objects.count(), 0)

    def test_field_app_requires_unit_selection_for_multi_unit_user(self):
        second_unit = Unit.objects.create(tenant=self.tenant, company=self.company, name="Unidade Secundária")
        EmploymentLink.objects.create(collaborator=self.person_allowed, company=self.company, unit=second_unit, job_title="Auxiliar", admission_date=date(2026, 1, 1))
        UserScope.objects.create(user=self.user, tenant=self.tenant, unit=second_unit, role="leader")

        empty_response = self.client.get("/campo/")
        selected_response = self.client.get(f"/campo/?unit={second_unit.id}")

        self.assertEqual(empty_response.status_code, 200)
        self.assertContains(empty_response, "Selecione uma unidade para iniciar")
        self.assertContains(empty_response, 'unitId:""')
        self.assertContains(selected_response, "Unidade Secundária")
        self.assertContains(selected_response, f'unitId:"{second_unit.id}"')
        self.assertContains(selected_response, "Pessoa Permitida")
        self.assertNotContains(selected_response, "Pessoa Bloqueada")

    def test_closing_requires_approved_cycles_and_reopening_unlocks_them(self):
        competency = Competency.objects.get(tenant=self.tenant)
        competency.status = "review"
        competency.save(update_fields=["status"])
        CompensationVersion.objects.create(collaborator=self.person_allowed, company=self.company, unit=self.unit_allowed, combined_salary="5000.00", clt_salary="2316.96", effective_from=date(2026, 1, 1), reason="Regra sintética", created_by=self.user)
        CalculationRule.objects.create(tenant=self.tenant, code="ADICIONAL_12H", version=1, name="Adicional 12h", event_type="additional_12h", status="published", parameters={"amount": "50.00"}, effective_from=date(2026, 1, 1), created_by=self.user, approved_by=self.user)
        event = FieldEvent.objects.create(tenant=self.tenant, competency=competency, unit=self.unit_allowed, collaborator=self.person_allowed, event_type="additional_12h", event_date=date(2026, 10, 20), quantity=1, reason="Permanência extraordinária", status="approved", idempotency_key=uuid.uuid4(), created_by=self.user, approved_by=self.user)
        calculate_event(event)
        monthly_result = calculate_monthly_compensation(competency, self.person_allowed, self.unit_allowed)
        monthly_cycle, _ = generate_monthly_entries(monthly_result, self.user)
        day10_cycle, _ = generate_day10_entries(competency, self.user)
        manager = User.objects.create_user(username="manager", password="senha-teste")
        UserScope.objects.create(user=manager, tenant=self.tenant, unit=self.unit_allowed, role="management")
        self.client.force_login(manager)

        self.client.post(f"/fechamento/{competency.id}/close/", {"reason": "Conferência final"})
        competency.refresh_from_db()
        self.assertEqual(competency.status, "review")

        self.assertEqual(self.client.get(f"/pagamentos/{monthly_cycle.id}/aprovar/").status_code, 405)
        for cycle in (monthly_cycle, day10_cycle):
            response = self.client.post(f"/pagamentos/{cycle.id}/aprovar/", {"reason": "Valores conferidos"})
            self.assertEqual(response.status_code, 302)
            cycle.refresh_from_db()
            self.assertEqual(cycle.status, "approved")
            self.assertFalse(cycle.entries.exclude(status="approved").exists())

        self.client.post(f"/fechamento/{competency.id}/close/", {"reason": "Conferência final"})
        competency.refresh_from_db()
        self.assertEqual(competency.status, "closed")

        self.client.post(f"/fechamento/{competency.id}/reopen/", {"reason": "Correção autorizada"})
        competency.refresh_from_db()
        self.assertEqual(competency.status, "review")
        self.assertFalse(PaymentCycle.objects.filter(competency=competency).exclude(status="draft").exists())
        self.assertFalse(PaymentEntry.objects.filter(cycle__competency=competency).exclude(status="draft").exists())

    def test_additional_12h_generates_day10_entry(self):
        competency = Competency.objects.get(tenant=self.tenant)
        CalculationRule.objects.create(tenant=self.tenant, code="ADICIONAL_12H", version=1, name="Adicional 12h", event_type="additional_12h", status="published", parameters={"amount": "50.00"}, effective_from=date(2026, 1, 1), created_by=self.user, approved_by=self.user)
        event = FieldEvent.objects.create(tenant=self.tenant, competency=competency, unit=self.unit_allowed, collaborator=self.person_allowed, event_type="additional_12h", event_date=date(2026, 10, 20), quantity=1, reason="Permanência extraordinária combinada", status="approved", idempotency_key=uuid.uuid4(), created_by=self.user, approved_by=self.user)
        result = calculate_event(event)
        cycle, entries = generate_day10_entries(competency, self.user)
        self.assertEqual(result.calculated_amount, Decimal("50.00"))
        self.assertEqual(cycle.cycle_type, "day10")
        self.assertEqual(entries[0].amount, Decimal("50.00"))

    def test_import_workbook_creates_only_preview_batch(self):
        UserScope.objects.create(user=self.user, tenant=self.tenant, unit=self.unit_allowed, role="dp")
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Folha mensal"
        sheet.append(["EMPRESA: Cliente Teste Ltda."])
        sheet.append(["CNPJ: 11.111.111/0001-11"])
        sheet.append(["COMPETÊNCIA: 10/2026"])
        sheet.append([])
        sheet.append(["n", "Funcionario", "Empresa", "Unidade", "Sal. Combinado"])
        sheet.append([1, "Pessoa Permitida", "Cliente Teste Ltda.", "Unidade Permitida", 5000])
        buffer = BytesIO()
        workbook.save(buffer)
        self.client.force_login(self.user)
        response = self.client.post("/importacao/", {"file": SimpleUploadedFile("folha_teste.xlsx", buffer.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
        self.assertEqual(response.status_code, 200)
        batch = ImportBatch.objects.get()
        self.assertEqual(batch.status, "preview")
        self.assertEqual(batch.sheet_name, "Folha mensal")
        self.assertEqual(batch.header_row, 5)
        self.assertEqual(batch.company, self.company)
        self.assertEqual(batch.competency.month, 10)
        self.assertEqual(batch.detected["matched_rows"], 1)
        self.assertEqual(batch.errors, [])
        self.assertEqual(batch.validation_rows[0]["status"], "matched")
        self.assertEqual(batch.validation_rows[0]["row"], 6)
        self.assertEqual(batch.preview[0]["Funcionario"], "Pessoa Permitida")
        self.assertEqual(FieldEvent.objects.count(), 0)

    def test_import_payroll_pdf_reconciles_totals_without_creating_entries(self):
        UserScope.objects.create(user=self.user, tenant=self.tenant, unit=self.unit_allowed, role="dp")
        competency = Competency.objects.get(tenant=self.tenant)
        collaborator = Collaborator.objects.create(tenant=self.tenant, name="Pessoa PDF", employee_code="001")
        EmploymentLink.objects.create(
            collaborator=collaborator,
            company=self.company,
            unit=self.unit_allowed,
            job_title="Auxiliar",
            admission_date=date(2026, 1, 1),
        )
        cycle = PaymentCycle.objects.create(
            tenant=self.tenant,
            competency=competency,
            cycle_type="monthly",
            created_by=self.user,
        )
        earnings_rubric = Rubric.objects.create(
            tenant=self.tenant,
            code="TEST_EARNING",
            name="Provento de teste",
            category="earning",
            cycle_type="monthly",
            effective_from=date(2026, 1, 1),
            created_by=self.user,
        )
        deduction_rubric = Rubric.objects.create(
            tenant=self.tenant,
            code="TEST_DEDUCTION",
            name="Desconto de teste",
            category="deduction",
            cycle_type="monthly",
            effective_from=date(2026, 1, 1),
            created_by=self.user,
        )
        PaymentEntry.objects.create(
            tenant=self.tenant,
            cycle=cycle,
            collaborator=collaborator,
            unit=self.unit_allowed,
            rubric=earnings_rubric,
            amount="100.00",
            created_by=self.user,
        )
        PaymentEntry.objects.create(
            tenant=self.tenant,
            cycle=cycle,
            collaborator=collaborator,
            unit=self.unit_allowed,
            rubric=deduction_rubric,
            amount="10.00",
            created_by=self.user,
        )
        pdf_buffer = BytesIO()
        document = canvas.Canvas(pdf_buffer)
        lines = [
            "Empresa: 239 - Cliente Teste Ltda. Página: 1/1",
            "CNPJ: 11.111.111/0001-11 Emissão: 05/10/2026",
            "Competência: 10/2026",
            "Empr.: 001 Pessoa PDF Situação: Trabalhando CPF: 000.000.000-00 Adm: 01/01/2026",
            "ND: 0 Proventos: 100,00 Descontos: 10,00 Informativa: 0,00 Informativa Dedutora: 0 Líquido: 90,00",
        ]
        for line_number, line in enumerate(lines):
            document.drawString(40, 800 - line_number * 20, line)
        document.save()

        self.client.force_login(self.user)
        response = self.client.post(
            "/importacao/",
            {
                "file": SimpleUploadedFile(
                    "folha_teste.pdf",
                    pdf_buffer.getvalue(),
                    content_type="application/pdf",
                )
            },
        )
        self.assertEqual(response.status_code, 200)
        batch = ImportBatch.objects.get()
        self.assertEqual(batch.status, "preview", batch.errors)
        self.assertEqual(batch.detected["source_format"], "PDF")
        self.assertEqual(batch.company, self.company)
        self.assertEqual(batch.competency, competency)
        self.assertEqual(batch.validation_rows[0]["status"], "reconciled")
        self.assertEqual(batch.validation_rows[0]["net_difference"], "0.00")
        self.assertEqual(batch.detected["summary"]["matched_count"], 1)
        self.assertEqual(PaymentEntry.objects.count(), 2)
        self.assertEqual(FieldEvent.objects.count(), 0)

    def test_admission_generates_secure_access_and_saves_candidate_data(self):
        UserScope.objects.create(user=self.user, tenant=self.tenant, unit=self.unit_allowed, role="dp")
        response = self.client.post("/admissoes/nova/", {"company": self.company.id, "unit": self.unit_allowed.id, "candidate_name": "Candidato Teste", "candidate_phone": "41999999999", "job_title": "Auxiliar", "expected_admission_date": "2026-11-01"})
        self.assertEqual(response.status_code, 200)
        admission = AdmissionRequest.objects.get()
        self.assertEqual(admission.status, "in_progress")
        self.assertContains(response, "Chave de acesso")
        access_key = response.context["access_key"]
        public_url = f"/admissao/preencher/{admission.token}/"
        self.assertEqual(self.client.get(public_url).status_code, 200)
        access = self.client.post(public_url, {"chave": access_key})
        self.assertEqual(access.status_code, 302)
        submitted = self.client.post(public_url, {"full_name": "Candidato Teste", "cpf": "12345678900", "birth_date": "1995-05-10", "social_name": "", "email": "candidato@example.com", "address": "Rua Teste, 10", "emergency_contact": "Contato (41) 98888-8888", "action": "submit"})
        self.assertEqual(submitted.status_code, 200)
        admission.refresh_from_db()
        self.assertEqual(admission.status, "submitted")
        self.assertEqual(admission.field_values.count(), 23)
        self.assertTrue(admission.field_values.filter(field__code="mother_name").exists())
        self.assertTrue(admission.field_values.filter(field__code="postal_code").exists())
        self.assertTrue(admission.field_values.filter(field__code="employment_type").exists())
        self.assertTrue(admission.field_values.filter(field__code="emergency_phone").exists())
        self.client.post(public_url, {"full_name": "Alteração indevida", "cpf": "12345678900", "birth_date": "1995-05-10", "action": "save"})
        self.assertEqual(admission.field_values.get(field__code="full_name").value, "Candidato Teste")
        self.assertEqual(self.client.get(f"/admissoes/{admission.id}/approve/").status_code, 405)
