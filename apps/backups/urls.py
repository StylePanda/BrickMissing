from django.urls import path

from . import views

app_name = "backups"
urlpatterns = [
    path("system/backups/", views.backup_list, name="list"),
    path("system/backups/create/", views.backup_create, name="create"),
    path("system/backups/<int:pk>/download/", views.backup_download, name="download"),
    path("system/backups/<int:pk>/restore/", views.backup_restore, name="restore"),
]
