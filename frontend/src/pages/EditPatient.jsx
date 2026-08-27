import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Lock, SquarePen, ClipboardList, ArrowRight, CircleAlert } from "lucide-react";

import "./EditPatient.css";


const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;

// This screen needs the intake only, so black-box is enough — and it avoids
// logging an explanation_viewed event the clinician never asked for.
const DETAIL_URL = (intakeId) => `${API_BASE_URL}/intakes/${intakeId}?mode=blackbox`;

// Exactly the fields IntakeUpdate accepts, with its Field() bounds.
const VITAL_FIELDS = [
    { name: "heart_rate", label: "Heart Rate", unit: "bpm", min: 1, max: 350, step: 1, integer: true },
    { name: "respiration_rate", label: "Respiratory Rate", unit: "/ min", min: 1, max: 99, step: 1, integer: true },
    { name: "blood_pressure_systolic", label: "Blood Pressure — Systolic", unit: "mmHg", min: 1, max: 300, step: 1, integer: true },
    { name: "blood_pressure_diastolic", label: "Blood Pressure — Diastolic", unit: "mmHg", min: 1, max: 250, step: 1, integer: true },
    { name: "oxygen_saturation", label: "Oxygen Saturation", unit: "% · 0–100", min: 0, max: 100, step: 1, integer: true },
    { name: "temperature", label: "Temperature", unit: "°F", min: 68, max: 115, step: 0.1, integer: false },
    { name: "blood_sugar", label: "Blood Sugar", unit: "mg/dL", min: 0.1, max: 1600, step: 0.1, integer: false }
];

const EDITABLE_NAMES = [...VITAL_FIELDS.map((field) => field.name), "pain_level"];

const COMPLAINT_LABELS = {
    cardiac: "Chest pain",
    stroke: "Stroke symptoms",
    respiratory: "Shortness of breath",
    syncope: "Syncope",
    abdominal: "Abdominal pain",
    neuro: "Severe headache",
    minor_injury: "Minor injury",
    minor_general: "Minor complaint",
    general: "Other / general"
};

const SEX_LABELS = { F: "Female", M: "Male", other: "Other", unknown: "Unknown" };

// Anything other than "scored" comes back as {intake_id, status}. update_patient
// needs a severity and a queue row, so editing an unscored intake would 500.
const NOT_SCORED_TEXT = {
    pending: "This patient hasn't been scored yet. Vitals can be edited once scoring finishes.",
    unscoreable: "This intake could not be scored, so its vitals can't be recomputed here.",
    failed: "Scoring failed for this intake, so its vitals can't be recomputed here."
};

const EM_DASH = "—";


/** Inputs hold strings; absent values start blank. */
function toFormValue(value) {
    return value === null || value === undefined ? "" : String(value);
}


/**
 * Every editable field here is numeric, so "97.0" and "97" are the same reading.
 * A string compare would mark that as an edit and send a field the API would
 * only no-op. Blank is compared as a string, since it means "not recorded"
 * rather than a number.
 */
function valuesDiffer(before, now) {
    if (before === "" || now === "") {
        return before !== now;
    }

    const beforeNumber = Number(before);
    const nowNumber = Number(now);

    if (Number.isNaN(beforeNumber) || Number.isNaN(nowNumber)) {
        return before !== now;
    }

    return beforeNumber !== nowNumber;
}


function seedValues(intake) {
    return Object.fromEntries(
        EDITABLE_NAMES.map((name) => [name, toFormValue(intake[name])])
    );
}


/**
 * Number() rather than parseInt/parseFloat: those stop at the first character
 * they can't read, so "12e2" would silently become 12.
 */
function toNumberOrNull(value) {
    const trimmed = value.trim();

    if (trimmed === "") {
        return null;
    }

    const parsed = Number(trimmed);

    return Number.isNaN(parsed) ? null : parsed;
}


function initialsFrom(name) {
    const words = name.trim().split(/\s+/);
    const first = words[0]?.[0] ?? "";
    const last = words.length > 1 ? words[words.length - 1][0] : "";

    return (first + last).toUpperCase();
}


/** "ESI-3" -> 3. Lower is more acute. */
function esiNumber(esi) {
    return Number(String(esi).slice(-1));
}


/**
 * Green only for a genuine de-escalation, red for any move toward ESI-1 — that
 * is an escalation the clinician needs to notice. An unchanged band is neither,
 * so it stays neutral rather than implying something happened.
 */
function recomputeTone(beforeEsi, afterEsi) {
    if (!afterEsi) {
        return "pending";
    }

    const before = esiNumber(beforeEsi);
    const after = esiNumber(afterEsi);

    if (after === before) {
        return "same";
    }

    return after > before ? "better" : "worse";
}


