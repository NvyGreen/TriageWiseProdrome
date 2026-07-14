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
