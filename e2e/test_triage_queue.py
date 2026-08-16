"""Browser E2E for the Triage Queue page.

Flow: add three patients via the intake form (with a deliberate ESI spread),
navigate to the queue via the navbar, assert they're ordered most-acute first,
then disposition the middle one and assert it drops out of the active queue.

Isolation: the `backend` fixture is module-scoped, so this file gets a FRESH
backend with an empty in-memory queue — the three patients here are the only
entries. `db_cleanup` removes the ZZTEST rows + idempotency keys; the orphaned
queue entries die with the module's backend process.
"""
from playwright.sync_api import Page, expect

FRONTEND_URL = "http://localhost:5173"

# Three intakes with a clear acuity spread so queue order is deterministic:
#   A cardiac + danger vitals -> ESI-1, B cardiac + normal -> ESI-2,
#   C minor complaint -> ESI-4/5. Expected top-to-bottom order: A, B, C.
PATIENTS = [
    ("ZZTEST Queue A", "cardiac",
     {"heart_rate": 135, "oxygen_saturation": 88, "respiration_rate": 28,
      "blood_pressure_systolic": 92, "pain_level": 9}),
    ("ZZTEST Queue B", "cardiac",
     {"heart_rate": 80, "oxygen_saturation": 98, "respiration_rate": 16,
      "blood_pressure_systolic": 120, "pain_level": 2}),
    ("ZZTEST Queue C", "minor_general",
     {"heart_rate": 78, "oxygen_saturation": 99, "respiration_rate": 14,
      "blood_pressure_systolic": 118, "pain_level": 0}),
]


def _submit_intake(page: Page, name: str, complaint: str, vitals: dict):
    page.fill("input[name='name']", name)
    page.select_option("select[name='sex']", "M")  # Male -> no pregnancy field
    page.fill("input[name='date_of_birth']", "1990-01-01")
    page.select_option("select[name='chief_complaint']", complaint)
    for field, value in vitals.items():
        page.fill(f"input[name='{field}']", str(value))
    page.click("button[type='submit']")
    # Success feedback confirms the 201 (and the queue insert) landed.
    expect(page.locator("li", has_text="Intake ID:")).to_be_visible()


def _row_order(page: Page) -> list[str]:
    """Names of the ZZTEST patients in table order."""
    texts = page.locator("tbody tr").all_inner_texts()
    return [t for t in texts if "ZZTEST Queue" in t]


def test_queue_orders_and_dispositions(page: Page, db_cleanup):
    def on_request(r):
        if r.method == "POST" and "/patients/" in r.url:
            key = r.headers.get("idempotency-key")
            if key:
                db_cleanup.append(key)
    page.on("request", on_request)

    # 1. Add the three patients via the intake form.
    page.goto(FRONTEND_URL)
    for name, complaint, vitals in PATIENTS:
        _submit_intake(page, name, complaint, vitals)

    # 2. Navigate to the queue via the navbar; the three should load in order.
    page.get_by_role("link", name="Triage Queue").click()
    expect(page.locator("h1", has_text="Triage Queue")).to_be_visible()
    rows = page.locator("tbody tr")
    expect(rows).to_have_count(3)

    order = _row_order(page)
    idx = lambda sub: next(i for i, t in enumerate(order) if sub in t)
    # Ordered most-acute first: A (ESI-1) -> B (ESI-2) -> C (ESI-4/5).
    assert idx("Queue A") < idx("Queue B") < idx("Queue C"), order

    # 3. Disposition the middle patient -> it leaves the active queue.
    b_row = page.locator("tbody tr", has_text="ZZTEST Queue B")
    b_row.locator("select[name='status']").select_option("DISPOSITIONED")

    # B disappears (Show completed is off); A and C remain. A revert on API
    # failure would bring B back, so count 0 also proves the PATCH succeeded.
    expect(page.locator("tbody tr", has_text="ZZTEST Queue B")).to_have_count(0)
    expect(page.locator("tbody tr", has_text="ZZTEST Queue A")).to_have_count(1)
    expect(page.locator("tbody tr", has_text="ZZTEST Queue C")).to_have_count(1)
    # No error banner -> the disposition PATCH was accepted, not reverted.
    expect(page.locator(".banner[role='alert']")).to_have_count(0)
