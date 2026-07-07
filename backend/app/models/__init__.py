from app.models.patient import Patient
from app.models.intake_record import IntakeRecord
from app.models.patient_severity import PatientSeverity
from app.models.triage_queue import TriageQueue
from app.models.case_update import CaseUpdate

from app.database import Base
metadata = Base.metadata