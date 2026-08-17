"""Browser E2E for clinician override on the patient detail screen.

Flow: submit a patient (cardiac + normal vitals -> system ESI-2), open them from
the queue, then override the ESI twice — once more-acute (ESI-1) and once
less-acute (ESI-3) than the system band.

Isolation: the module-scoped `backend` fixture gives this file a fresh, empty
queue. `db_cleanup` removes the ZZTEST patient (its Override rows cascade) plus
the captured idempotency keys (one intake + two overrides).
"""
from playwright.sync_api import Page, expect

FRONTEND_URL = "http://localhost:5173"
PATIENT_NAME = "ZZTEST Override P"


def _submit_intake(page: Page):
    """Cardiac + normal vitals -> chief-complaint rule only -> system ESI-2."""
    page.fill("input[name='name']", PATIENT_NAME)
    page.select_option("select[name='sex']", "M")
    page.fill("input[name='date_of_birth']", "1990-01-01")
    page.select_option("select[name='chief_complaint']", "cardiac")
    for field, value in {
        "heart_rate": 80, "oxygen_saturation": 98, "respiration_rate": 16,
        "blood_pressure_systolic": 120, "pain_level": 2,
    }.items():
        page.fill(f"input[name='{field}']", str(value))
    page.click("button[type='submit']")
    expect(page.locator("li", has_text="Intake ID:")).to_be_visible()


def _override(page: Page, band: str, reason: str):
    """Select a band + reason and submit; return the POST /overrides/ status."""
    page.select_option("select[name='clinician_esi']", band)
    page.select_option("select[name='reason_code']", reason)
    with page.expect_response(
        lambda r: r.request.method == "POST" and "/overrides/" in r.url
    ) as resp:
        page.click("button.overrideSubmit")
    return resp.value.status


def test_override_more_then_less_acute(page: Page, db_cleanup):
    def on_request(r):
        if r.method == "POST" and ("/patients/" in r.url or "/overrides/" in r.url):
            key = r.headers.get("idempotency-key")
            if key:
                db_cleanup.append(key)
    page.on("request", on_request)

    # 1. Submit the patient.
    page.goto(FRONTEND_URL)
    _submit_intake(page)

    # 2. Queue -> click the patient's name -> detail page (wait for its load).
    page.get_by_role("link", name="Triage Queue").click()
    expect(page.locator("h1", has_text="Triage Queue")).to_be_visible()
    with page.expect_response(
        lambda r: r.request.method == "GET" and "/intakes/" in r.url and "mode=" in r.url
    ) as detail_resp:
        page.locator("a.namelink", has_text=PATIENT_NAME).click()
    assert detail_resp.value.status == 200
    expect(page.locator("select[name='clinician_esi']")).to_be_visible()

    # 3a. Override MORE acute: ESI-1 (system is ESI-2).
    assert _override(page, "ESI-1", "AI driver incorrect") == 201
    # Refetch shows the stored override; system band stays the original ESI-2.
    expect(page.locator(".dualbox .you .num")).to_have_text("ESI-1")
    expect(page.locator(".dualbox .sys .num")).to_have_text("ESI-2")

    # 3b. Override LESS acute: ESI-3.
    assert _override(page, "ESI-3", "Patient preference") == 201
    expect(page.locator(".dualbox .you .num")).to_have_text("ESI-3")
    expect(page.locator(".dualbox .sys .num")).to_have_text("ESI-2")
