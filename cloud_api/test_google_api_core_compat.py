from pathlib import Path


def test_google_api_core_stays_below_path_template_encoding_regression():
    requirements = (Path(__file__).with_name("requirements.txt")).read_text()
    assert "google-api-core==2.34.0" in requirements


def test_default_firestore_database_path_keeps_literal_parentheses():
    from google.api_core import path_template

    path = path_template.expand(
        "projects/{project}/databases/{database}",
        project="tradementor-production",
        database="(default)",
    )
    assert path.endswith("/databases/(default)")
    assert "%28default%29" not in path
