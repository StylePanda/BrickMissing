from django.urls import path

from . import views

app_name = "data_portability"
urlpatterns = [
    path("daten/meine-daten/", views.personal_export_page, name="personal_export"),
    path(
        "daten/meine-daten/download/",
        views.personal_export_download,
        name="personal_export_download",
    ),
    path("daten/import/", views.import_page, name="import_page"),
    path("daten/import/json/", views.import_json, name="import_json"),
    path("daten/import/csv/", views.import_csv, name="import_csv"),
    path("daten/import/<uuid:pk>/bestaetigen/", views.import_confirm, name="import_confirm"),
    path("daten/export/json/", views.export_json, name="export_json"),
    path("daten/export/fehlteile.csv", views.export_missing_csv, name="export_csv"),
]
