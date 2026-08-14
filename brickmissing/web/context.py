from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ApplicationContext:
    """Explicit dependency graph shared by controllers and request handlers."""

    config: Any
    database: Any
    services: Any
    mariadb: Any
    email: Any
    pricing: Any
    api: Any
    account_security: Any
    operations: Any
    user_content: Any
    assets: Any
    static_assets: Any
    hub: Any
