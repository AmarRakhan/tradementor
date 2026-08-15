from read_only_source import LOCAL_STATE_PATHS_BY_ENVIRONMENT, READ_ONLY_PATHS, read_source_url


SOURCE = "https://tradementor-api-604335232956.europe-west4.run.app"


def test_only_allowlisted_reads_can_reach_existing_data_source():
    for path in READ_ONLY_PATHS:
        assert read_source_url(SOURCE, "GET", path) == f"{SOURCE}{path}"

    assert read_source_url(SOURCE, "POST", "/v1/me/aster/status") is None
    assert read_source_url(SOURCE, "PUT", "/v1/me/wallet") is None
    assert read_source_url(SOURCE, "GET", "/v1/me/orders/entry") is None
    assert read_source_url(SOURCE, "POST", "/internal/aster-automation/tick") is None


def test_query_is_preserved_but_unsafe_source_urls_are_rejected():
    assert read_source_url(SOURCE, "GET", "/v1/me/aster/trade-events", "limit=20") == (
        f"{SOURCE}/v1/me/aster/trade-events?limit=20"
    )
    assert read_source_url("http://example.test", "GET", "/v1/me/aster/status") is None
    assert read_source_url("https://user:secret@example.test", "GET", "/v1/me/aster/status") is None


def test_strategy2_test_status_stays_with_start_and_stop_in_the_test_runtime():
    environment = "strategy2-test-live"
    assert LOCAL_STATE_PATHS_BY_ENVIRONMENT[environment] == frozenset({"/v1/me/aster/status"})
    assert read_source_url(
        SOURCE,
        "GET",
        "/v1/me/aster/status",
        environment=environment,
    ) is None
    assert read_source_url(
        SOURCE,
        "GET",
        "/v1/me/aster/closed-trades",
        environment=environment,
    ) == f"{SOURCE}/v1/me/aster/closed-trades"
    assert read_source_url(
        SOURCE,
        "GET",
        "/v1/me/aster/status",
        environment="production",
    ) == f"{SOURCE}/v1/me/aster/status"
