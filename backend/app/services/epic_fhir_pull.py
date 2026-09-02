"""
Pull a patient's FHIR R4 resources from the Epic sandbox with NO browser and NO
user login, using SMART on FHIR "Backend Services" (OAuth2 client_credentials +
signed JWT assertion).

TWO WAYS THIS MODULE IS USED
  As a service  -> `fetch_patient_fhir(patient_id)` returns the bundles in memory,
                   keyed for `epic_fhir_adapter.build_intake`. This is the path
                   behind POST /demo/fhir/{fhir_id}; it writes nothing to disk or
                   to the database.
  As a CLI      -> `python -m app.services.epic_fhir_pull` pulls the patients
                   listed in PATIENT_IDS / PATIENT_NAMES below and saves each
                   bundle to disk. Useful for inspecting raw sandbox payloads
                   while extending the adapter.

WHY client_credentials
  There is no human in the loop, so the app proves its own identity by signing a
  short-lived JWT with its private key instead of presenting a stored secret. The
  trade-off: because nobody logs in, the token response carries no `patient`
  field — the caller must name the patient, by FHIR ID or by name search.

SETUP
  Requires a registered Epic *Backend Systems* app, an RSA key pair in keys/, and
  FHIR_CLIENT_ID in backend/.env. See "Epic FHIR setup" in the project README for
  the full sequence, including Epic's ~60-minute key-sync delay (until it
  completes, every token request fails with "invalid client" no matter what).
  Runtime dependencies (requests, pyjwt, cryptography) are in requirements.in.
"""

import json
import os
import time
import uuid
from pathlib import Path

import jwt
import requests

# ---------------------------------------------------------------------------
# CONFIG — edit this section
# ---------------------------------------------------------------------------

# The Non-Production Client ID of the *Backend Systems* app comes from settings
# (FHIR_CLIENT_ID in .env), read lazily via _client_id() so importing this module
# never requires app settings to be configured.

# Resolve the key + JWKS paths relative to THIS file, so they work no matter what
# the process cwd is (e.g. uvicorn serving the app from backend/).
_HERE = Path(__file__).resolve().parent

PRIVATE_KEY_PATH = os.environ.get("EPIC_PRIVATE_KEY", str(_HERE / "keys" / "private_key.pem"))

# The published JWKS (public key only). Used here to read back the `kid`, which
# must appear in the JWT header so Epic can pick the right key out of the set.
# Lives outside keys/ because it's the one file here that is meant to be public
# and committed — keys/ itself is gitignored.
JWKS_PATH = str(_HERE / "jwks.json")

# Epic's public non-production (sandbox) endpoints.
TOKEN_URL = "https://fhir.epic.com/interconnect-fhir-oauth/oauth2/token"
FHIR_BASE_URL = "https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4"

# Which patients to pull. Two ways, use either or both:
#
#   PATIENT_IDS   — exact Epic FHIR IDs, fastest and most reliable.
#   PATIENT_NAMES — (family, given) pairs; the script searches for the ID first.
#
# The IDs below are Epic's long-standing public sandbox test patients. If one
# 404s, Epic reshuffled it — fall back to PATIENT_NAMES, or check the current
# list under Documentation -> Sandbox on fhir.epic.com.
PATIENT_IDS = [
    "erXuFYUfucBZaryVksYEcMg3",  # Camila Lopez
    "eq081-VQEgP8drUUqCWzHfw3",  # Derrick Lin
]

PATIENT_NAMES = [
    # ("Lopez", "Camila"),
    # ("Lin", "Derrick"),
]

# (label, FHIR resource type, extra search params).
#
# The label names the output file, so the same resource type can appear more
# than once with different params — Epic requires a category on some searches
# rather than returning everything, and it authorizes those categories
# separately. Asking for a category your app can't search returns nothing
# rather than an error, so pull them one at a time and you can see which
# came back empty.
RESOURCE_TYPES = [
    ("Condition", "Condition", {}),
    ("Encounter", "Encounter", {}),
    ("Observation_vitals", "Observation", {"category": "vital-signs"}),
]

