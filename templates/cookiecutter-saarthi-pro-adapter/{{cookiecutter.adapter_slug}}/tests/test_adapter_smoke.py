from {{ cookiecutter.package_name }} import adapter


def test_integration_profile_constant() -> None:
    assert adapter.INTEGRATION_PROFILE_ID == "{{ cookiecutter.integration_profile_id }}"


def test_example_health_probe_stub() -> None:
    body = adapter.example_health_probe()
    assert body["status"] == "stub"
    assert "profile" in body
