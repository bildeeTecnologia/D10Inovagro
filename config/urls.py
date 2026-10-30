from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from core.auth_forms import LoginFormBR

admin.site.site_header = "Administração do Fechamento de Campo"
admin.site.site_title = "Fechamento de Campo"
admin.site.index_title = "Gestão do sistema"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("login/", auth_views.LoginView.as_view(template_name="registration/login.html", authentication_form=LoginFormBR), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", include("core.urls")),
]
