from django.urls import path

from . import views

app_name = "catalog"
urlpatterns = [
    path("sets/", views.set_list, name="set_list"),
    path("sets/neu/", views.set_edit, name="set_create"),
    path("sets/<uuid:pk>/", views.set_detail, name="set_detail"),
    path("sets/<uuid:pk>/bearbeiten/", views.set_edit, name="set_edit"),
    path("sets/<uuid:pk>/loeschen/", views.set_delete, name="set_delete"),
    path("sets/<uuid:set_pk>/exemplare/neu/", views.set_copy_edit, name="set_copy_create"),
    path("sets/<uuid:set_pk>/exemplare/<int:pk>/", views.set_copy_edit, name="set_copy_edit"),
    path("sets/<uuid:set_pk>/inventar/neu/", views.set_inventory_edit, name="set_inventory_create"),
    path("sets/<uuid:set_pk>/inventar/<int:pk>/", views.set_inventory_edit, name="set_inventory_edit"),
    path("sets/<uuid:set_pk>/inventar/aktion/<str:action>/", views.set_inventory_action, name="set_inventory_action"),
    path("teile/", views.part_list, name="part_list"),
    path("teile/neu/", views.part_edit, name="part_create"),
    path("teile/<uuid:pk>/bearbeiten/", views.part_edit, name="part_edit"),
    path("teile/<uuid:pk>/loeschen/", views.part_delete, name="part_delete"),
    path("fehlteile/", views.missing_parts, name="missing_parts"),
    path("fehlteile/aktion/", views.missing_parts_bulk, name="missing_parts_bulk"),
    path("papierkorb/", views.trash, name="trash"),
    path("papierkorb/<str:kind>/<uuid:pk>/wiederherstellen/", views.restore, name="restore"),
    path("papierkorb/<str:kind>/<uuid:pk>/endgueltig-loeschen/", views.permanent_delete, name="permanent_delete"),
]
