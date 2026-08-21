"""
MC-MED visits.csv  ->  intake_records.json  (ranking-validation slice)

RUN LOCALLY. MC-MED data must not leave your machine (DUA).
This script only READS visits.csv and WRITES intake_records.json — no upload, no network.

Usage:
    python mcmed_extractor.py /path/to/visits.csv
    python mcmed_extractor.py /path/to/visits.csv --n 500 --out intake_records.json

Output: a JSON array of intake records in your IntakeCreate shape, PLUS two
ground-truth fields per record (true_esi, actual_outcome) held for validation.
Feed these through your unchanged scoring engine, then compare predicted ESI
to true_esi (under-triage rate, AUC on admit vs discharge).
"""

import csv, json, argparse, random, re
from collections import defaultdict, Counter
from datetime import date

# ----------------------------------------------------------------------
# 1. CONFIG — review the two mappings marked  # <-- REVIEW  before trusting output
# ----------------------------------------------------------------------

# Your ChiefComplaint enum values (the REAL ones)
VALID_KEYS = {"cardiac","respiratory","abdominal","stroke","syncope",
              "neuro","sepsis","trauma","weakness","minor_injury","minor_general","general"}

# Complaint weights (from your rule table) — used to pick ONE when a visit
# lists several complaints (highest weight wins). Ties resolved by list order.
COMPLAINT_WEIGHT = {
    "stroke":6, "cardiac":6, "trauma":5, "respiratory":4, "neuro":4, "sepsis":4,
    "syncope":3, "weakness":3, "abdominal":2, "minor_injury":1, "minor_general":1,
    "general":1,
}

# --- Free-text CC  ->  your enum.  # <-- REVIEW
# MC-MED 'CC' is free text, often UPPERCASE, sometimes comma-joined.
# Keys here are matched as substrings against the normalized CC text.
# Build this from the TOP ~50 actual CC values in your file (see the
# "unmapped CC" report this script prints) and extend as needed.
CC_TEXT_TO_KEY = {
    # cardiac
    "chest pain":"cardiac", "chest pressure":"cardiac", "palpitation":"cardiac",
    "cardiac":"cardiac",
    # respiratory
    "shortness of breath":"respiratory", "sob":"respiratory", "dyspnea":"respiratory",
    "difficulty breathing":"respiratory", "wheez":"respiratory", "respiratory":"respiratory",
    # stroke
    "stroke":"stroke", "facial droop":"stroke", "slurred speech":"stroke",
    "weakness one side":"stroke", "cva":"stroke",
    # neuro (headache / neuro)
    "headache":"neuro", "head ache":"neuro", "seizure":"neuro", "dizziness":"neuro",
    "confusion":"neuro", "altered mental":"neuro", "ams":"neuro",
    # syncope
    "syncope":"syncope", "fainting":"syncope", "passed out":"syncope",
    "loss of consciousness":"syncope",
    # abdominal
    "abdominal pain":"abdominal", "abd pain":"abdominal", "stomach pain":"abdominal",
    "nausea":"abdominal", "vomiting":"abdominal", "flank pain":"abdominal",
    # minor injury
    "laceration":"minor_injury", "fracture":"minor_injury", "sprain":"minor_injury",
    "injury":"minor_injury", "fall":"minor_injury", "cut":"minor_injury",
    "burn":"minor_injury", "wound":"minor_injury",
    # minor general
    "rash":"minor_general", "med refill":"minor_general", "medication refill":"minor_general",
    "cold":"minor_general", "sore throat":"minor_general", "cough":"minor_general",
    "uri":"minor_general",
    # 2nd pass: confident
    "breathing problem":"respiratory",
    "emesis":"abdominal", "melena":"abdominal", "diarrhea":"abdominal",
    "irregular heart beat":"cardiac",
    "numbness":"neuro",
    "back pain":"minor_injury", "leg pain":"minor_injury", "knee pain":"minor_injury",
    "hip pain":"minor_injury", "foot pain":"minor_injury", "arm pain":"minor_injury",
    "shoulder pain":"minor_injury", "neck pain":"minor_injury",
    "eye problem":"minor_general", "eye pain":"minor_general", "ear pain":"minor_general",
    "swab only":"minor_general", "allergic reaction":"minor_general", "referral":"minor_general",
    # Tier-A: sepsis / trauma / weakness (high-acuity carve-outs from general)
    "fever":"sepsis", "chills":"sepsis", "abnormal lab":"sepsis",
    "trauma":"trauma", "automobile versus pedestrian":"trauma", "assault":"trauma",
    "general weakness":"weakness", "fatigue":"weakness",
    # 2nd pass: judgement
    "vaginal bleeding":"abdominal",
    "hypertension":"general",
    "alcohol intoxication":"general",
    "problem psych":"general",
    "edema":"general",
    "multiple complaints":"general",
    "feeding tube":"minor_general",
    # 3rd pass: clear-ish
    "ankle pain":"minor_injury", "finger lac":"minor_injury", "groin pain":"minor_injury",
    "hand pain":"minor_injury", "toe pain":"minor_injury", "rib pain":"minor_injury",
    "dental pain":"minor_general", "throat pain":"minor_general",
    "epistaxis":"minor_general",           # nosebleed
    "constipation":"abdominal", "rectal pain":"abdominal", "epigastric pain":"abdominal",
    "pelvic pain":"abdominal",
    "neurologic problem":"neuro", "lethargy":"neuro",
    "hypotension":"cardiac",               # low BP as CC - concerning
    "skin abscess":"minor_general",
    "rapid heart rate":"cardiac",
    "blood in vomit":"abdominal",
    "vision change":"neuro", "blurred vision":"neuro",
    "blood in stool":"abdominal",
    "hemoptysis":"respiratory",
    "finger pain":"minor_injury","wrist pain": "minor_injury","dog bite": "minor_injury",
    "lac other": "minor_injury","jaw/facial pain": "minor_injury",
    "immunization/injection": "minor_general", "skin_problem": "minor_general",
    "abcess": "minor_general", "abscess": "minor_general", "breast pain": "minor_general"
}

