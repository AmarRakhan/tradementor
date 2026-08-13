"""Firebase identity-project selection without changing the data project."""

from __future__ import annotations

from typing import Any


def identity_app(
    firebase_admin_module: Any,
    *,
    data_project_id: str,
    auth_project_id: str,
) -> Any:
    """Return an app that validates tokens for the configured identity project.

    The default Firebase app remains bound to ADC and therefore to the isolated
    staging Firestore project.  A named app only supplies the expected Firebase
    Authentication project ID; it never becomes the Firestore client app.
    """

    default_app = firebase_admin_module.get_app()
    auth_project_id = auth_project_id.strip()
    if not auth_project_id or auth_project_id == data_project_id.strip():
        return default_app

    try:
        return firebase_admin_module.get_app("identity")
    except ValueError:
        return firebase_admin_module.initialize_app(
            options={"projectId": auth_project_id},
            name="identity",
        )
