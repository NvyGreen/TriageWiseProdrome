"""Browser E2E for the Epic FHIR import tab on the Demo Tools page.

The frontend POSTs to /demo/fhir/{id}, which on the server calls the real Epic
sandbox (needs a private key + network) — wrong to hit in a test. So the request
is stubbed in the browser with page.route: this exercises the frontend flow
(fetch -> mapping render, and the error path) with no network, no key, and no DB
writes. The backend adapter + pull are covered by the pytest suite.

Isolation: this test never reaches the backend for the FHIR call (page.route
fulfills it) and writes nothing, so it needs no db_cleanup or scorer wait.
"""
import json

from playwright.sync_api import Page, expect

FRONTEND_URL = "http://localhost:5173"

# Mirrors epic_fhir_adapter.build_intake output (the endpoint's payload), wrapped
# in the app's {payload, meta} envelope that the frontend unwraps. chief_complaint
# is None (the sandbox rarely maps one) so the mapping shows a "not in record" row.
DRAFT = {
    "name": "ZZTEST FHIR Patient",
    "date_of_birth": "1980-05-17",
    "chief_complaint": None,
    "heart_rate": 88,
    "blood_pressure_systolic": 120,
    "blood_pressure_diastolic": 78,
    "temperature": 98.6,
    "oxygen_saturation": 98,
    "respiration_rate": 16,
    "pain_level": 4,
    "blood_sugar": None,
    "missing_fields": ["chief_complaint", "blood_sugar"],
    "source": "fhir",
    "external_patient_id": "abc123",
}


def _open_fhir_tab(page: Page):
    page.goto(FRONTEND_URL)
    page.get_by_role("link", name="Demo Tools").click()
    expect(page.locator("h1", has_text="Demo Tools")).to_be_visible()
    page.get_by_role("tab", name="Epic FHIR import").click()


def test_fhir_import_maps_record(page: Page):
    def fulfill(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"payload": DRAFT, "meta": {"disclaimer": "Not medical advice."}}),
        )
    page.route("**/demo/fhir/**", fulfill)

    _open_fhir_tab(page)
    page.get_by_role("button", name="Fetch & map").click()

    # Header shows the patient name; a present vital maps; the null field is flagged.
    expect(page.locator(".outhead .meta")).to_contain_text("ZZTEST FHIR Patient")
    expect(page.locator(".maprow", has_text="heart_rate")).to_contain_text("88 bpm")
    expect(
        page.locator(".maprow", has_text="Encounter.reasonCode").locator(".v.missing")
    ).to_have_text("not in record")


def test_fhir_import_shows_error(page: Page):
    def fulfill(route):
        route.fulfill(
            status=500,
            content_type="application/json",
            body=json.dumps(
                {"error": {"code": "internal_error", "message": "FHIR sandbox retrieval failed."}}
            ),
        )
    page.route("**/demo/fhir/**", fulfill)

    _open_fhir_tab(page)
    page.get_by_role("button", name="Fetch & map").click()

    expect(page.locator(".loaderror")).to_contain_text("FHIR sandbox retrieval failed.")
