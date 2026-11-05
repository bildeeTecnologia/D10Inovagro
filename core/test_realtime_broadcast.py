import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .models import Company, Competency, Tenant, Unit, UserScope


class ConferenceRealtimeTokenTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Tenant RT", slug="tenant-rt")
        self.company = Company.objects.create(
            tenant=self.tenant,
            legal_name="Empresa RT Ltda.",
            cnpj="12.345.678/0001-90",
        )
        self.allowed_unit = Unit.objects.create(tenant=self.tenant, company=self.company, name="Permitida")
        self.other_unit = Unit.objects.create(tenant=self.tenant, company=self.company, name="Fora do escopo")
        self.competency = Competency.objects.create(tenant=self.tenant, year=2026, month=10, status="open")
        self.user = User.objects.create_user(username="dp-rt", password="test-password")
        UserScope.objects.create(user=self.user, tenant=self.tenant, unit=self.allowed_unit, role="dp")
        self.client = Client()
        self.client.force_login(self.user)
        self.private_key = ec.generate_private_key(ec.SECP256R1())
        self.private_pem = self.private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("ascii")
        self.public_key = self.private_key.public_key()

    @override_settings(
        SUPABASE_REALTIME_URL="https://project-ref.supabase.co",
        SUPABASE_PUBLISHABLE_KEY="sb_publishable_test_only",
        SUPABASE_REALTIME_SIGNING_PRIVATE_KEY="",
        SUPABASE_REALTIME_SIGNING_KEY_ID="test-key-id",
        SUPABASE_REALTIME_ISSUER="https://project-ref.supabase.co/auth/v1",
    )
    def test_missing_signing_key_disables_realtime_without_exposing_details(self):
        response = self.client.get(reverse("conference_realtime_token"), {"competency": self.competency.pk})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        self.assertNotContains(response, "private_key", status_code=503)

    @override_settings(
        SUPABASE_REALTIME_URL="https://project-ref.supabase.co",
        SUPABASE_PUBLISHABLE_KEY="sb_publishable_test_only",
        SUPABASE_REALTIME_SIGNING_PRIVATE_KEY="",
        SUPABASE_REALTIME_SIGNING_KEY_ID="test-key-id",
        SUPABASE_REALTIME_ISSUER="https://project-ref.supabase.co/auth/v1",
    )
    def test_only_review_roles_can_request_a_channel_token(self):
        leader = User.objects.create_user(username="leader-rt", password="test-password")
        UserScope.objects.create(user=leader, tenant=self.tenant, unit=self.allowed_unit, role="leader")
        client = Client()
        client.force_login(leader)
        response = client.get(reverse("conference_realtime_token"), {"competency": self.competency.pk})
        self.assertEqual(response.status_code, 403)

    @override_settings(
        SUPABASE_REALTIME_URL="https://project-ref.supabase.co",
        SUPABASE_PUBLISHABLE_KEY="sb_publishable_test_only",
        SUPABASE_REALTIME_SIGNING_PRIVATE_KEY="",
        SUPABASE_REALTIME_SIGNING_KEY_ID="test-key-id",
        SUPABASE_REALTIME_ISSUER="https://project-ref.supabase.co/auth/v1",
    )
    def test_token_is_short_lived_and_limited_to_authorized_unit_competency(self):
        from django.test import override_settings as settings_override

        with settings_override(SUPABASE_REALTIME_SIGNING_PRIVATE_KEY=self.private_pem):
            response = self.client.get(reverse("conference_realtime_token"), {"competency": self.competency.pk})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "private, no-store")
        body = response.json()
        claims = jwt.decode(
            body["token"],
            self.public_key,
            algorithms=["ES256"],
            issuer="https://project-ref.supabase.co/auth/v1",
        )
        self.assertEqual(claims["role"], "authenticated")
        self.assertEqual(claims["tenant_id"], str(self.tenant.pk))
        self.assertEqual(claims["unit_ids"], [self.allowed_unit.pk])
        self.assertEqual(claims["competency_id"], str(self.competency.pk))
        self.assertLessEqual(claims["exp"] - claims["iat"], 300)
        self.assertEqual(len(body["topics"]), 1)
        self.assertIn(f":unit:{self.allowed_unit.pk}:", body["topics"][0])
        self.assertNotIn(str(self.other_unit.pk), body["topics"][0])
        self.assertNotIn("BEGIN PRIVATE KEY", str(body))

    def test_requested_unit_outside_scope_is_rejected(self):
        response = self.client.get(reverse("conference_realtime_token"), {
            "competency": self.competency.pk,
            "unit": self.other_unit.pk,
        })
        self.assertEqual(response.status_code, 403)
