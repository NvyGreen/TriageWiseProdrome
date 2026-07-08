from app.models.patient import Patient
from app.models.intake_record import IntakeRecord
from app.models.patient_severity import PatientSeverity
from app.models.triage_queue import TriageQueue
from app.models.case_update import CaseUpdate
from app.models.ai_explanation import AIExplanation
from app.models.override import Override
from app.models.system_metric import SystemMetric
from app.models.event_log import EventLog
from app.models.idempotency_key import IdempotencyKey
from app.models.condition_reference import ConditionReference
from app.models.scoring_rule import ScoringRule

from app.database import Base
metadata = Base.metadata