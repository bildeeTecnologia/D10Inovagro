from datetime import date

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from core.models import CalculationRule, Collaborator, Company, CompensationVersion, Competency, EmploymentLink, Tenant, Unit, UserScope


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
        Competency.objects.get_or_create(tenant=tenant, year=2026, month=10, defaults={"status": "review"})
        CalculationRule.objects.get_or_create(tenant=tenant, code="ADICIONAL_12H", version=1, defaults={"name": "Adicional 12h", "event_type": "additional_12h", "status": "published", "parameters": {"amount": "50.00"}, "effective_from": date(2026, 1, 1), "approval_reason": "Regra sintética de demonstração", "created_by": user, "approved_by": user})

        for index, name in enumerate(["João da Silva", "Maria Souza", "Carlos Oliveira"], start=1):
            collaborator, _ = Collaborator.objects.get_or_create(
                tenant=tenant,
                employee_code=f"DEMO-{index:03d}",
                defaults={"name": name, "cpf_masked": "***.***.***-**"},
            )
            EmploymentLink.objects.get_or_create(
                collaborator=collaborator,
                company=company,
                unit=unit,
                defaults={"job_title": "Auxiliar agrícola", "admission_date": date(2026, 1, 10)},
            )
            CompensationVersion.objects.get_or_create(
                collaborator=collaborator,
                company=company,
                unit=unit,
                effective_from=date(2026, 1, 1),
                defaults={"combined_salary": "5000.00", "clt_salary": "2316.96", "reason": "Valores sintéticos de demonstração", "created_by": user},
            )

        self.stdout.write(self.style.SUCCESS("Dados sintéticos criados. Use demo / demo12345 para entrar."))