# --- ED_dispo  ->  your actual_outcome enum.  # <-- REVIEW
# Fill/adjust after eyeballing the REAL distinct ED_dispo values this script prints.
# Your enum: admitted / icu / discharged / died / transferred
DISPO_TO_OUTCOME = {
    "discharge":"discharged",
    "admit":"admitted",
    "admitted":"admitted",
    "icu":"icu",
    "transfer":"transferred",
    "expired":"died",
    "deceased":"died",
    "death":"died",
    "ama":"discharged",          # left against medical advice -> treat as discharged (adjust if you prefer)
    "eloped":"discharged",
    "observation":"admitted",    # obs status -> admitted (adjust to taste)
    "inpatient":"admitted",
}

# ----------------------------------------------------------------------
# 2. HELPERS
# ----------------------------------------------------------------------

def parse_esi(raw):
    """'3-Urgent' -> 3 ; returns None if unparseable."""
    if raw is None: return None
    m = re.match(r"\s*([1-5])", str(raw))
    return int(m.group(1)) if m else None

def c_to_f(c):
    try: return round(float(c)*9/5+32, 1)
    except (TypeError, ValueError): return None

def to_int(x):
    try:
        v = float(x)
        return int(round(v))
    except (TypeError, ValueError):
        return None

def to_float(x):
    try: return float(x)
    except (TypeError, ValueError): return None

def norm(s):
    return re.sub(r"\s+", " ", str(s or "").strip().lower())

def map_cc(cc_raw):
    """Free-text CC -> one enum key (highest weight among matches). Returns (key, matched_bool)."""
    text = norm(cc_raw)
    if not text:
        return "general", False
    hits = []
    for phrase, key in CC_TEXT_TO_KEY.items():
        if phrase in text:
            hits.append(key)
    if not hits:
        return "general", False          # unmapped -> general, flagged
    # pick highest-weight complaint
    best = max(hits, key=lambda k: COMPLAINT_WEIGHT.get(k, 0))
    return best, True

def map_dispo(dispo_raw, admit_service=None):
    d = norm(dispo_raw)
    # ICU detection via admit service if disposition is a generic 'admit'
    if admit_service and "icu" in norm(admit_service):
        return "icu"
    for phrase, out in DISPO_TO_OUTCOME.items():
        if phrase in d:
            return out
    return None                          # unmapped -> leave null

def age_to_dob(age_raw):
    a = to_int(age_raw)
    if a is None:
        return None
    return date(date.today().year - a, 1, 1).isoformat()   # Jan 1, approx

# Psych / behavioral complaints are OUT OF SCOPE for the engine — filtered out
# here so they never reach scoring. Toxicology (overdose, intoxication) is a
# MEDICAL emergency, not psych, and is deliberately NOT filtered. Matched as
# substrings against the normalized CC text.
PSYCH_CC = [
    "psych", "suicid", "homicid", "anxiety", "panic attack",
    "depress", "hallucinat", "agitat", "behavioral",
]

def is_psych(cc_raw):
    text = norm(cc_raw)
    return any(p in text for p in PSYCH_CC)

# core vitals required for a usable validation row
CORE_VITALS = ["heart_rate","blood_pressure_systolic","oxygen_saturation","respiration_rate"]

def plausible(rec):
    """Drop sentinel / impossible values in place; return rec."""
    hr = rec["heart_rate"];           rec["heart_rate"]        = hr if hr and 10 <= hr <= 300 else None
    rr = rec["respiration_rate"];     rec["respiration_rate"]  = rr if rr and 3 <= rr <= 80 else None
    sp = rec["oxygen_saturation"];    rec["oxygen_saturation"] = sp if sp and 50 <= sp <= 100 else None
    sb = rec["blood_pressure_systolic"];  rec["blood_pressure_systolic"]  = sb if sb and 40 <= sb <= 300 else None
    db = rec["blood_pressure_diastolic"]; rec["blood_pressure_diastolic"] = db if db and 20 <= db <= 200 else None
    return rec

