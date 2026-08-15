from firebase_identity import check_revoked_tokens, identity_app, recent_id_token


class FakeFirebaseAdmin:
    def __init__(self):
        self.apps = {"[DEFAULT]": {"name": "[DEFAULT]"}}
        self.initializations = []

    def get_app(self, name="[DEFAULT]"):
        if name not in self.apps:
            raise ValueError(name)
        return self.apps[name]

    def initialize_app(self, *, options, name):
        app = {"name": name, "options": options}
        self.apps[name] = app
        self.initializations.append(app)
        return app


def test_separate_identity_app_preserves_staging_data_app():
    firebase = FakeFirebaseAdmin()

    selected = identity_app(
        firebase,
        data_project_id="tradementor-migration-20260812",
        auth_project_id="tradementor-production",
    )

    assert selected == {
        "name": "identity",
        "options": {"projectId": "tradementor-production"},
    }
    assert firebase.get_app() == {"name": "[DEFAULT]"}


def test_identity_app_is_reused_without_reinitializing():
    firebase = FakeFirebaseAdmin()

    first = identity_app(
        firebase,
        data_project_id="tradementor-migration-20260812",
        auth_project_id="tradementor-production",
    )
    second = identity_app(
        firebase,
        data_project_id="tradementor-migration-20260812",
        auth_project_id="tradementor-production",
    )

    assert second is first
    assert len(firebase.initializations) == 1


def test_default_app_is_used_when_projects_match_or_auth_is_unset():
    firebase = FakeFirebaseAdmin()

    same_project = identity_app(
        firebase,
        data_project_id="tradementor-production",
        auth_project_id="tradementor-production",
    )
    unset = identity_app(
        firebase,
        data_project_id="tradementor-migration-20260812",
        auth_project_id="",
    )

    assert same_project is firebase.get_app()
    assert unset is firebase.get_app()
    assert firebase.initializations == []


def test_isolated_runtimes_skip_only_the_remote_revocation_lookup():
    assert check_revoked_tokens("staging") is False
    assert check_revoked_tokens(" STAGING ") is False
    assert check_revoked_tokens("live-canary") is False
    assert check_revoked_tokens("strategy2-test-live") is False
    assert check_revoked_tokens("strategy3-live") is False
    assert check_revoked_tokens(" STRATEGY3-LIVE ") is False


def test_shared_project_environments_keep_revocation_checks_enabled():
    assert check_revoked_tokens("production") is True
    assert check_revoked_tokens("") is True


def test_recent_id_token_accepts_only_a_ten_minute_window():
    now = 2_000.0

    assert recent_id_token({"iat": 1_400}, now_epoch_seconds=now) is True
    assert recent_id_token({"iat": 1_399}, now_epoch_seconds=now) is False
    assert recent_id_token({"iat": 2_060}, now_epoch_seconds=now) is True
    assert recent_id_token({"iat": 2_061}, now_epoch_seconds=now) is False
    assert recent_id_token({}, now_epoch_seconds=now) is False
