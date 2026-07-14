"""Smoke tests for the root endpoint.

Copy this pattern (request the `client` fixture, hit an endpoint, assert
on status + body) for future endpoint tests.
"""


def test_root_returns_ok(client):
    response = client.get("/")
    assert response.status_code == 200


def test_root_returns_running_message(client):
    response = client.get("/")
    body = response.json()
    assert "payload" in body
    payload = body["payload"]
    assert "message" in payload
    assert payload["message"].endswith("API is running")


def test_endpoints_have_disclaimer(client):
    disclaimer_message = "simplified/educational, not clinically validated; explains & prioritizes, does not diagnose."

    root_response = client.get("/")
    root_body = root_response.json()
    assert "meta" in root_body
    root_meta = root_body["meta"]
    assert "disclaimer" in root_meta
    assert root_meta["disclaimer"] == disclaimer_message

    esi_response = client.get("/esi-bands")
    esi_body = esi_response.json()
    assert "meta" in esi_body
    esi_meta = esi_body["meta"]
    assert "disclaimer" in esi_meta
    assert esi_meta["disclaimer"] == disclaimer_message

    cr_response = client.get("/condition-reference")
    cr_body = cr_response.json()
    assert "meta" in cr_body
    cr_meta = cr_body["meta"]
    assert "disclaimer" in cr_meta
    assert cr_meta["disclaimer"] == disclaimer_message
