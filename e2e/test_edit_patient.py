"""Browser E2E for the Edit Patient screen.

Flow: submit an intake with some scoreable vitals missing, open the patient from
the queue, go to Edit Patient, fill the missing vitals, Save & Recompute, then
return to the detail screen.

Isolation: the session-scoped `backend` fixture keeps one backend + scorer up for
the whole run, so the patient stays queued across page navigations, which the
clinical-update save needs. Per-test isolation comes from `db_cleanup` purging the
ZZTEST patient (its case_update / severity rows cascade) at setup and teardown,
plus the intake idempotency key (the edit PATCH carries no key).
"""
import re

from playwright.sync_api import Page, expect

FRONTEND_URL = "http://localhost:5173"
PATIENT_NAME = "ZZTEST Edit P"


def test_edit_fills_missing_vitals(page: Page, db_cleanup, wait_for_scored):
    def on_request(r):
        if r.method == "POST" and "/patients/" in r.url:
            key = r.headers.get("idempotency-key")
            if key:
                db_cleanup.append(key)
    page.on("request", on_request)

    # 1. Intake with missing scoreable vitals (HR + pain only; SpO2 / RR / SBP blank).
    page.goto(FRONTEND_URL)
    page.fill("input[name='name']", PATIENT_NAME)
    page.select_option("select[name='sex']", "M")
    page.fill("input[name='date_of_birth']", "1990-01-01")
    page.select_option("select[name='chief_complaint']", "cardiac")
    page.fill("input[name='heart_rate']", "80")
    page.fill("input[name='pain_level']", "2")
    page.click("button[type='submit']")
    expect(page.locator("li", has_text="Intake ID:")).to_be_visible()

    # 2. Wait for the scorer to finish (DB state check), then open the queue and
    #    click through to the patient's detail — no reload race.
    wait_for_scored(1)
    page.get_by_role("link", name="Triage Queue").click()
    expect(page.locator("h1", has_text="Triage Queue")).to_be_visible()
    name_link = page.locator("a.namelink", has_text=PATIENT_NAME)
    name_link.click()
    expect(page.locator("a.editbtn")).to_be_visible()  # detail loaded

    # 3. Detail -> Edit Patient.
    page.locator("a.editbtn").click()
    expect(page.locator("h1", has_text="Edit Patient")).to_be_visible()
    expect(page.locator("#oxygen_saturation")).to_be_visible()  # baseline loaded

    # 4. Fill the missing vitals (edit inputs are keyed by id, not name).
    page.fill("#oxygen_saturation", "97")
    page.fill("#respiration_rate", "18")
    page.fill("#blood_pressure_systolic", "120")

    # 5. Save & Recompute -> PATCH 200 -> the After column populates.
    with page.expect_response(
        lambda r: r.request.method == "PATCH" and "/intakes/" in r.url
    ) as save_resp:
        page.get_by_role("button", name="Save & Recompute").click()
    assert save_resp.value.status == 200
    expect(page.get_by_role("link", name="Done")).to_be_visible()
    expect(page.locator(".ba-col.after .pts")).to_contain_text("points")

    # 6. Back to the patient detail screen.
    page.get_by_role("link", name="Done").click()
    expect(page).to_have_url(re.compile(r"/intakes/\d+$"))
    expect(page.locator("a.editbtn")).to_be_visible()  # detail again
