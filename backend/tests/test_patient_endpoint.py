def test_submit_proper_intake_form(client):
    input = {
        "name":  "Robert Johnson",
        "date_of_birth": "1958-03-12",
        "sex": "M",
        "chief_complaint": "chest_pain",
        "symptoms": [
            "chest_pain",
            "dizziness"
        ],
        "heart_rate": 120,
        "blood_pressure_systolic": 140,
        "blood_pressure_diastolic": 90,
        "temperature": 101.2,
        "oxygen_saturation": None,
        "respiration_rate": None,
        "pain_level": 7,
        "blood_sugar": 180,
        "pregnancy_status": "none",
        "pre_existing_conditions": [
            "diabetes",
            "prior_mi"
        ],
        "arrival_by_ambulance": False,
        "recent_ed_visit_72h": False,
        "injury_related": False,
        "source": "form"
    }

    response = client.post("/patients", json=input)
    body = response.json()
    assert "payload" in body
    payload = body["payload"]
    assert "message" in payload
    assert payload["message"] == "Intake recorded successfully"
    assert "record" in payload
    record = payload["record"]
    assert record["heart_rate"] == 120
    assert record["arrival_by_ambulance"] == False

def test_submit_malformed_intake_form(client):
    # No complaint
    # Invalid heart rate type
    # Too-high o2sat
    # Negative pain
    # Invalid pre-existing conditions
    input = {
        "name":  "Robert Johnson",
        "date_of_birth": "1958-03-12",
        "sex": "M",
        "symptoms": [
            "chest_pain",
            "dizziness"
        ],
        "heart_rate": "abc",
        "blood_pressure_systolic": 140,
        "blood_pressure_diastolic": 90,
        "temperature": 101.2,
        "oxygen_saturation": 101,
        "respiration_rate": None,
        "pain_level": -1,
        "blood_sugar": 180,
        "pregnancy_status": "none",
        "pre_existing_conditions": [
            "fatigue"
        ],
        "arrival_by_ambulance": False,
        "recent_ed_visit_72h": False,
        "injury_related": False,
        "source": "form"
    }

    response = client.post("/patients", json=input)
    body = response.json()
    assert "error" in body
    error = body["error"]
    
    assert "code" in error
    assert error["code"] == "invalid_input"
    assert "message" in error
    assert error["message"] == "Malformed body, wrong types, missing required field (e.g. no chief complaint), out-of-range vital"

    assert "details" in error
    details = error["details"]
    assert len(details) == 5

    assert details[0]["field"] == "chief_complaint"
    assert details[0]["issue"] == "missing required field"

    assert details[1]["field"] == "heart_rate"
    assert details[1]["issue"] == "must be an integer"

    assert details[2]["field"] == "oxygen_saturation"
    assert "less than or equal to" in details[2]["issue"]

    assert details[3]["field"] == "pain_level"
    assert "greater than or equal to" in details[3]["issue"]

    assert details[4]["field"] == "pre_existing_conditions"
    assert "invalid selection" in details[4]["issue"]