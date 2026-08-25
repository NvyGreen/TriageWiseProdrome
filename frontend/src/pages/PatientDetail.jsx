import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Info, Heart, Bot, ChartPie, Package, TriangleAlert, CircleAlert } from "lucide-react";

import Dropdown from "../components/Dropdown";
import TextBox from "../components/TextBox";

import "./PatientDetail.css";


const esiBandOptions = [
    { value: "ESI-1", display: "ESI-1" },
    { value: "ESI-2", display: "ESI-2" },
    { value: "ESI-3", display: "ESI-3" },
    { value: "ESI-4", display: "ESI-4" },
    { value: "ESI-5", display: "ESI-5" }
];

// Values match the ReasonCode enum in backend/app/utils/enums.py.
const overrideReasonOptions = [
    { value: "Clinical info AI lacks", display: "Clinical info AI lacks" },
    { value: "AI driver incorrect", display: "AI driver incorrect" },
    { value: "Patient preference", display: "Patient preference" },
    { value: "Other", display: "Other" }
];

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;

// The server decides what each mode returns; black-box simply omits the
// reasoning fields, so there is nothing to strip client-side.
const BLACKBOX = "blackbox";
const XAI = "xai";

// scoring_status values from ScoringStatus in triage_service.py. Anything other
// than "scored" comes back as {intake_id, status} instead of a full payload.
const PENDING = "pending";
const TERMINAL_STATUS_TEXT = {
    unscoreable: "This intake is valid, but it could not be scored. Review it manually.",
    failed: "Scoring failed for this intake. It may need to be resubmitted."
};

// The scorer is a separate process, so the wait is unbounded in principle.
// Poll briefly, then hand over to a manual refresh rather than spinning forever.
const POLL_INTERVAL_MS = 3000;
const POLL_TIMEOUT_MS = 120000;

const VITAL_ROWS = [
    { label: "Heart Rate", field: "heart_rate", unit: "bpm" },
    {
        label: "Blood Pressure",
        field: "blood_pressure_systolic",
        unit: "mmHg",
        pair: "blood_pressure_diastolic"
    },
    { label: "Temperature", field: "temperature", unit: "°F" },
    { label: "SpO2", field: "oxygen_saturation", unit: "%" },
    { label: "Respiratory Rate", field: "respiration_rate", unit: "/min" },
    { label: "Pain Level", field: "pain_level", unit: "/ 10" }
];

const GAP_LABELS = {
    not_provided: "Not provided → rule skipped",
    assumed: "Assumed",
    recorded_not_scored: "Recorded, not scored",
    red_flag_input: "Red-flag input",
    beyond_the_data: "Beyond the data"
};

// Most actionable first: a missing vital can still be measured, whereas the
// last category never becomes available.
const GAP_ORDER = [
    "not_provided",
    "assumed",
    "recorded_not_scored",
    "red_flag_input",
    "beyond_the_data"
];

// Warm-to-cool, matching descending contribution.
const SEGMENT_COLOURS = [
    "#d83a3a",
    "#e0662b",
    "#e0a52b",
    "#c9b23a",
    "#8a9a52",
    "#7a8aa0"
];

const EM_DASH = "—";

// Driver factor names -> intake fields, mirroring VITAL_MAP in
// backend/app/utils/constants.py. Used to mark which vitals actually scored.
const FACTOR_TO_FIELD = {
    "SpO2": "oxygen_saturation",
    "Heart rate": "heart_rate",
    "Respiratory rate": "respiration_rate",
    "Systolic BP": "blood_pressure_systolic",
    "Pain score": "pain_level"
};


/** randomUUID needs a secure context, which includes localhost. */
function createIdempotencyKey() {
    if (globalThis.crypto?.randomUUID) {
        return globalThis.crypto.randomUUID();
    }

    return `override-${Date.now()}-${Math.random().toString(16).slice(2, 10)}`;
}


/** ESI-1/2 read as red, ESI-3 amber, ESI-4/5 calm. */
function severityTone(systemEsi) {
    if (systemEsi === "ESI-1" || systemEsi === "ESI-2") {
        return "crit";
    }

    return systemEsi === "ESI-3" ? "amber" : "ok";
}


