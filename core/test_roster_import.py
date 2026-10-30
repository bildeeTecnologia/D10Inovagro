from io import BytesIO
from datetime import date

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from openpyxl import Workbook

from .models import Collaborator, Company, EmploymentLink, RosterImportBatch, Tenant, Unit, UserScope
from .importer import validate_payroll_pdf


class RosterImportTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Tenant Roster", slug="tenant-roster")
        self.company = Company.objects.create(tenant=self.tenant, legal_name="Empresa Teste Ltda.", cnpj="11.111.111/0001-11")
        self.user = User.objects.create_user(username="dp-roster", password="test-password")
        UserScope.objects.create(user=self.user, tenant=self.tenant, company=self.company, role="dp")
        self.client.force_login(self.user)

    def make_file(self, rows):
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Vinculos"
        sheet.append([
            "CNPJ da empresa", "Unidade", "Nome do colaborador", "CPF",
            "Matrícula no vínculo", "Cargo/função", "Data de admissão", "Data de desligamento",
        ])
        for row in rows:
            sheet.append(row)
        buffer = BytesIO()
        workbook.save(buffer)
        return SimpleUploadedFile(
            "carga.xlsx",
            buffer.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    def test_download_model_and_import_same_cpf_into_two_units(self):
        template = self.client.get("/importacao/cadastro/modelo.xlsx")
        self.assertEqual(template.status_code, 200)
        self.assertIn("Modelo_Carga_Cadastral.xlsx", template["Content-Disposition"])

        uploaded = self.make_file([
            [self.company.cnpj, "Unidade Norte", "Pessoa Exemplo", "529.982.247-25", "A-10", "Auxiliar", "01/01/2024", ""],
            [self.company.cnpj, "Unidade Sul", "Pessoa Exemplo", "529.982.247-25", "B-20", "Operador", "01/01/2024", ""],
        ])
        preview = self.client.post("/importacao/cadastro/", {"file": uploaded})
        self.assertEqual(preview.status_code, 200)
        batch = RosterImportBatch.objects.get()
        self.assertEqual(batch.detected["person_count"], 1)
        self.assertEqual(batch.detected["unit_count"], 2)
        self.assertEqual(batch.detected["ready_count"], 2)
        self.assertEqual(batch.errors, [])
        self.assertNotIn("52998224725", str(batch.preview))

        response = self.client.post(f"/importacao/cadastro/{batch.id}/confirmar/")
        self.assertEqual(response.status_code, 302)
        person = Collaborator.objects.get(tenant=self.tenant, cpf_fingerprint__gt="")
        links = EmploymentLink.objects.filter(collaborator=person).order_by("unit__name")
        self.assertEqual(links.count(), 2)
        self.assertEqual({link.employee_code for link in links}, {"A-10", "B-20"})
        self.assertEqual(Unit.objects.filter(company=self.company).count(), 2)
        batch.refresh_from_db()
        self.assertEqual(batch.status, "confirmed")
        self.assertEqual(batch.validation_rows, [])

    def test_invalid_cpf_blocks_batch_without_creating_records(self):
        uploaded = self.make_file([
            [self.company.cnpj, "Unidade Norte", "Pessoa Exemplo", "123.456.789-00", "", "Auxiliar", "01/01/2024", ""],
        ])
        preview = self.client.post("/importacao/cadastro/", {"file": uploaded})
        self.assertEqual(preview.status_code, 200)
        batch = RosterImportBatch.objects.get()
        self.assertTrue(batch.errors)
        self.assertIn("CPF inválido", " ".join(batch.errors))
        self.client.post(f"/importacao/cadastro/{batch.id}/confirmar/")
        self.assertEqual(Collaborator.objects.filter(tenant=self.tenant).count(), 0)
        self.assertEqual(Unit.objects.filter(company=self.company).count(), 0)

    def test_payroll_pdf_matches_code_stored_on_company_unit_employment_link(self):
        competency = self.tenant.competencies.create(year=2026, month=10)
        collaborator = Collaborator.objects.create(tenant=self.tenant, name="Pessoa Exemplo", employee_code="")
        unit = Unit.objects.create(tenant=self.tenant, company=self.company, name="Unidade Norte")
        EmploymentLink.objects.create(
            collaborator=collaborator,
            company=self.company,
            unit=unit,
            employee_code="REG-0042",
            job_title="Auxiliar",
            admission_date=date(2024, 1, 1),
        )
        inspection = {
            "metadata": {"cnpj": self.company.cnpj, "month": 10, "year": 2026},
            "errors": [],
            "detected": {"row_count": 1},
            "employees": [{
                "employee_code": "REG-0042",
                "employee": "Pessoa Exemplo",
                "status": "pending",
                "pdf_earnings": "100.00",
                "pdf_deductions": "0.00",
                "pdf_net": "100.00",
            }],
        }
        result = validate_payroll_pdf(inspection, self.tenant)
        self.assertEqual(result["validation_rows"][0]["status"], "no_cycle")
