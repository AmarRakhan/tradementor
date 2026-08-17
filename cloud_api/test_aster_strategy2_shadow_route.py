import ast
from pathlib import Path


SOURCE = Path(__file__).with_name("strategy2_test_entrypoint.py").read_text()
TREE = ast.parse(SOURCE)


def _route_function():
    return next(node for node in TREE.body if isinstance(node, ast.FunctionDef)
                and node.name == "strategy2_queue_shadow")


def test_queue_shadow_is_get_only_and_token_scoped():
    node = _route_function()
    decorators = ast.unparse(node.decorator_list[0])
    rendered = ast.unparse(node)
    assert decorators == "app.get('/v1/me/aster/strategy2/queue-shadow')"
    assert "authenticated_user" in rendered
    assert "str(user['uid'])" in rendered


def test_queue_shadow_client_can_never_submit_live():
    rendered = ast.unparse(_route_function())
    assert "live_authorized=False" in rendered
    assert ".submit_order(" not in rendered
    assert ".place_order(" not in rendered
    assert ".change_leverage(" not in rendered


def test_queue_shadow_contains_no_persistent_or_bot_scheduler_mutation():
    rendered = ast.unparse(_route_function())
    for forbidden in (".set(", ".update(", ".add(", ".commit(",
                      "enabled =", "monitor =", "gcloud"):
        assert forbidden not in rendered
    assert "persistentWrites': 0" in rendered
    assert "schedulerChanged': False" in rendered
    assert "botStatusChanged': False" in rendered


def test_queue_shadow_validates_new_entries_using_reads_only():
    rendered = ast.unparse(_route_function())
    assert "validated_entry_symbols" in rendered
    assert "public_exchange_info()" in rendered
    assert "ticker_prices()" in rendered
    assert "ticker_24h()" in rendered
    assert "leverage_brackets()" in rendered
    assert "READ_ONLY_CONTRACT_VALIDATED" in rendered
