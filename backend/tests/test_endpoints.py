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