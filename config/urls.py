from django.contrib import admin
from django.urls import include, path

from apps.catalog.views import dashboard
from apps.core.views import (
    global_search,
    health,
    quality,
    quality_scan,
    saved_view_delete,
    saved_view_load,
    saved_views,
    service_worker,
    test_email,
)

admin.site.site_header = "BrickMissing Administration"
admin.site.site_title = "BrickMissing Administration"
admin.site.index_title = "Systemverwaltung"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("konto/", include("apps.accounts.urls")),
    path("", include("apps.legal.urls")),
    path("", dashboard, name="dashboard"),
    path("", include("apps.catalog.urls")),
    path("", include("apps.inventory.urls")),
    path("", include("apps.orders.urls")),
    path("", include("apps.data_portability.urls")),
    path("", include("apps.organizer.urls")),
    path("", include("apps.backups.urls")),
    path("", include("apps.integrations.urls")),
    path("health/", health, name="health"),
    path("service-worker.js", service_worker, name="service_worker"),
    path("system/email-test/", test_email, name="test_email"),
    path("suche/", global_search, name="global_search"),
    path("ansichten/", saved_views, name="saved_views"),
    path("ansichten/<int:pk>/laden/", saved_view_load, name="saved_view_load"),
    path("ansichten/<int:pk>/loeschen/", saved_view_delete, name="saved_view_delete"),
    path("datenqualitaet/", quality, name="quality"),
    path("datenqualitaet/pruefen/", quality_scan, name="quality_scan"),
]
