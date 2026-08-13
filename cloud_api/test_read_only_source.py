from read_only_source import READ_ONLY_PATHS, read_source_url


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