OUTPUT_DIR = "fhir_data_backend"

# Epic caps the assertion lifetime at 5 minutes.
ASSERTION_LIFETIME_SECONDS = 240


# ---------------------------------------------------------------------------
# Authentication — this is the part that replaces the browser login
# ---------------------------------------------------------------------------
class FHIRRetrievalException(Exception):
    """Raised when pulling a patient's FHIR data fails (auth or HTTP error)."""


def _client_id() -> str:
    """The Backend Systems client ID, from settings (FHIR_CLIENT_ID). Imported
    lazily so this module can be imported without app settings configured."""
    from ..config import get_settings
    return get_settings().FHIR_CLIENT_ID


def read_kid():
    """Read the key ID from the JWKS we published, if there is one.

    Epic fetches your JWK Set URL and needs to know which key in the set signed
    the assertion. That's the `kid`, and it goes in the JWT *header*, not the
    claims. Without it Epic may reject the assertion even though the signature
    is perfectly valid.
    """
    if not os.path.exists(JWKS_PATH):
        return None
    with open(JWKS_PATH, encoding="utf-8") as f:
        keys = json.load(f).get("keys", [])
    return keys[0].get("kid") if keys else None


def build_client_assertion():  # pragma: no cover - JWT signing, needs a real key
    """Build and sign the JWT that proves we are CLIENT_ID.

    Epic verifies the signature against the public key it fetched from your
    JWK Set URL. That's how the app authenticates with no secret and no human.
    """
    with open(PRIVATE_KEY_PATH, "rb") as f:
        private_key = f.read()

    cid = _client_id()
    now = int(time.time())
    claims = {
        "iss": cid,                       # who is asserting
        "sub": cid,                       # who the assertion is about (same app)
        "aud": TOKEN_URL,                 # must match Epic's token endpoint exactly
        "jti": str(uuid.uuid4()),         # unique per request; Epic rejects replays
        "iat": now,
        "nbf": now,
        "exp": now + ASSERTION_LIFETIME_SECONDS,
    }

    kid = read_kid()
    headers = {"kid": kid} if kid else None

    # RS384 is what the SMART Backend Services spec mandates.
    return jwt.encode(claims, private_key, algorithm="RS384", headers=headers)


def get_access_token():  # pragma: no cover - network call to Epic's token endpoint
    assertion = build_client_assertion()
    data = {
        "grant_type": "client_credentials",
        "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
        "client_assertion": assertion,
    }
    resp = requests.post(
        TOKEN_URL,
        data=data,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        timeout=30,
    )

    if resp.status_code != 200:
        raise RuntimeError(
            f"Token request failed ({resp.status_code}): {resp.text}\n\n"
            "Common causes:\n"
            "  - Less than ~60 min since you saved the app. Epic syncs app\n"
            "    changes to the sandbox on a timer.\n"
            "  - CLIENT_ID is the Production one. Use the NON-Production one.\n"
            "  - Epic can't reach your JWK Set URL, or it doesn't return raw\n"
            "    JSON. Open the URL in a private browser window to check.\n"
            "  - The published jwks.json doesn't match keys/private_key.pem.\n"
            "    Regenerate the JWKS from the current public key and re-publish.\n"
            "  - The app has no Read APIs selected."
        )

    payload = resp.json()
    print(f"Got access token, valid {payload.get('expires_in', '?')}s.")
    return payload["access_token"]


