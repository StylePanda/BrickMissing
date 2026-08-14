from django.urls import path

from . import views

app_name = "integrations"
urlpatterns = [
    path("integrationen/rebrickable/set-suche/", views.rebrickable_set_lookup, name="rebrickable_set_lookup"),
    path("integrationen/rebrickable/sets/<uuid:pk>/", views.sync_rebrickable, name="sync_rebrickable"),
    path("integrationen/rebrickable/sets/<uuid:pk>/anleitungen/", views.instructions, name="instructions"),
    path("integrationen/bild/", views.image_proxy, name="image_proxy"),
    path("integrationen/lego-pick-a-brick/<uuid:pk>/", views.pick_a_brick, name="pick_a_brick"),
    path("integrationen/preise/sets/<uuid:pk>/", views.sync_price, name="sync_price"),
]
