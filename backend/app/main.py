import uuid
from fastapi import FastAPI, Request, status, Depends
from fastapi.exceptions import RequestValidationError, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from .config import get_settings, Settings
from .dependencies import get_db
from .models.esi_band import ESIBand
from .models.condition_reference import ConditionReference
from .routers import patients, queue, intakes
from .services.triage_service import IntakeNotFoundError, UnscoreableException


class MedicalDisclaimerResponse(JSONResponse):
    def render(self, content):
        if isinstance(content, dict) and "error" in content:
            return super().render(content)
        
        wrapped_content = {
            "payload": content,
            "meta": {
                "disclaimer": "simplified/educational, not clinically validated; explains & prioritizes, does not diagnose."
            }
        }
        return super().render(wrapped_content)


app = FastAPI(default_response_class=MedicalDisclaimerResponse)
patients_app = FastAPI(default_response_class=MedicalDisclaimerResponse)
queue_app = FastAPI(default_response_class=MedicalDisclaimerResponse)
intakes_app = FastAPI(default_response_class=MedicalDisclaimerResponse)


async def validation_handler(request: Request, exc: RequestValidationError):
    details = []
    for error in exc.errors():
        loc = error.get("loc", ())
        if not loc:
            continue
        if isinstance(loc[-1], int):
            field_name = loc[-2] if len(loc) > 1 else "body"
        else:
            field_name = loc[-1]
        
        error_type = error.get("type")
        raw_ctx = error.get("ctx", {})
        issue_msg = error["msg"].replace("Value error, ", "").lower()

        if error_type == "missing":
            issue_msg = "missing required field"
        elif error_type in ("int_type", "int_parsing"):
            issue_msg = "must be an integer"
        elif error_type in ("float_type", "float_parsing"):
            issue_msg = "must be a valid number"
        elif error_type == "date_type":
            issue_msg = "must be a valid date (YYYY-MM-DD)"
        elif error_type == "bool_type":
            issue_msg = "must be a boolean value (true/false)"
        elif error_type == "enum":
            allowed = raw_ctx.get("expected", "").replace("'", "")
            issue_msg = f"invalid selection. must be one of: {allowed}"
        elif error_type in ("greater_than_equal", "greater_than"):
            limit = raw_ctx.get("ge") if raw_ctx.get("ge") is not None else raw_ctx.get("gt")
            issue_msg = f"must be greater than or equal to {limit}"
        elif error_type in ("less_than_equal", "less_than"):
            limit = raw_ctx.get("le") if raw_ctx.get("le") is not None else raw_ctx.get("lt")
            issue_msg = f"must be less than or equal to {limit}"

        details.append({"field": str(field_name), "issue": issue_msg})

    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "error": {
                "code": "invalid_input",
                "message": "One or more fields are invalid.",
                "details": details,
                "request_id": f"req_{uuid.uuid4().hex[:12]}"
            }
        }
    )

# Registered on both sub-apps at the bottom of this module, so the 500 envelope
# stays identical across them.
async def internal_server_error(request: Request, exc: HTTPException):
    if exc.status_code == 500:
        return JSONResponse(
            status_code = status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "Something went wrong on our end. Please try again.",
                    "request_id": f"req_{uuid.uuid4().hex[:12]}"
                }
            }
        )
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

@patients_app.exception_handler(patients.IdempotencyKeyRequiredException)
async def idempotency_key_required_handler(request: Request, exc: patients.IdempotencyKeyRequiredException):
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "error": {
                "code": "invalid_input",
                "message": "One or more fields are invalid.",
                "details": [
                    {"field": "Idempotency-Key", "issue": "missing required header"}
                ],
                "request_id": f"req_{uuid.uuid4().hex[:12]}"
            }
        }
    )

@patients_app.exception_handler(patients.DuplicateRequestException)
async def patient_duplicate_handler(request: Request, exc: patients.DuplicateRequestException):
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={
            "error": {
                "code": "duplicate_request",
                "message": "This request was already submitted.",
                "request_id": f"req_{uuid.uuid4().hex[:12]}"
            }
        }
    )

async def unscoreable_handler(request: Request, exc: UnscoreableException):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={
            "error": {
                "code": "unscoreable",
                "message": "The intake is valid but cannot be scored.",
                "request_id": f"req_{uuid.uuid4().hex[:12]}"
            }
        }
    )

@intakes_app.exception_handler(IntakeNotFoundError)
async def intakes_not_found_handler(request: Request, exc: IntakeNotFoundError):
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={
            "error": {
                "code": "not_found",
                "message": "No intake with that id.",
                "request_id": f"req_{uuid.uuid4().hex[:12]}"
            }
        }
    )


for sub_app in (patients_app, queue_app, intakes_app):
    sub_app.add_exception_handler(HTTPException, internal_server_error)

for sub_app in (patients_app, intakes_app):
    sub_app.add_exception_handler(RequestValidationError, validation_handler)
    sub_app.add_exception_handler(UnscoreableException, unscoreable_handler)


patients_app.include_router(patients.router)
app.mount("/patients", patients_app)

queue_app.include_router(queue.router)
app.mount("/queue", queue_app)

intakes_app.include_router(intakes.router)
app.mount("/intakes", intakes_app)


@app.get("/")
def root(settings: Settings = Depends(get_settings)):
    return {
        "message": f"{settings.app_name} API is running"
    }

@app.get("/esi-bands")
def get_esi_bands(db: Session = Depends(get_db)):
    # Fetch all 5 bands sorted by their primary key
    bands = db.query(ESIBand).order_by(ESIBand.band_id).all()
    return bands

@app.get("/condition-reference")
def get_condition_reference(db: Session = Depends(get_db)):
    conditions = db.query(ConditionReference).all()
    return conditions