# ---------------------------------------------------------------------------
# FHIR calls
# ---------------------------------------------------------------------------
def fhir_get(access_token, url, params=None):  # pragma: no cover - network call
    resp = requests.get(
        url,
        params=params,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/fhir+json",
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_bundle(access_token, resource_type, patient_id, extra_params=None):  # pragma: no cover - network call
    """Fetch a search bundle, following `next` links so we get every page."""
    params = {"patient": patient_id}
    params.update(extra_params or {})

    bundle = fhir_get(access_token, f"{FHIR_BASE_URL}/{resource_type}", params)
    entries = bundle.get("entry", [])

    next_url = _next_link(bundle)
    while next_url:
        page = fhir_get(access_token, next_url)
        entries.extend(page.get("entry", []))
        next_url = _next_link(page)

    bundle["entry"] = entries
    bundle["total"] = len(entries)
    bundle.pop("link", None)  # paging links are meaningless once merged
    return bundle


def _next_link(bundle):  # pragma: no cover - paging helper for the network fetch
    for link in bundle.get("link", []):
        if link.get("relation") == "next":
            return link.get("url")
    return None


def find_patient_id(access_token, family, given):  # pragma: no cover - network call, CLI-only
    bundle = fhir_get(
        access_token, f"{FHIR_BASE_URL}/Patient", {"family": family, "given": given}
    )
    entries = bundle.get("entry", [])
    if not entries:
        raise RuntimeError(f"No patient found for {given} {family}")
    return entries[0]["resource"]["id"]


def fetch_patient_fhir(patient_id):
    """Pull one patient's FHIR resources into memory (no disk writes) and return
    them keyed for epic_fhir_adapter.build_intake:

        {"patient", "vitals", "condition", "encounter"}

    Raises FHIRRetrievalException if authentication (RuntimeError) or any FHIR
    call (requests.HTTPError) fails, so callers can map it to one error response."""
    try:
        access_token = get_access_token()
        patient = fhir_get(access_token, f"{FHIR_BASE_URL}/Patient/{patient_id}")
        vitals = fetch_bundle(access_token, "Observation", patient_id, {"category": "vital-signs"})
        condition = fetch_bundle(access_token, "Condition", patient_id)
        encounter = fetch_bundle(access_token, "Encounter", patient_id)
    except (RuntimeError, requests.HTTPError) as e:
        raise FHIRRetrievalException(str(e)) from e

    return {
        "patient": patient,
        "vitals": vitals,
        "condition": condition,
        "encounter": encounter,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def save(obj, *path_parts):  # pragma: no cover - CLI disk write
    path = os.path.join(OUTPUT_DIR, *path_parts)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)
    return path


def pull_patient(access_token, patient_id):  # pragma: no cover - CLI orchestration
    print(f"\nPatient {patient_id}")

    patient = fhir_get(access_token, f"{FHIR_BASE_URL}/Patient/{patient_id}")
    save(patient, patient_id, "Patient.json")
    name = patient.get("name", [{}])[0].get("text", "(no name)")
    print(f"  Patient.json — {name}")

    for label, rtype, extra in RESOURCE_TYPES:
        try:
            bundle = fetch_bundle(access_token, rtype, patient_id, extra)
            save(bundle, patient_id, f"{label}.json")
            print(f"  {label}.json — {bundle['total']} entries")
        except requests.HTTPError as e:
            print(f"  {label} skipped: {e}")


def main():  # pragma: no cover - CLI entrypoint
    if not _client_id():
        raise SystemExit(
            "Set FHIR_CLIENT_ID in .env to the Non-Production Client ID of your "
            "Backend Systems app. See 'Epic FHIR setup' in the project README."
        )
    if not os.path.exists(PRIVATE_KEY_PATH):
        raise SystemExit(
            f"{PRIVATE_KEY_PATH} not found. Generate an RSA key pair into that "
            "directory — see 'Epic FHIR setup' in the project README."
        )

    access_token = get_access_token()

    patient_ids = list(PATIENT_IDS)
    for family, given in PATIENT_NAMES:
        try:
            found = find_patient_id(access_token, family, given)
            print(f"Resolved {given} {family} -> {found}")
            patient_ids.append(found)
        except (requests.HTTPError, RuntimeError) as e:
            print(f"Could not resolve {given} {family}: {e}")

    if not patient_ids:
        raise SystemExit(
            "No patients configured. Fill in PATIENT_IDS or PATIENT_NAMES."
        )

    for patient_id in dict.fromkeys(patient_ids):  # de-dupe, keep order
        try:
            pull_patient(access_token, patient_id)
        except requests.HTTPError as e:
            print(f"\nPatient {patient_id} failed: {e}")

    print(f"\nDone. Data saved under ./{OUTPUT_DIR}/")


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    main()
