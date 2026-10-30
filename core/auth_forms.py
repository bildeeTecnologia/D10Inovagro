from django import forms
from django.contrib.auth.forms import AuthenticationForm


class LoginFormBR(AuthenticationForm):
    username = forms.CharField(label="Usuário", widget=forms.TextInput(attrs={"autofocus": True}))
    password = forms.CharField(label="Senha", strip=False, widget=forms.PasswordInput)

    error_messages = {
        "invalid_login": "Informe um usuário e senha corretos. Os dois campos diferenciam maiúsculas e minúsculas.",
        "inactive": "Esta conta está inativa.",
    }
