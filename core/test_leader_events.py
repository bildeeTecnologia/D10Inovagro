import json
import uuid
from datetime import date

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import (
    AuditLog, Collaborator, Company, Competency, EmploymentLink, EventTypeSetting, FieldEvent,
    Rubric, RubricApplication, Tenant, Unit, UserScope,
)


class LeaderEventReleaseTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Liberação teste", slug="liberacao-teste")
        self.company = Company.objects.create(tenant=self.tenant, legal_name="Empresa liberação", cnpj="44.444.444/0001-44")
        self.unit = Unit.objects.create(tenant=self.tenant, company=self.company, name="Unidade A")
        self.other_unit = Unit.objects.create(tenant=self.tenant, company=self.company, name="Unidade B")
        self.person = Collaborator.objects.create(tenant=self.tenant, name="Pessoa A", employee_code="L-1")
        EmploymentLink.objects.create(
            collaborator=self.person, company=self.company, unit=self.unit, job_title="Auxiliar", admission_date=date(2026, 1, 1),
        )
        self.competency = Competency.objects.create(tenant=self.tenant, year=2026, month=10)
        self.dp = User.objects.create_user(username="dp-liberacao")
        UserScope.objects.create(user=self.dp, tenant=self.tenant, role="platform")
        self.leader = User.objects.create_user(username="lider-liberacao")
        UserScope.objects.create(user=self.leader, tenant=self.tenant, role="leader", unit=self.unit)

    def sync(self, event_type):
        payload = {"events": [{
            "client_id": "c1", "idempotency_key": str(uuid.uuid4()), "unit_id": self.unit.id,
            "collaborator_id": self.person.id, "event_type": event_type, "event_date": "2026-10-10",
            "quantity": "1", "reason": "Lançamento de teste",
        }]}
        return self.client.post("/api/v1/events/sync/", json.dumps(payload), content_type="application/json").json()

    def test_field_app_shows_only_released_fixed_events(self):
        EventTypeSetting.objects.create(tenant=self.tenant, event_type="holiday", leader_available=False)
        self.client.force_login(self.leader)
        page = self.client.get(reverse("field_app"))
        self.assertContains(page, 'data-event-type="daily"')
        self.assertContains(page, 'data-event-type="rain_release"')
        self.assertNotContains(page, 'data-event-type="holiday"')

    def test_blocked_event_is_rejected_for_leaders_but_not_for_office(self):
        EventTypeSetting.objects.create(tenant=self.tenant, event_type="daily", leader_available=False)
        self.client.force_login(self.leader)
        result = self.sync("daily")
        self.assertEqual(len(result["errors"]), 1)
        self.assertIn("não está liberado", result["errors"][0]["reason"])
        self.assertFalse(FieldEvent.objects.filter(event_type="daily").exists())
        self.assertEqual(len(self.sync("overtime")["synced"]), 1)

        UserScope.objects.create(user=self.leader, tenant=self.tenant, role="dp")
        self.client.force_login(User.objects.get(pk=self.leader.pk))
        self.assertEqual(len(self.sync("daily")["synced"]), 1)

    def test_dp_toggles_release_and_leader_cannot(self):
        url = reverse("event_type_release", args=["sunday"])
        self.client.force_login(self.leader)
        self.assertEqual(self.client.post(url, {"leader_available": "0"}).status_code, 403)
        self.client.force_login(self.dp)
        self.assertRedirects(self.client.post(url, {"leader_available": "0"}), reverse("rule_list"), fetch_redirect_response=False)
        self.assertFalse(EventTypeSetting.objects.get(tenant=self.tenant, event_type="sunday").leader_available)
        self.assertTrue(AuditLog.objects.filter(entity="event_type_setting", action="update").exists())
        self.assertEqual(self.client.post(reverse("event_type_release", args=["nope"]), {"leader_available": "0"}).status_code, 400)
        self.client.post(url, {"leader_available": "1"})
        self.assertTrue(EventTypeSetting.objects.get(tenant=self.tenant, event_type="sunday").leader_available)

    def test_single_screen_creates_approved_bonus_for_several_units_and_shows_it_to_leaders(self):
        self.client.force_login(self.dp)
        page = self.client.get(reverse("rule_list"))
        self.assertContains(page, "1. Eventos do app do líder")
        self.assertContains(page, "Nova bonificação")
        data = {
            "name": "Meta de produtividade", "mode": "cumulative", "amount": "50.00", "cycle_type": "day10",
            "units": [self.unit.id, self.other_unit.id], "effective_from": "2026-01-01",
            "leader_available": "on", "instructions": "Registrar cada meta atingida.",
            "reason": "Bonificação definida pelo DP", "approve_now": "on",
        }
        response = self.client.post(reverse("bonus_create"), data)
        self.assertRedirects(response, reverse("rule_list"), fetch_redirect_response=False)
        rubric = Rubric.objects.get(tenant=self.tenant, name="Meta de produtividade")
        self.assertEqual(rubric.code, "META_DE_PRODUTIVIDADE")
        apps = RubricApplication.objects.filter(rubric=rubric)
        self.assertEqual(apps.count(), 2)
        self.assertTrue(all(app.status == "approved" and app.leader_available for app in apps))

        self.client.force_login(self.leader)
        self.assertContains(self.client.get(reverse("field_app")), "Meta de produtividade")

        self.client.force_login(self.dp)
        duplicate = self.client.post(reverse("bonus_create"), data)
        self.assertEqual(duplicate.status_code, 400)
        self.assertEqual(Rubric.objects.filter(tenant=self.tenant, name="Meta de produtividade").count(), 1)

        app = apps.get(unit=self.unit)
        self.client.post(reverse("application_leader_release", args=[app.pk]), {"leader_available": "0"})
        app.refresh_from_db()
        self.assertFalse(app.leader_available)
        self.client.force_login(self.leader)
        self.assertNotContains(self.client.get(reverse("field_app")), f"data-application-id=\"{app.pk}\"")
