from __future__ import annotations

from typing import Any, Mapping


class AuthorizationPolicy:
    """Central ownership rules shared by HTTP routes and services."""

    ROLE_LEVELS = {
        "readonly": 0,
        "viewer": 0,
        "user": 1,
        "editor": 1,
        "collection_manager": 2,
        "manager": 2,
        "admin": 3,
    }

    @classmethod
    def can_write(cls, session: Mapping[str, Any]) -> bool:
        return cls.ROLE_LEVELS.get(str(session.get("role", "readonly")), 0) >= 1

    @classmethod
    def can_manage_collection(cls, session: Mapping[str, Any]) -> bool:
        return cls.ROLE_LEVELS.get(str(session.get("role", "readonly")), 0) >= 2

    @classmethod
    def require_write(cls, session: Mapping[str, Any]) -> None:
        if not cls.can_write(session):
            raise PermissionError("Dieses Konto besitzt nur Leserechte.")

    @staticmethod
    def user_id(session: Mapping[str, Any], requested: Any) -> int:
        requested_id = int(requested or session["id"])
        if session["role"] != "admin" and requested_id != int(session["id"]):
            raise PermissionError("Kein Zugriff auf diesen Benutzer.")
        return requested_id

    @classmethod
    def requested_user_id(
        cls, session: Mapping[str, Any], requested: Any = None
    ) -> int:
        default = (
            session.get("selected_user_id", session["id"])
            if session["role"] == "admin"
            else session["id"]
        )
        return cls.user_id(
            session,
            requested if requested not in (None, "") else default,
        )

    @staticmethod
    def owns(session: Mapping[str, Any], owner_id: Any) -> bool:
        return session["role"] == "admin" or int(owner_id) == int(session["id"])

    @classmethod
    def require_owner(
        cls, session: Mapping[str, Any], owner_id: Any, resource: str
    ) -> None:
        if not cls.owns(session, owner_id):
            raise PermissionError(f"Kein Zugriff auf {resource}.")