# ----------------------------------------------------------------------
# 3. MAIN
# ----------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_path")
    ap.add_argument("--n", type=int, default=500, help="target slice size (stratified by ESI)")
    ap.add_argument("--out", default="intake_records.json")
    ap.add_argument("--sampling", choices=["balanced","representative"], default="balanced")
    args = ap.parse_args()

    rows = []
    dispo_values = Counter()
    unmapped_cc = Counter()
    esi_counts = Counter()
    total = 0
    psych_filtered = 0

    with open(args.csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            total += 1
            true_esi = parse_esi(r.get("Triage_acuity"))
            if true_esi is None:
                continue

            # Psych/behavioral complaints are out of scope — drop before scoring.
            if is_psych(r.get("CC")):
                psych_filtered += 1
                continue

            cc_key, matched = map_cc(r.get("CC"))
            if not matched:
                unmapped_cc[norm(r.get("CC"))[:40]] += 1

            rec = {
                # --- intake fields (your IntakeCreate shape) ---
                "date_of_birth": age_to_dob(r.get("Age")),
                "chief_complaint": cc_key,
                "heart_rate": to_int(r.get("Triage_HR")),
                "blood_pressure_systolic": to_int(r.get("Triage_SBP")),
                "blood_pressure_diastolic": to_int(r.get("Triage_DBP")),
                "temperature": c_to_f(r.get("Triage_Temp")),          # C -> F
                "oxygen_saturation": to_int(r.get("Triage_SpO2")),
                "respiration_rate": to_int(r.get("Triage_RR")),
                "pain_level": None,          # not in visits.csv (in continuous vitals table; optional join later)
                "blood_sugar": None,         # not at triage
                "symptoms": [],
                "source": "form",            # ingestion path; MC-MED is CSV, treat as form-equivalent (NOT 'mc_med')
                "external_patient_id": None,
                "pregnancy_status": "none",  # default 'none'; overridden to 'pregnant' from Dx below
                "pre_existing_conditions": None,
                "arrival_by_ambulance": ("ambul" in norm(r.get("Means_of_arrival")) or "ems" in norm(r.get("Means_of_arrival"))) or None,
                "recent_ed_visit_72h": None,
                "injury_related": None,
                # --- ground truth (NOT fed to the scorer) ---
                "actual_outcome": map_dispo(r.get("ED_dispo"), r.get("Admit_service")),
                "outcome_source": "mc_med",  # <-- the correct field for tagging MC-MED origin
                "true_esi": true_esi,        # parsed from Triage_acuity — the validation target
            }

            # pregnancy from primary ICD10 (O-codes), sparse — null when absent
            icd10 = norm(r.get("Dx_ICD10"))
            if icd10.startswith("o"):
                rec["pregnancy_status"] = "pregnant"

            rec = plausible(rec)

            # require core vitals present
            if any(rec[v] is None for v in CORE_VITALS):
                continue

            dispo_values[norm(r.get("ED_dispo"))] += 1
            esi_counts[true_esi] += 1
            rows.append(rec)

    # ---- stratified sample by true_esi ----
    random.seed(42)
    if args.sampling == "balanced":
        by_esi = defaultdict(list)
        for rec in rows:
            by_esi[rec["true_esi"]].append(rec)
        per_band = max(1, args.n // 5)
        sample = []
        for esi in [1,2,3,4,5]:
            pool = by_esi.get(esi, [])
            random.shuffle(pool)
            sample.extend(pool[:per_band])
        random.shuffle(sample)
    else:  # representative
        sample = random.sample(rows, min(args.n, len(rows)))

    with open(args.out, "w") as f:
        json.dump(sample, f, indent=2)

    # ---- report ----
    print(f"Total CSV rows:              {total}")
    print(f"Psych filtered (out of scope):{psych_filtered}")
    print(f"Usable (ESI + core vitals):  {len(rows)}")
    if args.sampling == "balanced":
        print(f"Sampled (balanced):          {len(sample)}  (~{per_band}/band)")
    else:
        print(f"Sampled (representative):    {len(sample)}  (real-ED proportions)")
    print(f"\nESI distribution (usable pool): {dict(sorted(esi_counts.items()))}")
    print(f"\nDistinct ED_dispo values seen (map these in DISPO_TO_OUTCOME):")
    for v,n in dispo_values.most_common():
        print(f"   {n:6}  {v}")
    print(f"\nTop UNMAPPED CC text (add to CC_TEXT_TO_KEY to raise coverage):")
    for v,n in unmapped_cc.most_common(30):
        print(f"   {n:6}  {v}")
    unmatched_total = sum(unmapped_cc.values())
    print(f"\nUnmapped CC rows: {unmatched_total} (these became 'general')")
    print(f"\nWrote {args.out}. Feed through your engine; compare predicted ESI to true_esi.")

if __name__ == "__main__":
    main()
