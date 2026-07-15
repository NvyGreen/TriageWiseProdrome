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