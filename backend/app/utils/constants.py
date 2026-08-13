VITAL_MAP = {
    "SpO2": "oxygen_saturation",
    "Heart rate": "heart_rate",
    "Respiratory rate": "respiration_rate",
    "Systolic BP": "blood_pressure_systolic",
    "Pain score": "pain_level"
}

TOTAL_VITALS = 5

LABEL_MAP = {
    "ESI-1": "Critical",
    "ESI-2": "Emergent",
    "ESI-3": "Urgent",
    "ESI-4": "Less urgent",
    "ESI-5": "Non-urgent"
}

ESI_THRESHOLDS = {
    "ESI-1": 8,
    "ESI-2": 6,
    "ESI-3": 3,
    "ESI-4": 1,
    "ESI-5": 0
}