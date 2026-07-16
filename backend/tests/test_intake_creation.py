from pydantic import ValidationError
import pytest
from app.schemas.intake_create import IntakeCreate, ChiefComplaint

def test_valid_intake_input(intake_body):
    intake_record = IntakeCreate.model_validate(intake_body)
    assert intake_record.heart_rate == 120
    assert intake_record.chief_complaint == ChiefComplaint.CHEST_PAIN


def test_invalid_column_types(intake_body):
    intake_body["heart_rate"] = "abc"
    with pytest.raises(ValidationError) as e:
        IntakeCreate.model_validate(intake_body)
    assert "valid integer" in e.exconly()


def test_invalid_pain_scores(intake_body):
    intake_body["pain_level"] = -1
    with pytest.raises(ValidationError) as e:
        IntakeCreate.model_validate(intake_body)
    assert "pain_level" in e.exconly()
    assert "greater than or equal to" in e.exconly()

    
    intake_body["pain_level"] = 11
    with pytest.raises(ValidationError) as e:
        IntakeCreate.model_validate(intake_body)
    assert "pain_level" in e.exconly()
    assert "less than or equal to" in e.exconly()


def test_invalid_o2sat_scores(intake_body):
    intake_body["oxygen_saturation"] = -1
    with pytest.raises(ValidationError) as e:
        IntakeCreate.model_validate(intake_body)
    assert "oxygen_saturation" in e.exconly()
    assert "greater than or equal to" in e.exconly()

    
    intake_body["oxygen_saturation"] = 101
    with pytest.raises(ValidationError) as e:
        IntakeCreate.model_validate(intake_body)
    assert "oxygen_saturation" in e.exconly()
    assert "less than or equal to" in e.exconly()


def test_valid_chief_complaint(intake_body):
    del intake_body["chief_complaint"]
    with pytest.raises(ValidationError) as e:
        IntakeCreate.model_validate(intake_body)
    assert "chief_complaint" in e.exconly()
    assert "required" in e.exconly()
    

    intake_body["chief_complaint"] = "fatigue"
    with pytest.raises(ValidationError) as e:
        IntakeCreate.model_validate(intake_body)
    assert "chief_complaint" in e.exconly()
    assert "Input should be" in e.exconly()


def test_valid_pre_existing_conditions(intake_body):
    intake_body["pre_existing_conditions"] = ["heart_attack"]
    with pytest.raises(ValidationError) as e:
        IntakeCreate.model_validate(intake_body)
    assert "pre_existing_conditions" in e.exconly()
    assert "Input should be" in e.exconly()

    del intake_body["pre_existing_conditions"]
    intake_record = IntakeCreate.model_validate(intake_body)
    assert len(intake_record.pre_existing_conditions) == 0

def test_invalid_dob(intake_body):
    intake_body["date_of_birth"] = "3000-01-01"
    with pytest.raises(ValidationError) as e:
        IntakeCreate.model_validate(intake_body)
    assert "date_of_birth" in e.exconly()
    assert "Value error" in e.exconly()


def test_invalid_name(intake_body):
    intake_body["name"] = "a" * 101
    with pytest.raises(ValidationError) as e:
        IntakeCreate.model_validate(intake_body)
    assert "name" in e.exconly()
    assert "at most 100 characters" in e.exconly()


def test_invalid_heart_rate_scores(intake_body):
    intake_body["heart_rate"] = -1
    with pytest.raises(ValidationError) as e:
        IntakeCreate.model_validate(intake_body)
    assert "heart_rate" in e.exconly()
    assert "greater than or equal to" in e.exconly()


    intake_body["heart_rate"] = 351
    with pytest.raises(ValidationError) as e:
        IntakeCreate.model_validate(intake_body)
    assert "heart_rate" in e.exconly()
    assert "less than or equal to" in e.exconly()


def test_invalid_systolic_scores(intake_body):
    intake_body["blood_pressure_systolic"] = -1
    with pytest.raises(ValidationError) as e:
        IntakeCreate.model_validate(intake_body)
    assert "blood_pressure_systolic" in e.exconly()
    assert "greater than or equal to" in e.exconly()


    intake_body["blood_pressure_systolic"] = 301
    with pytest.raises(ValidationError) as e:
        IntakeCreate.model_validate(intake_body)
    assert "blood_pressure_systolic" in e.exconly()
    assert "less than or equal to" in e.exconly()


def test_invalid_diastolic_scores(intake_body):
    intake_body["blood_pressure_diastolic"] = -1
    with pytest.raises(ValidationError) as e:
        IntakeCreate.model_validate(intake_body)
    assert "blood_pressure_diastolic" in e.exconly()
    assert "greater than or equal to" in e.exconly()


    intake_body["blood_pressure_diastolic"] = 251
    with pytest.raises(ValidationError) as e:
        IntakeCreate.model_validate(intake_body)
    assert "blood_pressure_diastolic" in e.exconly()
    assert "less than or equal to" in e.exconly()


def test_systolic_higher_than_diastolic(intake_body):
    intake_body["blood_pressure_systolic"] = 90
    intake_body["blood_pressure_diastolic"] = 120
    with pytest.raises(ValidationError) as e:
        IntakeCreate.model_validate(intake_body)
    assert "Value error" in e.exconly()
    assert "Systolic must be higher than diastolic" in e.exconly()


    intake_body["blood_pressure_systolic"] = 100
    intake_body["blood_pressure_diastolic"] = 100
    with pytest.raises(ValidationError) as e:
        IntakeCreate.model_validate(intake_body)
    assert "Value error" in e.exconly()
    assert "Systolic must be higher than diastolic" in e.exconly()


def test_invalid_temperature_scores(intake_body):
    intake_body["temperature"] = 67.9
    with pytest.raises(ValidationError) as e:
        IntakeCreate.model_validate(intake_body)
    assert "temperature" in e.exconly()
    assert "greater than or equal to" in e.exconly()


    intake_body["temperature"] = 115.1
    with pytest.raises(ValidationError) as e:
        IntakeCreate.model_validate(intake_body)
    assert "temperature" in e.exconly()
    assert "less than or equal to" in e.exconly()


def test_invalid_respiration_rate_scores(intake_body):
    intake_body["respiration_rate"] = -1
    with pytest.raises(ValidationError) as e:
        IntakeCreate.model_validate(intake_body)
    assert "respiration_rate" in e.exconly()
    assert "greater than or equal to" in e.exconly()


    intake_body["respiration_rate"] = 100
    with pytest.raises(ValidationError) as e:
        IntakeCreate.model_validate(intake_body)
    assert "respiration_rate" in e.exconly()
    assert "less than or equal to" in e.exconly()


def test_invalid_blood_sugar_scores(intake_body):
    intake_body["blood_sugar"] = -1.0
    with pytest.raises(ValidationError) as e:
        IntakeCreate.model_validate(intake_body)
    assert "blood_sugar" in e.exconly()
    assert "greater than or equal to" in e.exconly()


    intake_body["blood_sugar"] = 1000.0
    with pytest.raises(ValidationError) as e:
        IntakeCreate.model_validate(intake_body)
    assert "blood_sugar" in e.exconly()
    assert "less than or equal to" in e.exconly()


def test_invalid_source(intake_body):
    intake_body["source"] = "a" * 11
    with pytest.raises(ValidationError) as e:
        IntakeCreate.model_validate(intake_body)
    assert "source" in e.exconly()
    assert "at most 10 characters" in e.exconly()