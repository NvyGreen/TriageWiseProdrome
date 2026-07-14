from pydantic import ValidationError
import pytest
from app.schemas.intake_create import IntakeCreate, ChiefComplaint

def test_valid_intake_input():
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

    intake_record = IntakeCreate.model_validate(input)
    assert intake_record.heart_rate == 120
    assert intake_record.chief_complaint == ChiefComplaint.CHEST_PAIN


def test_invalid_column_types():
    wrong_hr_type = {
        "name":  "Robert Johnson",
        "date_of_birth": "1958-03-12",
        "sex": "M",
        "chief_complaint": "chest_pain",
        "symptoms": [
            "chest_pain",
            "dizziness"
        ],
        "heart_rate": "abc",
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

    with pytest.raises(ValidationError):
        IntakeCreate.model_validate(wrong_hr_type)


def test_invalid_pain_scores():
    low_pain = {
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
        "pain_level": -1,
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

    with pytest.raises(ValidationError):
        IntakeCreate.model_validate(low_pain)

    
    high_pain = {
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
        "pain_level": 11,
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

    with pytest.raises(ValidationError):
        IntakeCreate.model_validate(high_pain)


def test_invalid_o2sat_scores():
    low_sat = {
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
        "oxygen_saturation": -1,
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

    with pytest.raises(ValidationError):
        IntakeCreate.model_validate(low_sat)

    
    high_sat = {
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
        "oxygen_saturation": 101,
        "respiration_rate": None,
        "pain_level": 11,
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

    with pytest.raises(ValidationError):
        IntakeCreate.model_validate(high_sat)


def test_valid_chief_complaint():
    no_complaint = {
        "name":  "Robert Johnson",
        "date_of_birth": "1958-03-12",
        "sex": "M",
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

    with pytest.raises(ValidationError):
        IntakeCreate.model_validate(no_complaint)
    

    invalid_complaint = {
        "name":  "Robert Johnson",
        "date_of_birth": "1958-03-12",
        "sex": "M",
        "chief_complaint": "fatigue",
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

    with pytest.raises(ValidationError):
        IntakeCreate.model_validate(invalid_complaint)


def test_valid_pre_existing_conditions():
    invalid_condition = {
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
            "heart_attack"
        ],
        "arrival_by_ambulance": False,
        "recent_ed_visit_72h": False,
        "injury_related": False,
        "source": "form"
    }

    with pytest.raises(ValidationError):
        IntakeCreate.model_validate(invalid_condition)

    
    no_condition = {
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
        "arrival_by_ambulance": False,
        "recent_ed_visit_72h": False,
        "injury_related": False,
        "source": "form"
    }

    intake_record = IntakeCreate.model_validate(no_condition)
    assert len(intake_record.pre_existing_conditions) == 0