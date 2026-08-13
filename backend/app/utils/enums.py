from enum import StrEnum


class ChiefComplaint(StrEnum):
    CARDIAC = "cardiac"
    RESPIRATORY = "respiratory"
    ABDOMINAL = "abdominal"
    STROKE = "stroke"
    SYNCOPE = "syncope"
    NEURO = "neuro"
    MINOR_INJURY = "minor_injury"
    MINOR_GENERAL = "minor_general"
    GENERAL = "general"


class PreExistingConditions(StrEnum):
    DIABETES = "diabetes"
    HYPERTENSION = "hypertension"
    CHF = "chf"
    COPD = "copd"
    PRIOR_MI = "prior_mi"
    PRIOR_STROKE = "prior_stroke"
    CANCER = "cancer"
    ANTICOAGULANT = "anticoagulant"
    IMMUNOCOMPROMISED = "immunocompromised"
    SICKLE_CELL = "sickle_cell"


class Sex(StrEnum):
    M = "M"
    F = "F"
    OTHER = "other"
    UNKNOWN = "unknown"


class PregnancyStatus(StrEnum):
    NONE = "none"
    PREGNANT = "pregnant"
    POSTPARTUM = "postpartum"


class ReasonCode(StrEnum):
    LACK_INFO = "Clinical info AI lacks"
    BAD_DRIVER = "AI driver incorrect"
    PATIENT_PREFERENCE = "Patient preference"
    OTHER = "Other"


class ESILevels(StrEnum):
    ESI_1 = "ESI-1"
    ESI_2 = "ESI-2"
    ESI_3 = "ESI-3"
    ESI_4 = "ESI-4"
    ESI_5 = "ESI-5"