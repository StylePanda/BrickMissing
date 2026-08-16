from django.urls import path

from . import views

app_name = "legal"

urlpatterns = [
    path("impressum/", views.imprint, name="imprint"),
    path("datenschutz/", views.privacy, name="privacy"),
]