/** data_completeness arrives as "2 of 5"; incomplete coverage is worth flagging. */
function completenessIsPartial(dataCompleteness) {
    const [scored, total] = String(dataCompleteness).split(" of ").map(Number);

    return Number.isFinite(scored) && Number.isFinite(total) && scored < total;
}


function initialsFrom(name) {
    const words = name.trim().split(/\s+/);
    const first = words[0]?.[0] ?? "";
    const last = words.length > 1 ? words[words.length - 1][0] : "";

    return (first + last).toUpperCase();
}


/** Vitals that fired a scoring rule — the honest basis for highlighting them. */
function scoredFields(drivers) {
    const fields = new Set();

    for (const driver of drivers ?? []) {
        const field = FACTOR_TO_FIELD[driver.factor];

        if (field) {
            fields.add(field);
        }
    }

    return fields;
}


/** "shortness_of_breath" -> "Shortness of breath". */
function humanise(value) {
    const spaced = String(value).replace(/_/g, " ");

    return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}


function formatEnteredAt(timestamp) {
    return new Date(timestamp).toLocaleString("en-US", {
        month: "long",
        day: "numeric",
        year: "numeric",
        hour: "numeric",
        minute: "2-digit",
        hour12: true
    });
}


function VitalsList({ intake, scored }) {
    return (
        <ul className='vitalsList'>
            {VITAL_ROWS.map((row) => {
                const value = intake[row.field];
                // exclude_none drops absent vitals entirely, so undefined and
                // null both mean "not recorded".
                const provided = value !== undefined && value !== null;

                let display;
                let valueClass = 'vitalValue';

                if (!provided) {
                    display = 'not provided';
                    valueClass += ' miss';
                } else if (row.pair) {
                    display = `${value} / ${intake[row.pair] ?? EM_DASH} ${row.unit}`;
                } else {
                    display = `${value} ${row.unit}`;
                }

                // Highlighted only when a rule actually fired on it, so the
                // colour means something rather than guessing at normal ranges.
                if (provided && scored.has(row.field)) {
                    valueClass += ' scored';
                }

                return (
                    <li className='vital' key={row.field}>
                        <span className='vitalName'>{row.label}</span>
                        <span className={valueClass}>{display}</span>
                    </li>
                );
            })}
        </ul>
    );
}


function FactorTable({ drivers, gaps }) {
    // Vitals whose rule never ran still earn a row, so the absence is visible
    // rather than silently missing from the breakdown.
    const skipped = [...(gaps?.not_provided ?? []), ...(gaps?.assumed ?? [])];

    return (
        <table className='breakdownTable'>
            <thead>
                <tr>
                    <th>Factor</th>
                    <th>Relative weight</th>
                    <th>Points</th>
                    <th>Patient value</th>
                </tr>
            </thead>
            <tbody>
                {drivers.map((driver, index) => (
                    <tr key={driver.rule_id}>
                        {/* tabIndex so the rule detail is reachable by keyboard,
                            not hover only. */}
                        <td className='fname' tabIndex={0}>
                            {driver.threshold}
                            <span className='ftip'>
                                rule {driver.rule_id} · +{driver.weight} pts · {driver.esi_anchor}
                            </span>
                        </td>
                        <td>
                            <div className='bar'>
                                <i
                                    style={{
                                        width: `${driver.contribution_pct}%`,
                                        background: SEGMENT_COLOURS[index % SEGMENT_COLOURS.length]
                                    }}
                                />
                            </div>
                        </td>
                        <td className='imp'>
                            +{driver.weight}{' '}
                            <span className='muted'>({driver.contribution_pct}%)</span>
                        </td>
                        <td className='muted'>{driver.patient_value}</td>
                    </tr>
                ))}

                {skipped.map((field) => (
                    <tr className='skiprow' key={field}>
                        <td className='fname'>
                            {humanise(field)} <span className='skip'>skipped</span>
                        </td>
                        <td>
                            <div className='bar' />
                        </td>
                        <td className='imp muted'>{EM_DASH}</td>
                        <td className='muted miss2'>not provided</td>
                    </tr>
                ))}
            </tbody>
        </table>
    );
}


