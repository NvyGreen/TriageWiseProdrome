import { useEffect, useState } from "react";

import "./ScoringRules.css";


const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;

const ENDPOINTS = {
    scoringRules: `${API_BASE_URL}/rules/scoring-rules`,
    esiBands: `${API_BASE_URL}/rules/esi-bands`,
    redFlags: `${API_BASE_URL}/rules/red-flags`,
    complaintEsi: `${API_BASE_URL}/rules/complaint-esi`
};

const TABS = [
    { id: "ruleconfig", label: "Rule Configuration" },
    { id: "redflags", label: "Red Flags" },
    { id: "scoring", label: "Scoring Behavior" }
];

// ESI-1 has no real upper bound; the band table stores 99 as a sentinel.
const OPEN_ENDED_MAX = 99;

const EM_DASH = "—";

// Static by design: a fixed illustration of how the rules combine, not a live
// engine run. The numbers below are read straight off the rules above it.
const WORKED_EXAMPLE = {
    caption: "Synthetic case: cardiac complaint, SpO₂ 89%, HR 128.",
    lines: [
        { label: "Chief complaint — cardiac", points: 6 },
        { label: "SpO₂ 89% (≤91%)", points: 4 },
        { label: "Heart rate 128 (≥121)", points: 3 }
    ],
    total: 13,
    esi: "ESI-1"
};


/** "minor_injury" -> "Minor injury". */
function humanise(value) {
    const spaced = String(value).replace(/_/g, " ");

    return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}


/** "%" and "/10" read better flush against the number than spaced off it. */
function withUnits(value, units) {
    if (!units) {
        return String(value);
    }

    return units.startsWith("%") || units.startsWith("/")
        ? `${value}${units}`
        : `${value} ${units}`;
}


/** A rule's firing range, from whichever bounds it actually has. */
function formatBand(rule) {
    const { min_bound: min, max_bound: max, units } = rule;

    if (min === null && max === null) {
        return "any";
    }

    if (min === null) {
        return withUnits(`≤ ${max}`, units);
    }

    if (max === null) {
        return withUnits(`≥ ${min}`, units);
    }

    return withUnits(`${min}–${max}`, units);
}


/** ESI-1 stores 99 as its max, so it reads as "8+" rather than "8–99". */
function formatPoints(band) {
    if (band.max_points >= OPEN_ENDED_MAX) {
        return `${band.min_points}+`;
    }

    if (band.min_points === band.max_points) {
        return String(band.min_points);
    }

    return `${band.min_points}–${band.max_points}`;
}


/** Heavier rules read hotter. */
function weightTone(weight) {
    if (weight >= 4) {
        return "w4";
    }

    if (weight >= 3) {
        return "w3";
    }

    return weight >= 2 ? "w2" : "w1";
}


/** "ESI-2" -> "e2", for the band pill colours. */
function esiTone(esi) {
    return `e${String(esi).slice(-1)}`;
}


/** Vital and age rules share a shape, so they group together by factor. */
function groupByFactor(rules) {
    const groups = new Map();

    for (const rule of rules) {
        if (!groups.has(rule.factor)) {
            groups.set(rule.factor, []);
        }

        groups.get(rule.factor).push(rule);
    }

    // Heaviest band first within each factor, so the most acute reads leftmost.
    for (const bands of groups.values()) {
        bands.sort((a, b) => b.weight - a.weight);
    }

    // Widest factor first, so the blank padding cells collect at the bottom
    // right rather than scattering. sort is stable, so factors with the same
    // band count keep the order the API returned them in.
    return [...groups.entries()].sort(
        ([, aBands], [, bBands]) => bBands.length - aBands.length
    );
}


