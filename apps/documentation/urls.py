from django.urls import path

from .pages import PAGES
from .views import documentation_page

app_name = "documentation"

# Static patterns are generated only from the explicit publication allowlist.
urlpatterns = [
    path(f"{page.slug}/" if page.slug else "", documentation_page,
         {"slug": page.slug}, name=page.route_name)
    for page in PAGES
]