function GapBox({ gaps, fallbackInstruction }) {
    // Only categories with content are worth a row, and they read best in
    // severity order rather than whatever order the dict arrives in.
    const populated = GAP_ORDER.filter((key) => (gaps[key] ?? []).length > 0);

    return (
        <div className='gapbox'>
            <div className='gaptitle'>
                <span className='gapic'><TriangleAlert size={14} /></span>
                What this score can't see
            </div>

            {populated.map((key) => (
                <div className='gaprow' key={key}>
                    <span className={`gtag gtag-${key}`}>{GAP_LABELS[key]}</span>
                    <span className='gtxt'>
                        {gaps[key].map(humanise).join(", ")}
                    </span>
                </div>
            ))}

            <p className='gapcta'>{fallbackInstruction}</p>
        </div>
    );
}


/**
 * Donut of score share. r=15.9 gives a circumference of ~100, so each segment's
 * dash length is its percentage directly.
 */
function ScoreDonut({ drivers, total }) {
    // Cumulative offsets are worked out before the JSX: accumulating inside the
    // map callback mutates during render, which the compiler rejects.
    const segments = [];
    let offset = 0;

    for (let index = 0; index < drivers.length; index += 1) {
        const driver = drivers[index];

        segments.push({
            id: driver.rule_id,
            pct: driver.contribution_pct,
            offset,
            colour: SEGMENT_COLOURS[index % SEGMENT_COLOURS.length]
        });

        offset += driver.contribution_pct;
    }

    return (
        <svg className='donut' viewBox='0 0 42 42' role='img' aria-label={`Score breakdown, ${total} points`}>
            <circle cx='21' cy='21' r='15.9' fill='none' stroke='#eef1f5' strokeWidth='6' />

            {segments.map((segment) => (
                <circle
                    key={segment.id}
                    cx='21'
                    cy='21'
                    r='15.9'
                    fill='none'
                    stroke={segment.colour}
                    strokeWidth='6'
                    strokeDasharray={`${segment.pct} ${100 - segment.pct}`}
                    strokeDashoffset={-segment.offset}
                />
            ))}

            <text x='21' y='20.5' textAnchor='middle' fontSize='9' fontWeight='800' fill='#0f2440'>
                {total}
            </text>
            <text x='21' y='26' textAnchor='middle' fontSize='3.4' fill='#5b6b7f'>
                points
            </text>
        </svg>
    );
}


