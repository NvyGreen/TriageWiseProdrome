"""
Pull a FHIR dataset from Epic's public sandbox using SMART on FHIR
"Standalone Launch" OAuth2 (Authorization Code + PKCE).

WHAT THIS DOES
1. Opens your browser to Epic's sandbox login page.
2. You log in as one of Epic's fake test patients (see SETUP.md).
3. Epic redirects back to a tiny local web server this script starts,
   handing over an authorization `code`.
4. The script exchanges that code for an access token.
5. It uses the token to call the FHIR R4 API and saves the results
   (Patient, Condition, Encounter, Observation) as JSON files in ./fhir_data/.

BEFORE RUNNING
- Register a free app at https://fhir.epic.com (see SETUP.md for exact steps).
- Set CLIENT_ID below to your app's "Non-Production Client ID".
- Make sure the redirect URI registered on fhir.epic.com is exactly:
      http://localhost:8080/callback
- pip install requests --break-system-packages   (if not already installed)
"""

import base64
import hashlib
import http.server
import json
import os
import secrets
import threading
import urllib.parse
import webbrowser

import requests
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# CONFIG — edit this section
# ---------------------------------------------------------------------------
load_dotenv()
CLIENT_ID = os.environ["FHIR_CLIENT_ID"]

REDIRECT_URI = "http://localhost:8080/callback"

# Epic's public non-production (sandbox) endpoints — stable, no need to change.
AUTHORIZE_URL = "https://fhir.epic.com/interconnect-fhir-oauth/oauth2/authorize"
TOKEN_URL = "https://fhir.epic.com/interconnect-fhir-oauth/oauth2/token"
FHIR_BASE_URL = "https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4"

# Scopes: ask for the resource types you want to read for the patient.
SCOPES = (
    "openid fhirUser "
    "patient/Patient.read "
    "patient/Encounter.read "
    "patient/Condition.read "
    "patient/Observation.read"
)

# Patient
# Encounter (Outside Record & Patient Chart)
# Observation (Vital Signs)
# Condition (Reason for Visit & Problems)

# Resources to fetch once we have a token + patient id, as
# (output filename, resource type, extra search params).
# Epic rejects an Observation search without a `category`, and each category
# is a separate permission on the app registration, so they're fetched one at
# a time into their own files.
RESOURCE_TYPES = [
    ("Condition", "Condition", {}),
    ("Encounter", "Encounter", {}),
    ("Observation_vitals", "Observation", {"category": "vital-signs"}),
]

OUTPUT_DIR = "fhir_data"

# ---------------------------------------------------------------------------
# PKCE helpers
# ---------------------------------------------------------------------------
def make_pkce_pair():
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(40)).rstrip(b"=").decode()
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    return verifier, challenge


# ---------------------------------------------------------------------------
# Tiny local server to catch the OAuth redirect
# ---------------------------------------------------------------------------
class _CallbackResult:
    code = None
    error = None


def _make_handler(state_expected):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != "/callback":
                self.send_response(404)
                self.end_headers()
                return
            params = urllib.parse.parse_qs(parsed.query)
            if params.get("state", [None])[0] != state_expected:
                _CallbackResult.error = "State mismatch — possible CSRF, aborting."
            elif "code" in params:
                _CallbackResult.code = params["code"][0]
            else:
                _CallbackResult.error = params.get("error_description", ["Unknown error"])[0]

            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            msg = "Login complete — you can close this tab and return to the terminal."
            if _CallbackResult.error:
                msg = f"Error: {_CallbackResult.error}"
            self.wfile.write(f"<html><body><h2>{msg}</h2></body></html>".encode())

        def log_message(self, *args):
            pass  # silence default request logging

    return Handler


def get_authorization_code():
    state = secrets.token_urlsafe(16)
    verifier, challenge = make_pkce_pair()

    auth_params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "state": state,
        "aud": FHIR_BASE_URL,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    auth_url = f"{AUTHORIZE_URL}?{urllib.parse.urlencode(auth_params)}"

    server = http.server.HTTPServer(("localhost", 8080), _make_handler(state))
    thread = threading.Thread(target=server.handle_request)  # serves exactly one request
    thread.start()

    print("Opening browser for Epic sandbox login...")
    print("Log in with one of the test patient credentials from SETUP.md.")
    webbrowser.open(auth_url)

    thread.join(timeout=300)
    server.server_close()

    if _CallbackResult.error:
        raise RuntimeError(_CallbackResult.error)
    if not _CallbackResult.code:
        raise RuntimeError("Timed out waiting for login/redirect.")

    return _CallbackResult.code, verifier


def exchange_code_for_token(code, verifier):
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": CLIENT_ID,
        "code_verifier": verifier,
    }
    resp = requests.post(TOKEN_URL, data=data, headers={"Accept": "application/json"})
    resp.raise_for_status()
    return resp.json()


def fetch_resource(access_token, resource_type, patient_id, extra_params=None):
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/fhir+json",
    }
    if resource_type == "Patient":
        url = f"{FHIR_BASE_URL}/Patient/{patient_id}"
    else:
        query = {"patient": patient_id, **(extra_params or {})}
        url = f"{FHIR_BASE_URL}/{resource_type}?{urllib.parse.urlencode(query)}"

    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    return resp.json()


def main():
    if "PASTE_YOUR" in CLIENT_ID:
        raise SystemExit(
            "Set CLIENT_ID at the top of this script to your Epic on FHIR "
            "Non-Production Client ID first. See SETUP.md."
        )

    code, verifier = get_authorization_code()
    token_response = exchange_code_for_token(code, verifier)

    access_token = token_response["access_token"]
    patient_id = token_response.get("patient")
    if not patient_id:
        raise RuntimeError(
            "No 'patient' field in token response — check your scopes include "
            "patient-level read scopes."
        )

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print(f"Authenticated. Contextual patient FHIR ID: {patient_id}")

    # Epic echoes back the scopes it ACTUALLY granted, which is authoritative:
    # requested-but-not-registered scopes are dropped here, silently.
    print(f"Granted scopes: {token_response.get('scope', '(none reported)')}")

    patient = fetch_resource(access_token, "Patient", patient_id)
    with open(os.path.join(OUTPUT_DIR, "Patient.json"), "w") as f:
        json.dump(patient, f, indent=2)
    print("Saved Patient.json")

    for name, rtype, params in RESOURCE_TYPES:
        try:
            bundle = fetch_resource(access_token, rtype, patient_id, params)
            with open(os.path.join(OUTPUT_DIR, f"{name}.json"), "w") as f:
                json.dump(bundle, f, indent=2)
            count = bundle.get("total", len(bundle.get("entry", [])))
            print(f"Saved {name}.json ({count} entries)")
        except requests.HTTPError as e:
            # Epic explains *why* in an OperationOutcome body — surface it,
            # since a bare 403 usually means the API wasn't enabled on the
            # app registration at fhir.epic.com.
            # Epic often returns permission 403s with an empty body, so fall
            # back to the status line and any diagnostic headers it did send.
            r = e.response
            print(f"Skipped {name}: {r.status_code} {r.reason}  ({r.url})")
            body = r.text.strip()
            print(f"  Body: {body[:1000] if body else '(empty)'}")
            interesting = {
                k: v for k, v in r.headers.items()
                if any(t in k.lower() for t in ("error", "epic", "warn", "www-authenticate"))
            }
            if interesting:
                print(f"  Headers: {interesting}")

    print(f"\nDone. Data saved to ./{OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
