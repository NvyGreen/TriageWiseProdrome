import { useEffect, useRef, useState } from "react";
import { Zap, Import, Play, RotateCcw, Minus, Plus, Sparkles } from "lucide-react";

import "./DemoTools.css";


const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;

// Routes have no trailing slash; adding one would 307-redirect the POST.
const PRESETS_URL = `${API_BASE_URL}/demo/presets`;
const SIMULATION_URL = `${API_BASE_URL}/demo/simulation`;

const ESI_BANDS = ["1", "2", "3", "4", "5"];

// Not a preset — the sentinel for "the counts are whatever the user set".
const CUSTOM = "custom";

const EMPTY_COUNTS = Object.fromEntries(ESI_BANDS.map((band) => [band, 0]));

const EM_DASH = "—";


/**
 * arrival_epoch is Unix seconds, so it needs scaling to milliseconds. Rendered
 * in the browser's local zone and 12-hour, matching entered_at on the queue.
 */
function formatArrival(epoch) {
    if (epoch === null || epoch === undefined) {
        return EM_DASH;
    }

    return new Date(epoch * 1000).toLocaleTimeString("en-US", {
        hour: "numeric",
        minute: "2-digit",
        second: "2-digit",
        hour12: true
    });
}


/** "mass_casualty" -> "Mass casualty". */
function humanise(value) {
    const spaced = String(value).replace(/_/g, " ");

    return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}


/** A preset's per-band `n`, flattened to the shape the steppers hold. */
function countsFromPreset(preset) {
    return Object.fromEntries(
        ESI_BANDS.map((band) => [band, preset?.[band]?.n ?? 0])
    );
}


