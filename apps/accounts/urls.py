from django.contrib.auth.views import LogoutView
from django.urls import path

from apps.accounts import views

urlpatterns = [
    path("login/", views.CompanyAuthLoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path(
        "password-change/",
        views.CompanyPasswordChangeView.as_view(),
        name="password_change",
    ),
    path(
        "password-change/hecho/",
        views.CompanyPasswordChangeDoneView.as_view(),
        name="password_change_done",
    ),
    path("sitios/", views.SiteListView.as_view(), name="site_list"),
    path("sitios/nuevo/", views.SiteCreateView.as_view(), name="site_create"),
    path("sitios/<int:pk>/", views.SiteDetailView.as_view(), name="site_detail"),
    path("sitios/<int:pk>/editar/", views.SiteUpdateView.as_view(), name="site_update"),
    path("usuarios/", views.user_list, name="user_list"),
    path("usuarios/invitar/", views.user_invite, name="user_invite"),
    path(
        "usuarios/<int:pk>/desactivar/",
        views.user_deactivate,
        name="user_deactivate",
    ),
]
