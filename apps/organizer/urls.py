from django.urls import path

from . import views

app_name = "organizer"
urlpatterns = [
    path("organisation/labels/<int:pk>/preview/", views.label_preview, name="label_preview"),
    path("organisation/labels/<int:pk>/qr/<int:item_pk>.svg", views.label_qr, name="label_qr"),
    path("organisation/mocs/<int:moc_pk>/versionen/neu/", views.moc_version_edit, name="moc_version_create"),
    path("organisation/mocs/<int:moc_pk>/versionen/<int:pk>/", views.moc_version_edit, name="moc_version_edit"),
    path("organisation/mocs/<int:moc_pk>/versionen/<int:pk>/loeschen/", views.moc_version_delete, name="moc_version_delete"),
    path("organisation/mocs/<int:moc_pk>/versionen/<int:pk>/aktivieren/", views.moc_version_activate, name="moc_version_activate"),
    path("organisation/<str:area>/", views.area_list, name="list"),
    path("organisation/<str:area>/neu/", views.area_edit, name="create"),
    path("organisation/<str:area>/<int:pk>/", views.area_edit, name="edit"),
    path("organisation/<str:area>/<int:pk>/details/", views.area_detail, name="detail"),
    path("organisation/<str:area>/<int:parent_pk>/bestandteile/neu/", views.child_edit, name="child_create"),
    path("organisation/<str:area>/<int:parent_pk>/bestandteile/<int:pk>/", views.child_edit, name="child_edit"),
    path("organisation/<str:area>/<int:pk>/loeschen/", views.area_delete, name="delete"),
]