function DemoTools() {
    const [tab, setTab] = useState("sim");

    const [presets, setPresets] = useState(null);
    const [presetsError, setPresetsError] = useState(null);

    // null means Custom: the counts are the user's own, not a named preset.
    const [activePreset, setActivePreset] = useState(null);
    const [counts, setCounts] = useState(EMPTY_COUNTS);

    // null = never run. [] = ran and produced no arrivals, which the API treats
    // as a valid result rather than an error.
    const [rows, setRows] = useState(null);
    const [running, setRunning] = useState(false);
    const [runError, setRunError] = useState(null);
    const runController = useRef(null);

    useEffect(() => () => runController.current?.abort(), []);

    useEffect(() => {
        const controller = new AbortController();

        const load = async () => {
            try {
                const response = await fetch(PRESETS_URL, { signal: controller.signal });
                const data = await response.json().catch(() => null);

                if (!response.ok) {
                    setPresetsError(
                        data?.error?.message ??
                            `Could not load presets (HTTP ${response.status}).`
                    );
                    return;
                }

                const payload = data?.payload ?? {};
                const names = Object.keys(payload);

                setPresets(payload);

                // Start on the first preset so the steppers show a real mix
                // rather than an empty form.
                if (names.length > 0) {
                    setActivePreset(names[0]);
                    setCounts(countsFromPreset(payload[names[0]]));
                }
            } catch (fetchError) {
                if (fetchError.name === "AbortError") {
                    return;
                }

                console.error("Loading simulation presets failed:", fetchError);
                setPresetsError(
                    "Could not reach the server. Custom counts still work."
                );
            }
        };

        load();

        return () => controller.abort();
    }, []);

    const selectPreset = (name) => {
        if (name === CUSTOM) {
            setActivePreset(null);
            return;
        }

        setActivePreset(name);
        setCounts(countsFromPreset(presets?.[name]));
    };

    // Any manual change means the counts no longer describe the named preset,
    // so it becomes Custom — which also drops the preset's red flags.
    const adjustCount = (band, next) => {
        setCounts((previous) => ({ ...previous, [band]: Math.max(0, next) }));
        setActivePreset(null);
    };

    const total = ESI_BANDS.reduce((sum, band) => sum + (counts[band] || 0), 0);
    const presetNames = presets ? Object.keys(presets) : [];

    const handleRun = async () => {
        if (running) {
            return;
        }

        runController.current?.abort();
        const controller = new AbortController();
        runController.current = controller;

        setRunning(true);
        setRunError(null);

        // A named preset sends only its name, so the server's own config is what
        // runs. Custom sends counts with no flags - there is no UI to set them,
        // so claiming any would be inventing data.
        const body = activePreset
            ? { preset: activePreset }
            : {
                  custom_bands: Object.fromEntries(
                      ESI_BANDS.map((band) => [band, { n: counts[band] || 0, flags: {} }])
                  )
              };

        try {
            const response = await fetch(SIMULATION_URL, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(body),
                signal: controller.signal
            });

            const data = await response.json().catch(() => null);

            if (!response.ok) {
                const issues = (data?.error?.details ?? [])
                    .map((detail) => `${detail.field}: ${detail.issue}`)
                    .join("; ");

                setRunError(
                    issues ||
                        data?.error?.message ||
                        `Simulation failed (HTTP ${response.status}).`
                );

                return;
            }

            setRows(data?.payload ?? []);
        } catch (fetchError) {
            if (fetchError.name === "AbortError") {
                return;
            }

            console.error("Running the simulation failed:", fetchError);
            setRunError("Could not reach the server. Check the connection and try again.");
        } finally {
            if (!controller.signal.aborted) {
                setRunning(false);
            }
        }
    };

    const handleReset = () => {
        runController.current?.abort();
        setRows(null);
        setRunError(null);
        setRunning(false);
    };

    return (
        <div className='demo'>
            <div className='demobanner'>
                <div className='dot'>
                    <Sparkles size={17} />
                </div>
                <div className='txt'>
                    <strong>Demo workspace — nothing here touches the live triage queue.</strong>
                    <div>Simulations are sandboxed. No patient is scored, queued, or altered.</div>
                </div>
                <span className='badge'>Demo</span>
            </div>

            <div className='pagehead'>
                <h1 className='h1'>Demo Tools</h1>
                <p className='sub'>
                    Two separate demonstrations: stress-test the prioritisation logic
                    under a surge, or watch a real Epic FHIR record map into the intake
                    model.
                </p>
            </div>

            <div className='tabs' role='tablist'>
                <button
                    type='button'
                    className={tab === "sim" ? "tab on" : "tab"}
                    onClick={() => setTab("sim")}
                    role='tab'
                    aria-selected={tab === "sim"}
                >
                    <Zap size={15} />
                    What-if simulation
                </button>
                <button
                    type='button'
                    className={tab === "fhir" ? "tab on" : "tab"}
                    onClick={() => setTab("fhir")}
                    role='tab'
                    aria-selected={tab === "fhir"}
                >
                    <Import size={15} />
                    Epic FHIR import
                </button>
            </div>

            {tab === "sim" && (
                <div className='worktop'>
                    <div className='card'>
                        <h2>Build a surge</h2>
                        <p className='sub'>Pick a preset or set arrivals per band, then run.</p>

                        {presetsError && <p className='loaderror'>{presetsError}</p>}

                        <div className='chips'>
                            {presetNames.map((name) => (
                                <button
                                    type='button'
                                    key={name}
                                    className={activePreset === name ? "chip on" : "chip"}
                                    onClick={() => selectPreset(name)}
                                    aria-pressed={activePreset === name}
                                >
                                    {humanise(name)}
                                </button>
                            ))}

                            <button
                                type='button'
                                className={activePreset === null ? "chip on" : "chip"}
                                onClick={() => selectPreset(CUSTOM)}
                                aria-pressed={activePreset === null}
                            >
                                Custom
                            </button>
                        </div>

                        <label className='lbl'>Arrivals by ESI band</label>

                        <div className='bandgrid'>
                            {ESI_BANDS.map((band) => (
                                <div className='bandcell' key={band}>
                                    <label className='lbl' htmlFor={`band-${band}`}>
                                        ESI-{band}
                                    </label>
                                    <div className='stepper'>
                                        <button
                                            type='button'
                                            onClick={() => adjustCount(band, (counts[band] || 0) - 1)}
                                            aria-label={`One fewer ESI-${band} arrival`}
                                        >
                                            <Minus size={14} />
                                        </button>
                                        <input
                                            id={`band-${band}`}
                                            type='number'
                                            min='0'
                                            value={counts[band]}
                                            onChange={(event) =>
                                                adjustCount(band, parseInt(event.target.value, 10) || 0)
                                            }
                                        />
                                        <button
                                            type='button'
                                            onClick={() => adjustCount(band, (counts[band] || 0) + 1)}
                                            aria-label={`One more ESI-${band} arrival`}
                                        >
                                            <Plus size={14} />
                                        </button>
                                    </div>
                                </div>
                            ))}
                        </div>

                        <p className='simtotal'>
                            Total arrivals: <strong>{total}</strong>
                        </p>

                        {/* Red flags come from a preset's own config; there is no UI
                            to set them, so editing counts drops them. */}
                        <p className='flagnote'>
                            Presets carry their own red flags. Adjusting any count
                            switches to Custom, which runs without flags.
                        </p>

                        <div className='btnrow'>
                            <button
                                className='btn btn-primary'
                                type='button'
                                onClick={handleRun}
                                disabled={running}
                            >
                                <Play size={14} />
                                {running ? 'Running...' : 'Run simulation'}
                            </button>
                            <button
                                className='btn btn-ghost'
                                type='button'
                                onClick={handleReset}
                                disabled={running || rows === null}
                            >
                                <RotateCcw size={14} />
                                Reset
                            </button>
                        </div>
                    </div>

                    <div className='outpanel'>
                        <div className='outhead'>
                            <h3>Resulting queue order</h3>
                            {rows !== null && rows.length > 0 && (
                                <span className='meta'>
                                    {rows.length} arrivals · sorted by ESI, then red-flag tier
                                </span>
                            )}
                        </div>
                        <p className='outnote'>
                            All arrivals are synthetic (SIM-###) with generated vitals.
                            This ordering is a preview only — no real patient is created
                            or queued. Arrival time only breaks ties within a band and
                            flag tier, so later arrivals can outrank earlier ones.
                        </p>

                        {running && <p className='empty'>Running simulation…</p>}

                        {!running && runError && <p className='loaderror'>{runError}</p>}

                        {!running && !runError && rows === null && (
                            <p className='empty'>
                                Set a surge and run a simulation to see the queue order.
                            </p>
                        )}

                        {!running && !runError && rows !== null && rows.length === 0 && (
                            <p className='empty'>
                                That surge had no arrivals - every band was set to zero.
                            </p>
                        )}

                        {!running && !runError && rows !== null && rows.length > 0 && (
                            <table className='simtable'>
                                <thead>
                                    <tr>
                                        <th className='col-pos'>#</th>
                                        <th>Patient</th>
                                        <th>ESI</th>
                                        <th>Red flag</th>
                                        <th>Arrival</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {rows.map((row) => (
                                        <tr key={row.sim_id}>
                                            <td className='pos'>{row.position}</td>
                                            <td className='simid'>{row.sim_id}</td>
                                            <td>
                                                <span className={`pill e${row.esi_band}`}>
                                                    ESI-{row.esi_band}
                                                </span>
                                            </td>
                                            <td>
                                                {row.flag_label ? (
                                                    <span className='flagcell'>
                                                        <span className={`flagdot fd${row.flag_tier}`} />
                                                        {row.flag_label}
                                                    </span>
                                                ) : (
                                                    <span className='noflag'>{EM_DASH}</span>
                                                )}
                                            </td>
                                            <td className='arrival'>
                                                {formatArrival(row.arrival_epoch)}
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        )}
                    </div>
                </div>
            )}

            {tab === "fhir" && (
                <div className='worktop'>
                    <div className='card'>
                        <h2>Fetch a sandbox patient</h2>
                        <p className='sub'>
                            Pull a record from the Epic sandbox and map its FHIR
                            resources into the intake model.
                        </p>
                        {/* No backend for this yet — controls are inert on purpose. */}
                        <p className='placeholder'>
                            Epic FHIR import isn't available yet.
                        </p>
                    </div>

                    <div className='outpanel'>
                        <div className='outhead'>
                            <h3>FHIR → intake mapping</h3>
                        </div>
                        <p className='empty'>
                            Nothing to show until the import is built.
                        </p>
                    </div>
                </div>
            )}
        </div>
    );
}


export default DemoTools;
