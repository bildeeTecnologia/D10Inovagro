from django.http import HttpResponse
from django.template.loader import render_to_string


def _error_response(code, heading, message):
    # Sem RequestContext: a página deve continuar funcionando se banco/context processors falharem.
    html = render_to_string(
        "errors/error.html",
        {"code": code, "heading": heading, "message": message},
    )
    return HttpResponse(html, status=int(code), content_type="text/html; charset=utf-8")


def bad_request(request, exception=None):
    return _error_response(
        400,
        "Não foi possível concluir esta solicitação",
        "Confira as informações e tente novamente. Se o problema continuar, volte à página anterior e recomece a ação.",
    )


def forbidden(request, exception=None):
    return _error_response(
        403,
        "Você não tem acesso a esta página",
        "Seu perfil não permite esta ação. Se acredita que deveria ter acesso, fale com o administrador do sistema.",
    )


def csrf_failure(request, reason=""):
    # O motivo técnico é deliberadamente omitido da resposta ao usuário.
    return _error_response(
        403,
        "Não foi possível validar sua solicitação",
        "Por segurança, a ação não foi concluída. Atualize a página e tente novamente. Se o problema persistir, saia e entre no sistema outra vez.",
    )


def not_found(request, exception=None):
    return _error_response(
        404,
        "Página não encontrada",
        "O endereço pode ter mudado ou estar incorreto. Volte ao início e escolha a opção pelo menu.",
    )


def server_error(request):
    return _error_response(
        500,
        "Tivemos um problema temporário",
        "Não foi possível concluir esta ação agora. Aguarde um pouco e tente novamente. A equipe responsável poderá verificar o ocorrido.",
    )
