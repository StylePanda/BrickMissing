from django.urls import path

from . import views

app_name = "inventory"
urlpatterns = [
    path("inventar/", views.inventory_list, name="list"),
    path("inventar/neu/", views.inventory_edit, name="create"),
    path("inventar/<int:pk>/", views.inventory_edit, name="edit"),
    path("lagerorte/", views.locations, name="locations"),
    path("lagerorte/neu/", views.location_edit, name="location_create"),
    path("lagerorte/<int:pk>/", views.location_edit, name="location_edit"),
    path("lagerorte/<int:pk>/qr.svg", views.location_qr, name="location_qr"),
]
