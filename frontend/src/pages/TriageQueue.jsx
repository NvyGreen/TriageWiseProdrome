import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Search, TriangleAlert, CircleAlert, RefreshCw } from "lucide-react";

import TextBox from "../components/TextBox";
import Dropdown from "../components/Dropdown";

import "./TriageQueue.css";


const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;

// Values match the Status enum in backend/app/schemas/intake_update.py.
const statusOptions = [
    { value: "WAITING", display: "Waiting" },
    { value: "IN_ROOM", display: "In Room" },
    { value: "DISPOSITIONED", display: "Dispositioned" }
];

// Tier 3 is the scoring engine's "no red flag" value; null means scoring has
// not run yet. Neither should render as a flag.
const NO_FLAG_TIER = 3;

const EM_DASH = "—";

// IntakeUpdate accepts a status or vitals, never both. Explicit nulls read as
// "not provided" on the Python side, so they don't trip that rule.
const BLANK_VITALS = {
    heart_rate: null,
    blood_pressure_systolic: null,
    blood_pressure_diastolic: null,
    temperature: null,
    oxygen_saturation: null,
    respiration_rate: null,
    pain_level: null,
    blood_sugar: null
};


/**
 * The API returns handled errors as { error }, some as { detail }, and an
 * unhandled server fault as no JSON at all — so the status code is the only
 * thing that is always there.
 */
function describeStatusFailure(name, status, data) {
    const detail =
        data?.error?.message ??
        (typeof data?.detail === "string" ? data.detail : null) ??
        `The server returned HTTP ${status}.`;

    return `Could not update ${name}'s status. ${detail}`;
}

// Row tint and status-pill colour both key off status.
const STATUS_MODIFIERS = {
    WAITING: { row: "", pill: "st-waiting", badge: null },
    IN_ROOM: { row: "inroom", pill: "st-inroom", badge: "In Room" },
    DISPOSITIONED: { row: "done", pill: "st-done", badge: "Completed" }
};


/** "ESI-2" -> "e2". Scoring may not have run, in which case there is no band. */
function esiModifier(esiLevel) {
    return esiLevel ? `e${esiLevel.slice(-1)}` : null;
}


function FlagCell({ tier }) {
    if (tier === null || tier === undefined || tier === NO_FLAG_TIER) {
        return <span className='flag none'>{EM_DASH}</span>;
    }

    const Icon = tier === 1 ? TriangleAlert : CircleAlert;

    return (
        <span className={`flag t${tier}`}>
            <Icon size={11} />
            Tier {tier}
        </span>
    );
}


function formatEnteredAt(timestamp) {
    return new Date(timestamp).toLocaleTimeString("en-US", {
        hour: "numeric",
        minute: "2-digit",
        hour12: true
    });
}


function QueueRow({ patient, status, onStatusChange, pending }) {
    const modifiers = STATUS_MODIFIERS[status] ?? STATUS_MODIFIERS.WAITING;
    const esiClass = esiModifier(patient.esi_level);

    // Dispositioning drops the intake from the queue, so the API has no way to
    // put it back. Locked until the queue is persisted and reversal works.
    const locked = status === "DISPOSITIONED";

    return (
        <tr className={modifiers.row}>
            {/* A dispositioned patient has left the queue, so a rank would
                misrepresent them. */}
            <td>
                <span className='pos'>
                    {status === "DISPOSITIONED" ? EM_DASH : patient.position}
                </span>
            </td>

            <td>
                <div className='nm'>
                    {/* Only the name is the link — the row holds a select, and a
                        whole-row target would swallow its clicks. */}
                    <Link className='namelink' to={`/intakes/${patient.intake_id}`}>
                        {patient.name}
                    </Link>{' '}
                    <span className='ag'>{patient.age} / {patient.sex}</span>
                    {modifiers.badge && (
                        <span className={`statebadge ${modifiers.row}`}>
                            {modifiers.badge}
                        </span>
                    )}
                </div>
                <div className='pid'>ID {patient.patient_id}</div>
            </td>

            <td>
                {esiClass ? (
                    <span className={`esi ${esiClass}`}>{patient.esi_level}</span>
                ) : (
                    <span className='flag none'>{EM_DASH}</span>
                )}
            </td>

            <td>
                <FlagCell tier={patient.flag_tier} />
            </td>

            <td>
                {patient.severity_score === null ? (
                    <span className='flag none'>{EM_DASH}</span>
                ) : (
                    <span className='pts'>
                        {patient.severity_score}
                        <small> pts</small>
                    </span>
                )}
            </td>

            <td className='ag'>{formatEnteredAt(patient.entered_at)}</td>

            <td>
                <span
                    className={`statussel ${modifiers.pill}`}
                    title={locked ? 'A dispositioned patient has left the queue.' : undefined}
                >
                    <Dropdown
                        name='status'
                        value={status}
                        onChange={onStatusChange}
                        options={statusOptions}
                        disabled={locked || pending}
                        ariaLabel={`Status for ${patient.name}`}
                    />
                </span>
            </td>
        </tr>
    );
}


