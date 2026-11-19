from django.urls import path

from . import api

app_name = "api_auth"

urlpatterns = [
    path("login/", api.LoginAPIView.as_view(), name="login"),
    path("logout/", api.LogoutAPIView.as_view(), name="logout"),
    path("me/", api.CurrentUserAPIView.as_view(), name="me"),
]