function ScoringRules() {
    const [tab, setTab] = useState("ruleconfig");
    const [data, setData] = useState(null);
    const [error, setError] = useState(null);

    useEffect(() => {
        const controller = new AbortController();

        const load = async () => {
            try {
                // Four small read-only endpoints; fetching together keeps tab
                // switches instant.
                const responses = await Promise.all(
                    Object.values(ENDPOINTS).map((url) =>
                        fetch(url, { signal: controller.signal })
                    )
                );

                const failed = responses.find((response) => !response.ok);

                if (failed) {
                    const body = await failed.json().catch(() => null);

                    setError(
                        body?.error?.message ??
                            `Could not load the rules (HTTP ${failed.status}).`
                    );

                    return;
                }

                const [scoringRules, esiBands, redFlags, complaintEsi] =
                    await Promise.all(responses.map((response) => response.json()));

                setData({
                    scoringRules: scoringRules.payload,
                    esiBands: esiBands.payload,
                    redFlags: redFlags.payload,
                    complaintEsi: complaintEsi.payload
                });
            } catch (fetchError) {
                if (fetchError.name === "AbortError") {
                    return;
                }

                console.error("Loading the rules failed:", fetchError);
                setError("Could not reach the server. Check the connection and try again.");
            }
        };

        load();

        return () => controller.abort();
    }, []);

    if (error) {
        return (
            <div className='rules'>
                <h1 className='h1'>Scoring &amp; Rules</h1>
                <div className='panel emptystate'>
                    <p className='loaderror'>{error}</p>
                </div>
            </div>
        );
    }

    if (data === null) {
        return (
            <div className='rules'>
                <h1 className='h1'>Scoring &amp; Rules</h1>
                <div className='panel emptystate'>
                    <p>Loading rules…</p>
                </div>
            </div>
        );
    }

    const { scoringRules, esiBands, redFlags, complaintEsi } = data;
    const complaints = scoringRules.complaint ?? [];
    const vitalRules = scoringRules.vital ?? [];
    const ageRules = scoringRules.age ?? [];

    const maxWeight = Math.max(...complaints.map((rule) => rule.weight), 1);
    const thresholdGroups = groupByFactor([...vitalRules, ...ageRules]);

    // Every row gets the same column count, set by whichever factor has the most
    // bands, so the cells line up down the table.
    const bandColumns = Math.max(
        ...thresholdGroups.map(([, bands]) => bands.length),
        1
    );

    const tier1 = redFlags["Tier 1"] ?? [];
    const tier2 = redFlags["Tier 2"] ?? [];
    const flagTotal = tier1.length + tier2.length;
    const tier1Share = flagTotal > 0 ? (tier1.length / flagTotal) * 100 : 0;

    return (
        <div className='rules'>
            <div className='head'>
                <h1 className='h1'>Scoring &amp; Rules</h1>
                <p className='sub'>
                    Rule configuration, red-flag catalogue, deterministic scoring
                    behavior, and reference-data provenance.
                </p>
            </div>

            <div className='tabs' role='tablist'>
                {TABS.map((item) => (
                    <button
                        type='button'
                        key={item.id}
                        className={tab === item.id ? "tab on" : "tab"}
                        onClick={() => setTab(item.id)}
                        role='tab'
                        aria-selected={tab === item.id}
                    >
                        {item.label}
                    </button>
                ))}
            </div>

            {tab === "ruleconfig" && (
                <>
                    <div className='grid2'>
                        <div className='panel'>
                            <h3>
                                Complaint Weights
                                <span className='badge derived'>scoring_rule</span>
                            </h3>
                            <p className='psub'>
                                Each chief complaint's base weight, resource level, and
                                ESI anchor.
                            </p>

                            {complaints.map((rule) => (
                                <div className='cwgroup' key={rule.complaint_group}>
                                    <div className='cwrow'>
                                        <span className='lbl'>
                                            {humanise(rule.complaint_group)}
                                        </span>
                                        <div className='cwtrack'>
                                            <div
                                                className='cwfill'
                                                style={{
                                                    width: `${(rule.weight / maxWeight) * 100}%`
                                                }}
                                            />
                                        </div>
                                        <span className='cwval'>{rule.weight}</span>
                                    </div>
                                    <div className='cwmeta'>
                                        {rule.resource_level} resources · {rule.esi_anchor}
                                    </div>
                                </div>
                            ))}
                        </div>

                        <div className='panel'>
                            <h3>
                                ESI Point Thresholds
                                <span className='badge derived'>esi_band</span>
                            </h3>
                            <p className='psub'>Total points required to reach each band.</p>

                            <table>
                                <thead>
                                    <tr>
                                        <th>Band</th>
                                        <th>Points</th>
                                        <th>Label</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {esiBands.map((band) => (
                                        <tr key={band.esi_level}>
                                            <td>
                                                <span className={`esitag ${esiTone(band.esi_level)}`}>
                                                    {band.esi_level}
                                                </span>
                                            </td>
                                            <td>{formatPoints(band)}</td>
                                            <td>{band.label}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>

                            <p className='footnote'>
                                ESI-3 is refined by resource level: none → ESI-5, one →
                                ESI-4, many → stays ESI-3.
                            </p>

                            <h3 className='spaced'>
                                Rule Counts
                                <span className='badge derived'>scoring_rule</span>
                            </h3>

                            <div className='rc'>
                                <span>Vital-sign rules</span>
                                <span className='n'>{vitalRules.length}</span>
                            </div>
                            {ageRules.length > 0 && (
                                <div className='rc'>
                                    <span>Age rules</span>
                                    <span className='n'>{ageRules.length}</span>
                                </div>
                            )}
                            <div className='rc'>
                                <span>Complaint rules</span>
                                <span className='n'>{complaints.length}</span>
                            </div>
                            <div className='rc'>
                                <span>Total active</span>
                                <span className='n'>
                                    {scoringRules.active_rules}
                                    <span className='off'>of {scoringRules.total_rules}</span>
                                </span>
                            </div>
                        </div>
                    </div>

                    <div className='panel'>
                        <h3>
                            Vital/Age Threshold Bands
                            <span className='badge derived'>scoring_rule</span>
                        </h3>
                        <p className='psub'>
                            Points added per band. Only bands that fire are listed —
                            anything outside them scores 0.
                        </p>

                        {thresholdGroups.map(([factor, bands]) => (
                            <div className='heatrow' key={factor}>
                                <span className='heatlbl'>{factor}</span>
                                {/* A custom property rather than an inline
                                    grid-template, so the narrow-screen override
                                    can still win. */}
                                <div
                                    className='heatcells'
                                    style={{ "--band-columns": bandColumns }}
                                >
                                    {bands.map((band) => (
                                        <span
                                            className={`heatcell ${weightTone(band.weight)}`}
                                            key={`${factor}-${band.min_bound}-${band.max_bound}`}
                                        >
                                            {formatBand(band)} · +{band.weight}
                                        </span>
                                    ))}

                                    {/* Padding only — this factor has no band here,
                                        which is not the same as a band worth 0. */}
                                    {Array.from(
                                        { length: bandColumns - bands.length },
                                        (unused, index) => (
                                            <span
                                                className='heatcell blank'
                                                key={`${factor}-blank-${index}`}
                                                aria-hidden='true'
                                            >
                                                {EM_DASH}
                                            </span>
                                        )
                                    )}
                                </div>
                            </div>
                        ))}
                    </div>
                </>
            )}

            {tab === "redflags" && (
                <>
                    <div className='panel'>
                        <h3>
                            Flags by Tier
                            <span className='badge derived'>red_flag_rule</span>
                        </h3>
                        <p className='psub'>
                            {flagTotal} active rules, split by escalation tier.
                        </p>

                        <div className='tiersplit'>
                            <div className='t1' style={{ width: `${tier1Share}%` }} />
                            <div className='t2' style={{ width: `${100 - tier1Share}%` }} />
                        </div>

                        <div className='tierlegend'>
                            <span>
                                <i className='d t1' />
                                Time-critical ({tier1.length})
                            </span>
                            <span>
                                <i className='d t2' />
                                Occult ({tier2.length})
                            </span>
                        </div>
                    </div>

                    <div className='panel'>
                        <h3>
                            Rule Catalogue
                            <span className='badge derived'>red_flag_rule</span>
                        </h3>
                        <p className='psub'>
                            Every active rule, in full — message, rationale, tier,
                            inspected fields, helper functions used, and tree depth.
                        </p>

                        <table className='ruletable'>
                            <thead>
                                <tr>
                                    <th>Message / rationale</th>
                                    <th>Tier</th>
                                    <th>Fields</th>
                                    <th>Helpers</th>
                                    <th>Depth</th>
                                </tr>
                            </thead>
                            <tbody>
                                {[...tier1, ...tier2].map((flag) => (
                                    <tr key={flag.message}>
                                        <td>
                                            <div className='rmsg'>{flag.message}</div>
                                            <div className='rrat'>{flag.rationale}</div>
                                        </td>
                                        <td className='rcentre'>
                                            <span className={`flagtier t${flag.flag_tier}`}>
                                                {flag.flag_tier}
                                            </span>
                                        </td>
                                        <td className='rfields'>
                                            {flag.fields.length > 0 ? (
                                                flag.fields.join(", ")
                                            ) : (
                                                <span className='rnone'>{EM_DASH}</span>
                                            )}
                                        </td>
                                        <td className='rhelpers'>
                                            {flag.helpers.length > 0 ? (
                                                flag.helpers.join(", ")
                                            ) : (
                                                <span className='rnone'>{EM_DASH}</span>
                                            )}
                                        </td>
                                        <td className='rcentre rdepth'>{flag.depth}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>

                        <p className='footnote'>
                            Depth = nested AND/OR levels in the trigger tree only;
                            helper-driven rules can be depth 0 because their logic lives
                            in code, not the tree — so read Fields and Helpers (which now
                            include what each helper inspects) for what a rule actually
                            looks at, not depth.
                        </p>
                    </div>
                </>
            )}

            {tab === "scoring" && (
                <div className='grid2'>
                    <div className='panel'>
                        <h3>
                            Baseline ESI by Complaint
                            <span className='badge derived'>derived from rules</span>
                        </h3>
                        <p className='psub'>
                            Each complaint scored alone, all vitals normal.
                        </p>

                        <table>
                            <thead>
                                <tr>
                                    <th>Complaint</th>
                                    <th>Points</th>
                                    <th>ESI</th>
                                </tr>
                            </thead>
                            <tbody>
                                {complaintEsi.map((row) => (
                                    <tr key={row.complaint}>
                                        <td>{humanise(row.complaint)}</td>
                                        <td>{row.points}</td>
                                        <td>
                                            <span className={`esitag ${esiTone(row.esi)}`}>
                                                {row.esi}
                                            </span>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>

                    <div className='panel'>
                        <h3>
                            Worked Example
                            <span className='badge derived'>derived from rules</span>
                        </h3>
                        <p className='psub'>{WORKED_EXAMPLE.caption}</p>

                        {WORKED_EXAMPLE.lines.map((line) => (
                            <div className='drow' key={line.label}>
                                <span className='f'>{line.label}</span>
                                <span className='w'>+{line.points}</span>
                            </div>
                        ))}

                        <div className='dtotal'>
                            <span>Total → {WORKED_EXAMPLE.esi}</span>
                            <span>{WORKED_EXAMPLE.total} pts</span>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}


export default ScoringRules;
