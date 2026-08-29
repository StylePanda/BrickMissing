from django.urls import path

from . import views

app_name = "orders"
urlpatterns = [
    path("bestellungen/", views.order_list, name="list"),
    path("bestellungen/neu/", views.order_edit, name="create"),
    path("bestellungen/importieren/", views.order_import, name="import"),
    path("bestellungen/importieren/bestaetigen/", views.order_import_confirm, name="import_confirm"),
    path("bestellungen/<int:pk>/", views.order_detail, name="detail"),
    path("bestellungen/<int:pk>/bearbeiten/", views.order_edit, name="edit"),
    path("bestellungen/<int:order_pk>/position/neu/", views.item_edit, name="item_create"),
    path("bestellungen/<int:order_pk>/position/<int:pk>/", views.item_edit, name="item_edit"),
    path("bestellungen/<int:order_pk>/position/<int:pk>/eingang/", views.receive_item, name="receive_item"),
]
