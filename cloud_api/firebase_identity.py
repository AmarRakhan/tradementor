"""Firebase identity-project selection without changing the data project."""

from __future__ import annotations

from typing import Any, Mapping


def check_revoked_tokens(environment: str) -> bool:
    """Require the remote revocation lookup only where Auth and data share IAM.

    ID tokens are always cryptographically verified, audience-scoped and
    expiry-checked. Isolated runtimes use the production identity project but
    deliberately do not receive production-wide Admin SDK access, so they skip
    only the additional remote user/revocation lookup.
    """

    return environment.strip().lower() not in {
        "staging",
        "live-canary",
        "strategy2-test-live",
        "strategy3-live",
    }


def recent_id_token(
    claims: Mapping[str, Any],
    *,
    now_epoch_seconds: float,
    maximum_age_seconds: int = 600,
) -> bool:
    """Return whether a token is fresh enough for the isolated live runtime."""

    try:
        issued_at = float(claims["iat"])
    except (KeyError, TypeError, ValueError):
        return False
    age_seconds = now_epoch_seconds - issued_at
    return -60 <= age_seconds <= maximum_age_seconds


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
