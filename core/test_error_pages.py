from django.test import Client, RequestFactory, SimpleTestCase, override_settings

from .error_views import server_error


class ErrorPageTests(SimpleTestCase):
    def test_404_uses_branded_page_when_debug_is_disabled(self):
        with override_settings(DEBUG=False):
            response = self.client.get("/endereco-que-nao-existe-para-teste/")

        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "Página não encontrada", status_code=404)
        self.assertContains(response, "D10 AGRO", status_code=404)
        self.assertNotContains(response, "Page not found", status_code=404)

    def test_csrf_failure_is_generic_even_if_debug_is_enabled(self):
        client = Client(enforce_csrf_checks=True)
        with override_settings(DEBUG=True):
            response = client.post("/login/", data={})

        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "Não foi possível validar sua solicitação", status_code=403)
        self.assertNotContains(response, "Reason given for failure", status_code=403)
        self.assertNotContains(response, "CSRF token", status_code=403)

    def test_server_error_page_does_not_expose_exception_details(self):
        response = server_error(RequestFactory().get("/"))

        self.assertEqual(response.status_code, 500)
        self.assertContains(response, "Tivemos um problema temporário", status_code=500)
        self.assertNotContains(response, "Traceback", status_code=500)
