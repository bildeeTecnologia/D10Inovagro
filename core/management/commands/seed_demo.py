from datetime import date
import uuid

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from core.models import CalculationRule, Collaborator, Company, CompensationVersion, Competency, EmploymentLink, FieldEvent, Tenant, Unit, UserScope
from core.compensation import calculate_monthly_compensation
from core.payments import generate_monthly_entries


class Command(BaseCommand):
    help = "Cria dados sintéticos para validar o primeiro incremento do Fechamento de Campo."

    def handle(self, *args, **options):
        user, created = User.objects.get_or_create(username="demo", defaults={"email": "demo@example.com"})
        if created or not user.check_password("demo12345"):
            user.set_password("demo12345")
        user.first_name = "Área de Pessoas"
        user.is_staff = True
        user.is_superuser = True
        user.save()

        tenant, _ = Tenant.objects.get_or_create(slug="grupo-agricola-demo", defaults={"name": "Grupo Agrícola Demo"})
        company, _ = Company.objects.get_or_create(
            tenant=tenant, cnpj="00.000.000/0001-00", defaults={"legal_name": "Agrícola Demo Ltda."}
        )
        unit, _ = Unit.objects.get_or_create(
            tenant=tenant,
            company=company,
            name="Fazenda Santa Rita",
            defaults={"region": "Interior de São Paulo", "final_customer": "Cliente Piloto"},
        )
        UserScope.objects.filter(user=user, tenant=tenant, role="dp", unit__isnull=True).delete()
        UserScope.objects.get_or_create(user=user, tenant=tenant, role="dp", company=company, unit=unit)
        competency, _ = Competency.objects.get_or_create(tenant=tenant, year=2026, month=10, defaults={"status": "review"})
        CalculationRule.objects.get_or_create(tenant=tenant, code="ADICIONAL_12H", version=1, defaults={"name": "Adicional 12h", "event_type": "additional_12h", "status": "published", "parameters": {"amount": "50.00"}, "effective_from": date(2026, 1, 1), "approval_reason": "Regra sintética de demonstração", "created_by": user, "approved_by": user})

        demo_people = [
            ("João da Silva", "Auxiliar agrícola", date(2026, 1, 10)),
            ("Maria Souza", "Operadora de máquinas", date(2026, 2, 3)),
            ("Carlos Oliveira", "Líder de equipe", date(2025, 8, 18)),
        ]
        for index, (name, job_title, admission_date) in enumerate(demo_people, start=1):
            collaborator, _ = Collaborator.objects.get_or_create(
                tenant=tenant,
                employee_code=f"DEMO-{index:03d}",
                defaults={"name": name, "cpf_masked": "***.***.**0-0" + str(index)},
            )
            EmploymentLink.objects.get_or_create(
                collaborator=collaborator,
                company=company,
                unit=unit,
                defaults={"job_title": job_title, "admission_date": admission_date},
            )
            CompensationVersion.objects.get_or_create(
                collaborator=collaborator,
                company=company,
                unit=unit,
                effective_from=date(2026, 1, 1),
                defaults={"combined_salary": "5000.00", "clt_salary": "2316.96", "reason": "Valores sintéticos de demonstração", "created_by": user},
            )
            if index == 1:
                FieldEvent.objects.get_or_create(
                    tenant=tenant, competency=competency, unit=unit, collaborator=collaborator,
                    event_type="rain_release", event_date=date(2026, 10, 14),
                    defaults={"quantity": 1, "reason": "Dispensa por chuva sintética de demonstração", "status": "approved", "idempotency_key": uuid.uuid4(), "created_by": user, "approved_by": user},
                )
            result = calculate_monthly_compensation(competency, collaborator, unit)
            generate_monthly_entries(result, user)

        self.stdout.write(self.style.SUCCESS("Dados sintéticos criados. Use demo / demo12345 para entrar."))