function PatientDetail() {
    const { intakeId } = useParams();

    // Black-box is the default view; XAI is opt-in and costs a second request.
    const [mode, setMode] = useState(BLACKBOX);
    const [detail, setDetail] = useState(null);
    // Which mode the held `detail` actually came from. Pairing them lets the
    // effect skip work, and lets a failed toggle revert without refetching.
    const [loadedMode, setLoadedMode] = useState(null);
    const [fetching, setFetching] = useState(true);
    const [error, setError] = useState(null);
    const [notFound, setNotFound] = useState(false);

    // Set when the API returns {intake_id, status} rather than a scored payload.
    const [scoringStatus, setScoringStatus] = useState(null);
    const [pollTimedOut, setPollTimedOut] = useState(false);

    const [overrideBand, setOverrideBand] = useState("");
    const [overrideReason, setOverrideReason] = useState("");
    const [overrideNote, setOverrideNote] = useState("");
    const [submitting, setSubmitting] = useState(false);
    const [overrideError, setOverrideError] = useState(null);

    // One key per attempt: reused when retrying the same override, replaced
    // after a 201 so a genuinely different override is not seen as a duplicate.
    const overrideKey = useRef(null);

    if (overrideKey.current === null) {
        overrideKey.current = createIdempotencyKey();
    }

    useEffect(() => {
        if (mode === loadedMode) {
            return;
        }

        const controller = new AbortController();

        const load = async () => {
            setFetching(true);
            setError(null);

            try {
                const response = await fetch(
                    `${API_BASE_URL}/intakes/${intakeId}?mode=${mode}`,
                    { signal: controller.signal }
                );

                const data = await response.json().catch(() => null);

                if (!response.ok) {
                    if (response.status === 404) {
                        setNotFound(true);
                    } else {
                        setError(
                            data?.error?.message ??
                                `Could not load this patient (HTTP ${response.status}).`
                        );
                        // Fall back to whatever mode is already on screen so the
                        // switch never claims a view that failed to load.
                        setMode(loadedMode ?? BLACKBOX);
                    }

                    return;
                }

                const payload = data?.payload ?? null;

                // Not scored yet: the router short-circuits to {intake_id,
                // status} long before there is anything to render.
                if (payload && payload.status && !payload.system_esi) {
                    setNotFound(false);
                    setScoringStatus(payload.status);
                    return;
                }

                setNotFound(false);
                setScoringStatus(null);
                setDetail(payload);
                setLoadedMode(mode);
            } catch (fetchError) {
                if (fetchError.name === "AbortError") {
                    return;
                }

                console.error("Loading patient detail failed:", fetchError);
                setError("Could not reach the server. Check the connection and try again.");
                setMode(loadedMode ?? BLACKBOX);
            } finally {
                if (!controller.signal.aborted) {
                    setFetching(false);
                }
            }
        };

        load();

        return () => controller.abort();
    }, [intakeId, mode, loadedMode]);

    // While the scorer has not claimed the intake, re-ask on an interval.
    // Clearing loadedMode is what re-triggers the load effect above.
    useEffect(() => {
        if (scoringStatus !== PENDING || pollTimedOut) {
            return undefined;
        }

        const startedAt = Date.now();

        const timer = setInterval(() => {
            if (Date.now() - startedAt >= POLL_TIMEOUT_MS) {
                setPollTimedOut(true);
                return;
            }

            setLoadedMode(null);
        }, POLL_INTERVAL_MS);

        return () => clearInterval(timer);
    }, [scoringStatus, pollTimedOut]);

    const checkAgain = () => {
        setPollTimedOut(false);
        setScoringStatus(null);
        setLoadedMode(null);
    };

    const handleOverrideSubmit = async () => {
        if (submitting || !overrideBand || !overrideReason) {
            return;
        }

        setSubmitting(true);
        setOverrideError(null);

        try {
            const response = await fetch(`${API_BASE_URL}/overrides/`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "Idempotency-Key": overrideKey.current
                },
                body: JSON.stringify({
                    severity_id: detail.severity_id,
                    clinician_esi: overrideBand,
                    reason_code: overrideReason,
                    note: overrideNote.trim() || null
                })
            });

            const data = await response.json().catch(() => null);

            if (!response.ok) {
                const detailText =
                    data?.error?.message ??
                    (typeof data?.detail === "string" ? data.detail : null) ??
                    `The server returned HTTP ${response.status}.`;

                // Values are left in place so a retry does not mean re-picking.
                setOverrideError(`Could not log the override. ${detailText}`);
                return;
            }

            setOverrideBand("");
            setOverrideReason("");
            setOverrideNote("");
            overrideKey.current = createIdempotencyKey();

            // Clearing loadedMode re-runs the load effect, so the box below
            // reflects what the server actually stored.
            setLoadedMode(null);
        } catch (submitError) {
            console.error("Logging the override failed:", submitError);
            setOverrideError(
                "Could not log the override. The server could not be reached."
            );
        } finally {
            setSubmitting(false);
        }
    };

    // Not scored yet, or terminally unscoreable: there is no severity or
    // explanation to render, so the page reports the state instead.
    if (scoringStatus) {
        const terminal = TERMINAL_STATUS_TEXT[scoringStatus];

        return (
            <div className='detail'>
                <div className='crumb'>
                    <Link to='/queue'>Triage Queue</Link> › <b>Patient Detail</b>
                </div>
                <h1 className='h1'>Patient Detail</h1>

                <div className='panel emptystate'>
                    {terminal ? (
                        <>
                            <p className='loaderror'>{terminal}</p>
                            <p className='statusnote'>Intake {intakeId} · {scoringStatus}</p>
                        </>
                    ) : (
                        <>
                            <p>Scoring in progress…</p>
                            <p className='statusnote'>
                                Intake {intakeId} is queued for scoring. This page
                                updates itself when the score lands.
                                {pollTimedOut && ' Still waiting — check again below.'}
                            </p>
                        </>
                    )}

                    <div className='statusactions'>
                        {(terminal || pollTimedOut) && (
                            <button type='button' className='backbtn' onClick={checkAgain}>
                                Check again
                            </button>
                        )}
                        <Link className='backbtn' to='/queue'>← Back to Queue</Link>
                    </div>
                </div>
            </div>
        );
    }

    if (notFound) {
        return (
            <div className='detail'>
                <div className='crumb'>
                    <Link to='/queue'>Triage Queue</Link> › <b>Patient Detail</b>
                </div>
                <h1 className='h1'>Patient Detail</h1>
                <div className='panel emptystate'>
                    <p>No intake with that id.</p>
                    <Link className='backbtn' to='/queue'>
                        ← Back to Queue
                    </Link>
                </div>
            </div>
        );
    }

    // Nothing has loaded yet, so there is no page to keep on screen.
    if (detail === null) {
        return (
            <div className='detail'>
                <div className='crumb'>
                    <Link to='/queue'>Triage Queue</Link> › <b>Patient Detail</b>
                </div>
                <h1 className='h1'>Patient Detail</h1>
                <div className='panel emptystate'>
                    {error ? (
                        <>
                            <p className='loaderror'>{error}</p>
                            <button
                                type='button'
                                className='backbtn'
                                onClick={() => setLoadedMode(null)}
                            >
                                Retry
                            </button>
                        </>
                    ) : (
                        <p>Loading patient…</p>
                    )}
                </div>
            </div>
        );
    }

    const visible = detail;
    const { intake } = visible;
    const showXai = loadedMode === XAI;

    const tone = severityTone(visible.system_esi);
    const partial = completenessIsPartial(visible.data_completeness);
    const scored = scoredFields(visible.explanation?.named_drivers);

    // The API returns drivers in rule order; largest contributor first reads
    // better, and keeps the donut, bars and legend colour-consistent.
    const drivers = [...(visible.explanation?.named_drivers ?? [])].sort(
        (a, b) => b.contribution_pct - a.contribution_pct
    );

    return (
        <div className='detail'>
            <div className='crumb'>
                <Link to='/queue'>Triage Queue</Link> › <b>Patient Detail</b>
            </div>

            <h1 className='h1'>Patient Detail</h1>

            <div className='actionrow'>
                <Link className='backbtn' to='/queue'>
                    ← Back to Queue
                </Link>
                <Link className='editbtn' to={`/intakes/${intakeId}/edit`}>
                    Edit Patient
                </Link>
            </div>

            <div className='pcard'>
                <div className={`pic ${tone}`}>{initialsFrom(visible.patient_name)}</div>

                <div className='pinfo'>
                    <div className='pnamecell'>
                        <div className='pname'>
                            {visible.patient_name}
                            <span className={`pill ${tone}line`}>
                                {visible.band_name.toUpperCase()}
                            </span>
                        </div>
                    </div>

                    <div>
                        <div className='lab'>Patient ID</div>
                        <div className='val'>ID {visible.patient_id}</div>
                    </div>

                    <div>
                        <div className='lab'>Age / Gender</div>
                        <div className='val blue'>{visible.age} / {visible.sex}</div>
                    </div>

                    <div>
                        <div className='lab'>Entered At</div>
                        <div className='val blue'>{formatEnteredAt(intake.created_at)}</div>
                    </div>
                </div>

                <div className={`sevbox ${tone}`}>
                    <div className='lab'>Severity Score</div>
                    <div className='score'>
                        {visible.severity_score} <small>points</small>
                    </div>
                    <div className='row2'>
                        <span className={`pill ${tone}`}>
                            {visible.system_esi} · {visible.band_name.toUpperCase()}
                        </span>
                        <span className={partial ? 'datacomp warn' : 'datacomp'}>
                            {visible.data_completeness} vitals scored
                        </span>
                    </div>
                </div>
            </div>

            <div className='tabsbar'>
                <div className='tabs'>
                    <div className='t on'>Explanation</div>
                    <div className='t future'>
                        Overview <span className='soon'>soon</span>
                    </div>
                    <div className='t future'>
                        Timeline / History <span className='soon'>soon</span>
                    </div>
                </div>

                <div className='statusmini'>
                    <div>
                        <div className='lab'>Status</div>
                        {/* Placeholder until the queue is persisted. */}
                        <div className='val'>In Queue</div>
                    </div>

                    <div>
                        <div className='lab'>In Queue Since</div>
                        <div className='val'>
                            <span className='pill wait'>WAITING</span> {EM_DASH}
                        </div>
                    </div>
                </div>
            </div>

            <div className='grid'>
                <div className='colleft'>
                    <div className='panel clinicalSummary'>
                        <h3>
                            <span className='ic info'><Info size={12} /></span>
                            Clinical Summary
                        </h3>

                        <div className='sect'>Symptoms</div>
                        <p className='symptoms'>
                            {intake.symptoms.length > 0
                                ? intake.symptoms.map(humanise).join(", ")
                                : EM_DASH}
                        </p>

                        {intake.pre_existing_conditions.length > 0 && (
                            <>
                                <div className='sect'>Pre-existing conditions</div>
                                <p className='symptoms'>
                                    {intake.pre_existing_conditions.map(humanise).join(", ")}
                                </p>
                            </>
                        )}

                        <div className='sect'>Vitals</div>
                        <VitalsList intake={intake} scored={scored} />
                    </div>

                    {visible.risk_blurb && (
                        <div className='panel riskLevel'>
                            <h3>
                                <span className='ic heart'><Heart size={12} /></span>
                                Risk Level
                            </h3>
                            <span className={`pill ${tone}`}>
                                {visible.band_name.toUpperCase()}
                            </span>
                            <p className='notes'>{visible.risk_blurb}</p>
                        </div>
                    )}
                </div>

                <div className='panel colmid explanationBox'>
                <div className='explanationTop'>
                    <h3 className='explanationTitle'>
                        <span className='ic ai'><Bot size={12} /></span>
                        Explanation
                    </h3>
                    <button
                        type='button'
                        className={showXai ? 'togglebar on' : 'togglebar'}
                        onClick={() => setMode(showXai ? BLACKBOX : XAI)}
                        aria-pressed={showXai}
                        disabled={fetching}
                    >
                        Black-box <span className='switch' /> XAI
                    </button>
                </div>

                {fetching && (
                    <p className='bbNote'>Loading explanation…</p>
                )}

                {!fetching && error && (
                    <p className='bbNote loaderror'>{error}</p>
                )}

                {!fetching && !error && !showXai && (
                    <p className='bbNote'>
                        Black-box mode: score and ESI band only. Toggle to XAI for the
                        full explanation.
                    </p>
                )}

                {visible.red_flags?.length > 0 && (
                    <div className='flagstrip'>
                        {visible.red_flags.map((flag, index) => (
                            <div className={`flag t${flag.flag_tier}`} key={index}>
                                <span className='fi'>
                                    {flag.flag_tier === 1 ? (
                                        <TriangleAlert size={15} />
                                    ) : (
                                        <CircleAlert size={15} />
                                    )}
                                </span>

                                <div className='ftext'>
                                    <div className='fmsg'>{flag.message}</div>
                                    {/* tabIndex so the rationale is reachable by
                                        keyboard and on touch, not hover only. */}
                                    <span className='fwhy' tabIndex={0}>
                                        why this flagged
                                        <span className='fwhytip'>
                                            {flag.rationale}
                                            <span className='fwhycaveat'>
                                                Banner only, doesn't change ESI.
                                            </span>
                                        </span>
                                    </span>
                                </div>

                                <span className='ftag'>
                                    {flag.flag_type} · Tier {flag.flag_tier}
                                </span>
                            </div>
                        ))}
                        <p className='flagnote'>
                            Red-flag banners surface safety patterns. They never change
                            the ESI score.
                        </p>
                    </div>
                )}

                {visible.lede && <p className='explanationText'>{visible.lede}</p>}

                {visible.confidence && (
                    <p className={`confidenceLine conf-${visible.confidence.toLowerCase()}`}>
                        Confidence: {visible.confidence}
                    </p>
                )}

                {visible.explanation && (
                    <>
                        <div className='factorBreakdown'>
                            <FactorTable
                                drivers={drivers}
                                gaps={visible.explanation.gap_acknowledgement}
                            />
                        </div>

                        <GapBox
                            gaps={visible.explanation.gap_acknowledgement}
                            fallbackInstruction={visible.explanation.fallback_instruction}
                        />
                    </>
                )}

                {visible.base_rate_line && (
                    <p className='braterow'>{visible.base_rate_line}</p>
                )}
            </div>

                <div className='colright'>
            {visible.explanation && (
                <div className='panel scoreBreakdown'>
                    <h3>
                        <span className='ic chart'><ChartPie size={12} /></span>
                        Score Breakdown
                    </h3>

                    <div className='donutwrap'>
                        <ScoreDonut drivers={drivers} total={visible.severity_score} />
                        <div className='donutcap'>share of score weight</div>
                    </div>

                    <div className='legend'>
                        {drivers.map((driver, index) => (
                            <div className='li' key={driver.rule_id}>
                                <span
                                    className='dot'
                                    style={{
                                        background:
                                            SEGMENT_COLOURS[index % SEGMENT_COLOURS.length]
                                    }}
                                />
                                <span className='lname'>{driver.factor}</span>
                                <span className='lval'>
                                    {driver.weight}
                                    <span className='lpct'>{driver.contribution_pct}%</span>
                                </span>
                            </div>
                        ))}

                        <div className='totrow'>
                            <span>Total</span>
                            <b>
                                {visible.severity_score} → {visible.system_esi}
                            </b>
                        </div>
                    </div>
                </div>
            )}

            {/* The structured override is sent in both modes, so the box looks
                the same either way. Only its xai_line — which names the delta
                drivers — is withheld in black-box. */}
            {visible.override && (
                <div className='dualbox'>
                    <h4>System vs. clinician score</h4>

                    <div className='dualrow'>
                        <div className='sys'>
                            <div className='lab'>System suggests</div>
                            <div className='num'>{visible.override.system_esi}</div>
                        </div>

                        <div className='you'>
                            <div className='lab'>Clinician score</div>
                            <div className='num'>{visible.override.clinician_esi}</div>
                        </div>
                    </div>

                    <p className='overrideReason'>
                        <span className='k'>Override reason:</span>{' '}
                        <b>{visible.override.reason_code}</b>
                        {visible.override.note && (
                            <span className='onote'> &mdash; &ldquo;{visible.override.note}&rdquo;</span>
                        )}
                    </p>

                    {visible.override.xai_line && (
                        <p className='dualprompt'>{visible.override.xai_line}</p>
                    )}
                </div>
            )}

            <div className='panel overrideForm'>
                <h3>
                    <span className='ic ovr'><Package size={12} /></span>
                    Clinician Override
                </h3>
                <p className='q'>Disagree with this score?</p>

                <Dropdown
                    dropdownLabel='New band'
                    name='clinician_esi'
                    value={overrideBand}
                    onChange={(name, value) => setOverrideBand(value)}
                    options={esiBandOptions}
                    placeholder='select…'
                />

                <Dropdown
                    dropdownLabel='Reason'
                    name='reason_code'
                    value={overrideReason}
                    onChange={(name, value) => setOverrideReason(value)}
                    options={overrideReasonOptions}
                    placeholder='select…'
                />

                <TextBox
                    boxLabel='Note'
                    name='note'
                    value={overrideNote}
                    onChange={(name, value) => setOverrideNote(value)}
                    placeholder='Optional note…'
                />

                {overrideError && (
                    <p className='overrideError'>{overrideError}</p>
                )}

                <button
                    className='overrideSubmit'
                    type='button'
                    onClick={handleOverrideSubmit}
                    disabled={!overrideBand || !overrideReason || submitting}
                >
                    {submitting ? 'Logging…' : 'Log Override'}
                </button>
            </div>

            <p className='disclaim'>
                Triage aid — not a diagnosis. Clinician judgment required.
            </p>
                </div>
            </div>
        </div>
    );
}


export default PatientDetail;
