from django.urls import path

from . import views

app_name = "ps4"

urlpatterns = [
    path("", views.index, name="index"),
    path("findings/", views.findings, name="findings"),
    path("personas/", views.personas, name="personas"),
    path("personas/<slug:slug>/", views.persona_detail, name="persona_detail"),
    path("scenarios/", views.scenarios, name="scenarios"),
    path("scenarios/<slug:slug>/", views.scenario_detail, name="scenario_detail"),
    path("prototype/", views.prototype, name="prototype"),
    path("alternatives/", views.alternatives, name="alternatives"),
    path("permissions/", views.permissions, name="permissions"),
    path("mvp/", views.mvp, name="mvp"),
    path("summary/", views.summary, name="summary"),
]