function TriageQueue() {
    const [text, setText] = useState("");
    const [showCompleted, setShowCompleted] = useState(false);

    const [entries, setEntries] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    // One entry per row rather than a single shared value, so changing one
    // patient's status doesn't change everyone's. Seeded from the queue data.
    const [statuses, setStatuses] = useState({});

    // Keyed by intake_id, so a slow request only locks its own row.
    const [pending, setPending] = useState({});
    const [statusError, setStatusError] = useState(null);

    // Dispositioning drops a patient from the queue, so a refetch would erase
    // the row that just moved to Completed. Held until the page unmounts.
    const [pinned, setPinned] = useState([]);

    const [refreshing, setRefreshing] = useState(false);
    const [lastUpdated, setLastUpdated] = useState(null);
    const refreshController = useRef(null);

    // No synchronous setState here: `loading` already starts true, and the
    // retry handler sets it before calling. Setting it here would cascade an
    // extra render on mount.
    const loadQueue = useCallback(async (signal) => {
        try {
            const response = await fetch(`${API_BASE_URL}/queue/`, { signal });
            const data = await response.json().catch(() => null);

            if (!response.ok) {
                setError(
                    data?.error?.message ?? `Could not load the queue (HTTP ${response.status}).`
                );
                return;
            }

            // Successful responses are wrapped by MedicalDisclaimerResponse.
            const queueEntries = data?.payload?.entries ?? [];

            setError(null);
            setEntries(queueEntries);
            setLastUpdated(new Date());

            // getQueue reports every entry as WAITING, so a plain overwrite
            // would revert any status set this session. Local values win.
            // Remove this merge once status is persisted server-side.
            setStatuses((prev) => {
                const merged = { ...prev };

                for (const patient of queueEntries) {
                    merged[patient.intake_id] =
                        prev[patient.intake_id] ?? patient.status;
                }

                return merged;
            });
        } catch (fetchError) {
            // An aborted request is a cancelled render, not a failure.
            if (fetchError.name === 'AbortError') {
                return;
            }

            console.error('Loading the queue failed:', fetchError);
            setError('Could not reach the server. Check the connection and try again.');
        } finally {
            if (!signal?.aborted) {
                setLoading(false);
            }
        }
    }, []);

    useEffect(() => {
        // Aborting on unmount stops StrictMode's double-mount from leaving a
        // second response to land on a component that is gone.
        const controller = new AbortController();

        // The rule flags any setState reachable from an effect. Here it all
        // happens in the promise callback once the response lands, which is the
        // fetch-on-mount pattern the rule's own docs allow.
        // eslint-disable-next-line react-hooks/set-state-in-effect
        loadQueue(controller.signal);

        return () => controller.abort();
    }, [loadQueue]);

    const handleRetry = () => {
        // Same controller as refresh, so a retry is abortable and the unmount
        // cleanup below covers it too.
        refreshController.current?.abort();

        const controller = new AbortController();
        refreshController.current = controller;

        setLoading(true);
        setError(null);
        loadQueue(controller.signal);
    };

    // Keeps the table on screen and only marks the button busy, so the list
    // doesn't blank out on every refresh.
    const refresh = useCallback(async () => {
        // A slower earlier response must not land after a newer one.
        refreshController.current?.abort();

        const controller = new AbortController();
        refreshController.current = controller;

        setRefreshing(true);

        try {
            await loadQueue(controller.signal);
        } finally {
            if (!controller.signal.aborted) {
                setRefreshing(false);
            }
        }
    }, [loadQueue]);

    useEffect(() => () => refreshController.current?.abort(), []);

    // TextBox and Dropdown both report (name, value); the field key is already
    // known here, so only the value is kept.
    const handleSearchChange = (name, value) => {
        setText(value);
    };

    // Applied locally first so the row reacts immediately, then reverted if the
    // API rejects it.
    const handleStatusChange = (patient) => async (name, value) => {
        const intakeId = patient.intake_id;
        const previous = statuses[intakeId];

        if (value === previous || pending[intakeId]) {
            return;
        }

        setStatuses((prev) => ({ ...prev, [intakeId]: value }));
        setPending((prev) => ({ ...prev, [intakeId]: true }));
        setStatusError(null);

        try {
            const response = await fetch(`${API_BASE_URL}/intakes/${intakeId}`, {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ ...BLANK_VITALS, status: value })
            });

            const data = await response.json().catch(() => null);

            if (!response.ok) {
                setStatuses((prev) => ({ ...prev, [intakeId]: previous }));
                setStatusError(
                    describeStatusFailure(patient.name, response.status, data)
                );

                return;
            }

            // The API drops dispositioned patients from the queue, so keep a
            // copy before refetching or the row would simply vanish.
            if (value === "DISPOSITIONED") {
                setPinned((prev) =>
                    prev.some((entry) => entry.intake_id === intakeId)
                        ? prev
                        : [...prev, patient]
                );
            }

            // Positions shift when a patient leaves the queue.
            refresh();
        } catch (patchError) {
            console.error("Status update failed:", patchError);

            setStatuses((prev) => ({ ...prev, [intakeId]: previous }));
            setStatusError(
                `Could not update ${patient.name}'s status. The server could not be reached.`
            );
        } finally {
            setPending((prev) => {
                const next = { ...prev };
                delete next[intakeId];

                return next;
            });
        }
    };

    // Name only — searching by ID was dropped from the mockup on purpose.
    const query = text.trim().toLowerCase();
    const matchesQuery = (patient) =>
        query === "" || patient.name.toLowerCase().includes(query);

    // Server entries plus any this session dispositioned, which the API no
    // longer returns.
    const serverIds = new Set(entries.map((patient) => patient.intake_id));
    const allEntries = [
        ...entries,
        ...pinned.filter((patient) => !serverIds.has(patient.intake_id))
    ];

    // Live status decides which list a patient belongs to, so dispositioning
    // someone moves them out of the active queue immediately.
    const active = allEntries.filter(
        (patient) =>
            statuses[patient.intake_id] !== "DISPOSITIONED" && matchesQuery(patient)
    );
    const completed = allEntries.filter(
        (patient) =>
            statuses[patient.intake_id] === "DISPOSITIONED" && matchesQuery(patient)
    );

    const visibleCount = active.length + (showCompleted ? completed.length : 0);
    // Matches hidden behind the toggle would otherwise read as "no results".
    const hiddenMatches = showCompleted ? 0 : completed.length;

    return (
        <div className='queue'>
            <h1 className='h1'>Triage Queue</h1>
            <p className='sub'>Ranked by ESI, then red-flag tier, then arrival. Set a patient's status as they move through care.</p>

            <div className='toolbar'>
                <div className='search'>
                    <TextBox
                        name='searchbar'
                        value={text}
                        onChange={handleSearchChange}
                        placeholder='Search patients by name…'
                        icon={Search}
                        ariaLabel='Search patients by name'
                    />
                </div>

                <div className='toolbar-right'>
                    {lastUpdated && (
                        <span className='updated'>
                            Updated {formatEnteredAt(lastUpdated)}
                        </span>
                    )}

                    <button
                        type='button'
                        className='refresh'
                        onClick={refresh}
                        disabled={loading || refreshing}
                    >
                        <RefreshCw size={14} className={refreshing ? 'spin' : undefined} />
                        {refreshing ? 'Refreshing…' : 'Refresh'}
                    </button>

                    <button
                        type='button'
                        className={showCompleted ? 'showcompleted on' : 'showcompleted'}
                        onClick={() => setShowCompleted((previous) => !previous)}
                        aria-pressed={showCompleted}
                    >
                        <span>Show completed</span>
                        <span className='box' />
                    </button>
                </div>
            </div>

            {statusError && (
                <div className='banner' role='alert'>
                    <CircleAlert size={16} />
                    <span>{statusError}</span>
                    <button
                        type='button'
                        className='banner-dismiss'
                        onClick={() => setStatusError(null)}
                        aria-label='Dismiss'
                    >
                        ×
                    </button>
                </div>
            )}

            <div className='tablecard'>
                <div className='tablewrap'>
                    <table>
                        <thead>
                            <tr>
                                <th className='col-pos'>#</th>
                                <th>Patient</th>
                                <th>ESI</th>
                                <th>Red Flag</th>
                                <th>Severity</th>
                                <th>Entered</th>
                                <th className='col-status'>Status</th>
                            </tr>
                        </thead>
                        <tbody>
                            {loading && (
                                <tr className='noresults'>
                                    <td colSpan={7}>Loading queue…</td>
                                </tr>
                            )}

                            {!loading && error && (
                                <tr className='noresults'>
                                    <td colSpan={7}>
                                        <div className='loaderror'>{error}</div>
                                        <button
                                            type='button'
                                            className='retry'
                                            onClick={handleRetry}
                                        >
                                            Retry
                                        </button>
                                    </td>
                                </tr>
                            )}

                            {!loading && !error && visibleCount === 0 && (
                                <tr className='noresults'>
                                    <td colSpan={7}>
                                        {query === ""
                                            ? "No patients in the queue."
                                            : `No active patients match “${text.trim()}”.`}
                                        {hiddenMatches > 0 && (
                                            <>
                                                {" "}
                                                {hiddenMatches} completed{" "}
                                                {hiddenMatches === 1 ? "patient" : "patients"}{" "}
                                                also {hiddenMatches === 1 ? "matches" : "match"} —
                                                turn on Show completed to see{" "}
                                                {hiddenMatches === 1 ? "them" : "those"}.
                                            </>
                                        )}
                                    </td>
                                </tr>
                            )}

                            {active.map((patient) => (
                                <QueueRow
                                    key={patient.intake_id}
                                    patient={patient}
                                    status={statuses[patient.intake_id]}
                                    onStatusChange={handleStatusChange(patient)}
                                    pending={Boolean(pending[patient.intake_id])}
                                />
                            ))}

                            {showCompleted && completed.length > 0 && (
                                <tr className='sectlabel'>
                                    <td colSpan={7}>Completed</td>
                                </tr>
                            )}

                            {showCompleted &&
                                completed.map((patient) => (
                                    <QueueRow
                                        key={patient.intake_id}
                                        patient={patient}
                                        status={statuses[patient.intake_id]}
                                        onStatusChange={handleStatusChange(patient)}
                                        pending={Boolean(pending[patient.intake_id])}
                                    />
                                ))}
                        </tbody>
                    </table>
                </div>
            </div>

            <p className='note'>
                Status flow: Waiting → In Room → Dispositioned. In-Room patients keep their position; Dispositioned patients leave the active queue and appear under "Show completed". A patient can be moved In Room → Waiting if bumped.
            </p>
        </div>
    );
}


export default TriageQueue;
