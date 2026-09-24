"""The only Markdown files published by the documentation views."""

from dataclasses import dataclass


@dataclass(frozen=True)
class DocumentationPage:
    slug: str
    source: str
    title: str

    @property
    def audience(self) -> str:
        return "admin" if self.slug == "developer" or self.slug.startswith("developer/") else "public"

    @property
    def route_name(self):
        return "index" if not self.slug else self.slug.replace("/", "_").replace("-", "_")


PAGES = (
    DocumentationPage("", "index.md", "Dokumentation"),
    DocumentationPage("getting-started", "getting-started.md", "Erste Schritte"),
    DocumentationPage("sets", "sets.md", "Sets"),
    DocumentationPage("parts", "parts.md", "Teile"),
    DocumentationPage("missing-parts", "missing-parts.md", "Fehlteile"),
    DocumentationPage("minifigures", "minifigures.md", "Minifiguren"),
    DocumentationPage("export-import", "export-import.md", "Import / Export"),
    DocumentationPage("labels", "labels.md", "Etiketten"),
    DocumentationPage("organization", "organization.md", "Organisation"),
    DocumentationPage("account", "account.md", "Konto"),
    DocumentationPage("faq", "faq.md", "FAQ"),
    DocumentationPage("developer", "developer/index.md", "Entwicklerübersicht"),
    DocumentationPage("developer/architecture", "developer/architecture.md", "Architektur"),
    DocumentationPage("developer/data-model", "developer/data-model.md", "Datenmodell"),
    DocumentationPage("developer/quantities", "developer/quantities.md", "Mengenlogik"),
    DocumentationPage("developer/status-workflow", "developer/status-workflow.md", "Statusworkflow"),
    DocumentationPage("developer/rebrickable", "developer/rebrickable.md", "Rebrickable"),
    DocumentationPage("developer/deployment", "developer/deployment.md", "Deployment"),
    DocumentationPage("developer/testing", "developer/testing.md", "Tests"),
    DocumentationPage("developer/releases", "developer/releases.md", "Releases"),
    DocumentationPage("developer/versioning", "VERSIONING.md", "Versionierung"),
)

PAGES_BY_SLUG = {page.slug: page for page in PAGES}
PAGES_BY_SOURCE = {page.source: page for page in PAGES}
