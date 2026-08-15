"""Browser E2E for the Patient Intake form (scenarios #1 and #4).

Runs against the real backend + frontend started by conftest, hitting the real DB.
#4 marks its patient 'ZZTEST ...' and registers the sent Idempotency-Key so
db_cleanup removes the row (and key) afterward.

The idempotency replay/conflict/missing-key and unscoreable scenarios live at the
API layer (test_patient_endpoint / test_override_endpoint) — the form can't reach
them (it always sends a key and rotates it on success).
"""
from playwright.sync_api import Page, expect

FRONTEND_URL = "http://localhost:5173"


def test_bad_input_is_rejected_client_side(page: Page):
    """#1: submitting with empty required fields is blocked by client validation —
    inline errors show and no request is sent."""
    posts = []
    page.on("request", lambda r: posts.append(r) if r.method == "POST" and "/patients/" in r.url else None)

    page.goto(FRONTEND_URL)
    page.click("button[type='submit']")

    # Inline validation surfaces the required-field errors.
    expect(page.locator(".field-error", has_text="Patient name is required.")).to_be_visible()
    expect(page.locator("[aria-invalid='true']").first).to_be_visible()

    # The form never reached the API, and no success was shown.
    page.wait_for_timeout(500)
    assert posts == []
    expect(page.locator("li", has_text="Intake ID:")).to_have_count(0)


def test_valid_intake_succeeds(page: Page, db_cleanup):
    """#4: a valid, scoreable intake with an idempotency key returns 201 and the
    success feedback renders."""
    def on_request(r):
        if r.method == "POST" and "/patients/" in r.url:
            key = r.headers.get("idempotency-key")
            if key:
                db_cleanup.append(key)  # register for teardown
    page.on("request", on_request)

    page.goto(FRONTEND_URL)

    page.fill("input[name='name']", "ZZTEST E2E Playwright")
    page.select_option("select[name='sex']", "M")          # Male -> no pregnancy field
    page.fill("input[name='date_of_birth']", "1990-01-01")
    page.select_option("select[name='chief_complaint']", "cardiac")

    # Scoreable vitals.
    page.fill("input[name='heart_rate']", "130")
    page.fill("input[name='oxygen_saturation']", "90")
    page.fill("input[name='respiration_rate']", "26")
    page.fill("input[name='blood_pressure_systolic']", "95")
    page.fill("input[name='pain_level']", "6")

    page.click("button[type='submit']")

    # Success feedback (success branch is the only one that shows "Intake ID:").
    expect(page.locator("li", has_text="Intake ID:")).to_be_visible()
    expect(page.locator("li", has_text="Severity score:")).to_be_visible()