/** Mirrors the blocking rules the API applies, so they surface before a 400. */
function validateEdits(values, original) {
    const errors = {};

    for (const field of VITAL_FIELDS) {
        const raw = values[field.name].trim();

        if (raw === "") {
            continue;
        }

        const parsed = Number(raw);

        if (Number.isNaN(parsed)) {
            errors[field.name] = "Must be a number.";
        } else if (field.integer && !Number.isInteger(parsed)) {
            errors[field.name] = "Must be a whole number.";
        } else if (parsed < field.min || parsed > field.max) {
            errors[field.name] = `Must be between ${field.min} and ${field.max}.`;
        }
    }

    // The API compares the merged values — whatever was sent, falling back to
    // what is already stored — so the same comparison happens here.
    const merged = (name) =>
        values[name].trim() === "" ? original[name] : Number(values[name]);
    const systolic = merged("blood_pressure_systolic");
    const diastolic = merged("blood_pressure_diastolic");

    if (
        systolic !== null && systolic !== undefined &&
        diastolic !== null && diastolic !== undefined &&
        diastolic >= systolic
    ) {
        errors.blood_pressure_diastolic = "Diastolic must be lower than systolic.";
    }

    return errors;
}


function EditPatient() {
    const { intakeId } = useParams();

    // The payload the form diffs against. Replaced after a successful save so
    // the change indicators reset to the newly stored values.
    const [baseline, setBaseline] = useState(null);
    const [values, setValues] = useState({});
    const [loadError, setLoadError] = useState(null);
    const [notFound, setNotFound] = useState(false);
    const [scoringStatus, setScoringStatus] = useState(null);

    const [saving, setSaving] = useState(false);
    const [saveError, setSaveError] = useState(null);
    const [fieldErrors, setFieldErrors] = useState({});

    // Score either side of the save, so the panel can compare them.
    const [before, setBefore] = useState(null);
    const [after, setAfter] = useState(null);

    useEffect(() => {
        const controller = new AbortController();

        const load = async () => {
            try {
                const response = await fetch(DETAIL_URL(intakeId), {
                    signal: controller.signal
                });
                const data = await response.json().catch(() => null);

                if (!response.ok) {
                    if (response.status === 404) {
                        setNotFound(true);
                    } else {
                        setLoadError(
                            data?.error?.message ??
                                `Could not load this patient (HTTP ${response.status}).`
                        );
                    }

                    return;
                }

                const payload = data?.payload ?? null;

                // Short-circuited response: no intake block to seed the form from.
                if (payload && payload.status && !payload.system_esi) {
                    setScoringStatus(payload.status);
                    return;
                }

                setBaseline(payload);
                setValues(seedValues(payload.intake));
            } catch (fetchError) {
                if (fetchError.name === "AbortError") {
                    return;
                }

                console.error("Loading patient for edit failed:", fetchError);
                setLoadError("Could not reach the server. Check the connection and try again.");
            }
        };

        load();

        return () => controller.abort();
    }, [intakeId]);

    const updateValue = (name, value) => {
        setValues((previous) => ({ ...previous, [name]: value }));

        // A previous save's before -> after describes edits that are already
        // stored. Once new edits begin it no longer describes what is pending,
        // so the panel drops back to "current -> calculated on save".
        setBefore(null);
        setAfter(null);

        setFieldErrors((previous) => {
            if (!(name in previous)) {
                return previous;
            }

            const next = { ...previous };
            delete next[name];

            return next;
        });
    };

    if (scoringStatus) {
        return (
            <div className='edit'>
                <h1 className='h1'>Edit Patient</h1>
                <div className='panel emptystate'>
                    <p>{NOT_SCORED_TEXT[scoringStatus] ?? `Intake status: ${scoringStatus}.`}</p>
                    <Link className='backbtn' to={`/intakes/${intakeId}`}>
                        ← Back to Patient Detail
                    </Link>
                </div>
            </div>
        );
    }

    if (notFound) {
        return (
            <div className='edit'>
                <h1 className='h1'>Edit Patient</h1>
                <div className='panel emptystate'>
                    <p>No intake with that id.</p>
                    <Link className='backbtn' to='/queue'>← Back to Queue</Link>
                </div>
            </div>
        );
    }

    if (baseline === null) {
        return (
            <div className='edit'>
                <h1 className='h1'>Edit Patient</h1>
                <div className='panel emptystate'>
                    {loadError ? <p className='loaderror'>{loadError}</p> : <p>Loading patient…</p>}
                </div>
            </div>
        );
    }

    const original = baseline.intake;
    const detailPath = `/intakes/${intakeId}`;

    // A field is "added" when it had no value before and has one now, and
    // "changed" when it had one and the value differs.
    const edits = EDITABLE_NAMES.map((name) => {
        const wasValue = toFormValue(original[name]);
        const now = values[name];

        return {
            name,
            before: wasValue,
            dirty: valuesDiffer(wasValue, now),
            added: wasValue === "" && now !== ""
        };
    });

    const addedCount = edits.filter((edit) => edit.added).length;
    const changedCount = edits.filter((edit) => edit.dirty && !edit.added).length;
    const hasEdits = addedCount + changedCount > 0;

    const painEdit = edits.find((edit) => edit.name === "pain_level");
    const painUnset = values.pain_level === "";

    const nowEsi = before?.esi ?? baseline.system_esi;
    const nowScore = before?.score ?? baseline.severity_score;
    const tone = recomputeTone(nowEsi, after?.esi);

    const handleSave = async () => {
        if (saving || !hasEdits) {
            return;
        }

        const nextFieldErrors = validateEdits(values, original);

        if (Object.keys(nextFieldErrors).length > 0) {
            setFieldErrors(nextFieldErrors);
            setSaveError("Fix the highlighted fields before saving.");
            return;
        }

        setFieldErrors({});
        setSaving(true);
        setSaveError(null);

        // Only changed fields go in the body. update_patient keys off
        // model_fields_set, so anything omitted is left exactly as stored.
        const body = {};

        for (const edit of edits) {
            if (edit.dirty) {
                body[edit.name] = toNumberOrNull(values[edit.name]);
            }
        }

        const priorScore = { esi: baseline.system_esi, score: baseline.severity_score };

        try {
            const response = await fetch(`${API_BASE_URL}/intakes/${intakeId}`, {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(body)
            });

            const data = await response.json().catch(() => null);

            if (!response.ok) {
                // Field-level issues come back keyed by name, so they land on
                // the inputs that caused them.
                const details = data?.error?.details ?? [];
                const mapped = {};

                for (const detail of details) {
                    if (EDITABLE_NAMES.includes(detail.field)) {
                        mapped[detail.field] = detail.issue;
                    }
                }

                setFieldErrors(mapped);
                setSaveError(
                    data?.error?.message ??
                        (typeof data?.detail === "string" ? data.detail : null) ??
                        `Could not save (HTTP ${response.status}).`
                );

                return;
            }

            // PATCH returns the new score but not the new ESI band, so the
            // fresh detail is what fills the After column.
            const refetch = await fetch(DETAIL_URL(intakeId));
            const refetched = await refetch.json().catch(() => null);

            if (!refetch.ok || !refetched?.payload) {
                setSaveError("Saved, but the updated score could not be loaded. Reload to see it.");
                return;
            }

            const payload = refetched.payload;

            setBaseline(payload);
            setValues(seedValues(payload.intake));
            setBefore(priorScore);
            setAfter({ esi: payload.system_esi, score: payload.severity_score });
        } catch (submitError) {
            console.error("Saving vitals failed:", submitError);
            setSaveError("Could not reach the server. Check the connection and try again.");
        } finally {
            setSaving(false);
        }
    };

    return (
        <div className='edit'>
            <div className='crumb'>
                <Link to='/queue'>Triage Queue</Link> ›{' '}
                <Link to={detailPath}>Patient Detail</Link> › <b>Edit Patient</b>
            </div>

            <h1 className='h1'>Edit Patient</h1>

            <div className='actionRow'>
                <Link className='backbtn' to={detailPath}>
                    ← Back to Patient Detail
                </Link>
            </div>

            <div className='pcard'>
                <div className='pic'>{initialsFrom(baseline.patient_name)}</div>

                <div className='pinfo'>
                    <div className='pname'>{baseline.patient_name}</div>

                    <div>
                        <div className='lab'>Age / Gender</div>
                        <div className='val blue'>
                            {baseline.age} / {SEX_LABELS[baseline.sex] ?? baseline.sex}
                        </div>
                    </div>

                    <div>
                        <div className='lab'>Chief Complaint</div>
                        <div className='val blue'>
                            {COMPLAINT_LABELS[original.chief_complaint] ??
                                original.chief_complaint}
                        </div>
                    </div>

                    <div>
                        <span className='lockchip'>
                            <Lock size={10} />
                            Identity not editable
                        </span>
                    </div>
                </div>
            </div>

            <div className='grid'>
                <div className='panel'>
                    <h3>
                        <span className='ic pen'><SquarePen size={12} /></span>
                        Update Vitals &amp; Pain
                    </h3>
                    <p className='panelsub'>
                        Correct or add measurements taken since intake. Only changed
                        fields are sent; the score and queue position recompute on save.
                    </p>

                    <div className='sect'>Vitals</div>

                    <div className='fields'>
                        {VITAL_FIELDS.map((field) => {
                            const edit = edits.find((item) => item.name === field.name);
                            const fieldError = fieldErrors[field.name];

                            return (
                                <div className='field' key={field.name}>
                                    <label htmlFor={field.name}>
                                        {field.label}
                                        <span className='unit'>{field.unit}</span>
                                    </label>

                                    <input
                                        id={field.name}
                                        type='number'
                                        className={
                                            fieldError
                                                ? 'invalid'
                                                : edit.dirty
                                                    ? 'changed'
                                                    : undefined
                                        }
                                        value={values[field.name]}
                                        onChange={(event) =>
                                            updateValue(field.name, event.target.value)
                                        }
                                        placeholder='not provided'
                                        min={field.min}
                                        max={field.max}
                                        step={field.step}
                                        aria-invalid={fieldError ? true : undefined}
                                    />

                                    {fieldError && <span className='err'>{fieldError}</span>}

                                    {!fieldError && edit.dirty && (
                                        <span className='wasval'>
                                            was: {edit.before === "" ? "not provided" : edit.before}
                                        </span>
                                    )}

                                    {!fieldError && !edit.dirty && edit.before === "" && (
                                        <span className='miss'>not provided</span>
                                    )}
                                </div>
                            );
                        })}
                    </div>

                    <div className='sect'>
                        Pain Level <span className='sectnote'>(0–10)</span>
                    </div>

                    {/* A blank pain level parks the thumb at 0, which would read
                        as a recorded 0. The dimmed track and "not recorded"
                        readout keep the two states distinguishable. */}
                    <div className='rangefield'>
                        <input
                            id='pain_level'
                            type='range'
                            min='0'
                            max='10'
                            step='1'
                            className={painUnset ? 'unset' : undefined}
                            value={painUnset ? "0" : values.pain_level}
                            onChange={(event) => updateValue("pain_level", event.target.value)}
                            aria-label='Pain level, 0 to 10'
                            aria-valuetext={painUnset ? 'not recorded' : `${values.pain_level} of 10`}
                        />
                        <span className={painUnset ? 'rangeval unset' : 'rangeval'}>
                            {painUnset ? 'not recorded' : `${values.pain_level} / 10`}
                        </span>
                    </div>

                    {painEdit.dirty && (
                        <span className='wasval'>
                            was: {painEdit.before === "" ? "not provided" : painEdit.before}
                        </span>
                    )}

                    {!painEdit.dirty && painEdit.before === "" && (
                        <span className='miss'>not provided</span>
                    )}

                    {saveError && <p className='saveerror'>{saveError}</p>}

                    <div className='actionbar'>
                        <span className='changed-note'>
                            {hasEdits ? (
                                <>
                                    <CircleAlert size={14} />
                                    {changedCount} field{changedCount === 1 ? '' : 's'} changed,{' '}
                                    {addedCount} added
                                </>
                            ) : (
                                <span className='nochange'>
                                    {after ? 'Saved. No further changes.' : 'No changes yet'}
                                </span>
                            )}
                        </span>

                        <div className='btns'>
                            <Link className='btn ghost' to={detailPath}>
                                {after ? 'Done' : 'Cancel'}
                            </Link>
                            <button
                                className='btn save'
                                type='button'
                                onClick={handleSave}
                                disabled={!hasEdits || saving}
                            >
                                {saving ? 'Saving…' : 'Save & Recompute'}
                            </button>
                        </div>
                    </div>
                </div>

                <div className='panel recompute'>
                    <h3>
                        <span className='ic calc'><ClipboardList size={12} /></span>
                        Recompute Preview
                    </h3>
                    <p className='panelsub'>
                        Estimated effect of these edits. Final values are confirmed after
                        save.
                    </p>

                    <div className='beforeafter'>
                        <div className='ba-col before'>
                            <div className='lab'>{after ? 'Before' : 'Now'}</div>
                            <div className='esi'>{nowEsi}</div>
                            <div className='pts'>{nowScore} points</div>
                        </div>

                        <div className='ba-arrow'>
                            <ArrowRight size={20} />
                        </div>

                        <div className={`ba-col after ${tone}`}>
                            <div className='lab'>After save</div>
                            <div className='esi'>{after?.esi ?? EM_DASH}</div>
                            <div className='pts'>
                                {after ? `${after.score} points` : 'calculated on save'}
                            </div>
                        </div>
                    </div>

                    <p className='preview-note'>
                        Data completeness is currently {baseline.data_completeness} scored
                        vitals. Adding a missing vital lets its scoring rule run.
                    </p>

                    <p className='disclaim'>
                        Triage aid — not a diagnosis. Clinician judgment required.
                    </p>
                </div>
            </div>
        </div>
    );
}


export default EditPatient;
