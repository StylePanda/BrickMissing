from django.urls import path

from . import views

app_name = "media_library"
urlpatterns = [
    path("dokumente/", views.document_list, name="list"),
    path("dokumente/hochladen/", views.upload, name="upload"),
    path("dokumente/<int:pk>/download/", views.download, name="download"),
    path("dokumente/<int:pk>/loeschen/", views.delete, name="delete"),
]
