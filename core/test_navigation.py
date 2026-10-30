from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import Company, Tenant, Unit, UserScope
from .navigation import AREAS


class WorkspaceNavigationTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(name="Cliente Navegação", slug="navigation")
        company = Company.objects.create(tenant=self.tenant, legal_name="Empresa Teste", cnpj="11.111.111/0001-11")
        unit = Unit.objects.create(tenant=self.tenant, company=company, name="Unidade Teste")
        self.user = User.objects.create_user(username="navigation-dp", password="test-password")
        self.scope = UserScope.objects.create(user=self.user, tenant=self.tenant, unit=unit, role="dp")
        self.client.force_login(self.user)

    def test_sidebar_has_at_most_six_primary_links_and_no_nested_tools(self):
        for path in ["/", "/areas/pessoas/", "/areas/operacao/", "/areas/fechamento/"]:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                sidebar = response.content.decode().split('aria-label="Navegação principal">')[1].split("</nav>")[0]
                self.assertEqual(sidebar.count("<a "), 6)
                for target in ["/", "/areas/pessoas/", "/areas/operacao/", "/areas/fechamento/", "/relatorios/", "/configuracoes/"]:
                    self.assertIn(f'href="{target}"', sidebar)
                for area in AREAS.values():
                    for tool in area["tools"]:
                        self.assertNotIn(f'href="{reverse(tool["route"])}"', sidebar)

    def test_every_existing_tool_is_reachable_with_help_and_example(self):
        for slug, area in AREAS.items():
            response = self.client.get(f"/areas/{slug}/")
            with self.subTest(area=slug):
                self.assertContains(response, "Por onde começar?")
                self.assertContains(response, area["guidance"])
                self.assertContains(response, "Exemplo de uso", count=len(area["tools"]))
                for tool in area["tools"]:
                    self.assertContains(response, f'href="{reverse(tool["route"])}"')
                    self.assertContains(response, tool["description"])
                    self.assertContains(response, tool["example"])
                    self.assertEqual(self.client.get(reverse(tool["route"])).status_code, 200)

    def test_child_pages_highlight_parent_and_offer_return_link(self):
        paths = {
            "/importacao/cadastro/": "pessoas", "/admissoes/": "pessoas",
            "/lancamentos/novo/": "operacao", "/campo/": "operacao",
            "/calendario/": "operacao", "/comunicacao/": "operacao",
            "/regras/": "fechamento", "/conferencia/": "fechamento",
            "/importacao/": "fechamento", "/pagamentos/": "fechamento",
            "/fechamento/": "fechamento", "/saude/": "fechamento",
        }
        for path, slug in paths.items():
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertContains(response, f'href="/areas/{slug}/" class="nav-link active" aria-current="page"')
                self.assertContains(response, f"Voltar para {AREAS[slug]['title']}")

    def test_leader_keeps_simple_navigation_and_cannot_open_office_hubs(self):
        self.scope.role = "leader"
        self.scope.save()
        response = self.client.get("/campo/")
        self.assertContains(response, 'aria-label="Navegação do líder"')
        self.assertNotContains(response, 'aria-label="Navegação principal"')
        self.assertNotContains(response, "/areas/")
        for slug in AREAS:
            self.assertEqual(self.client.get(f"/areas/{slug}/").status_code, 403)

    def test_finance_sees_only_permitted_tools(self):
        self.scope.role = "finance"
        self.scope.save()
        response = self.client.get("/areas/fechamento/")
        for route in ["payment_cycles", "closing", "health_dashboard"]:
            self.assertContains(response, f'href="{reverse(route)}"')
        for route in ["rule_list", "conference", "import_workbook"]:
            self.assertNotContains(response, f'href="{reverse(route)}"')
        self.assertEqual(self.client.get("/areas/pessoas/").status_code, 403)

    def test_anonymous_and_no_scope_cannot_access_hubs(self):
        self.scope.delete()
        for slug in AREAS:
            self.assertEqual(self.client.get(f"/areas/{slug}/").status_code, 403)
        self.client.logout()
        self.assertRedirects(
            self.client.get("/areas/operacao/"), "/login/?next=/areas/operacao/",
            fetch_redirect_response=False,
        )
        self.assertNotContains(self.client.get("/login/"), 'aria-label="Navegação principal"')

    def test_unknown_area_returns_not_found(self):
        self.assertEqual(self.client.get("/areas/inexistente/").status_code, 404)
