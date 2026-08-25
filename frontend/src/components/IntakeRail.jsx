import { Link } from 'react-router-dom';
import { Gauge, Info, ListChecks, CircleCheck, CircleAlert } from 'lucide-react';


const NEXT_STEPS = [
    'Calculate severity score',
    'Add to priority queue',
    'Generate rule-based explanation',
    'Check red-flag triggers'
];


/** Teal once complete, amber while partial, so the bar reads at a glance. */
function barColour(done, total) {
    return done === total ? 'var(--teal)' : 'var(--amber)';
}


/**
 * Live intake summary: what is still missing, and what happens on submit.
 *
 * @param {object} props
 * @param {number} props.requiredDone - required fields answered
 * @param {number} props.requiredTotal - required fields currently on screen
 * @param {string[]} props.missingRequired - labels of unanswered required fields
 * @param {number} props.scoredVitalsDone - scored vitals entered
 * @param {number} props.scoredVitalsTotal - scored vitals available
 * @param {string[]} props.missingVitals - labels of scored vitals left blank
 * @param {object} [props.submitState] - outcome of the last submit, if any
 */
export default function IntakeRail({
    requiredDone,
    requiredTotal,
    missingRequired,
    scoredVitalsDone,
    scoredVitalsTotal,
    missingVitals,
    submitState
}) {
    const requiredComplete = missingRequired.length === 0;
    const vitalsPercent = Math.round((scoredVitalsDone / scoredVitalsTotal) * 100);
    const requiredPercent = Math.round((requiredDone / requiredTotal) * 100);

    return (
        <aside className='rail'>
            <div className='rcard qual'>
                <h4 className='teal'>
                    <Gauge size={16} />
                    Data Completeness
                </h4>

                <div className='qrow'>
                    <div className='qtop'>
                        <span>Required fields</span>
                        <span style={{ color: barColour(requiredDone, requiredTotal) }}>
                            {requiredDone} / {requiredTotal}
                        </span>
                    </div>
                    <div className='bar'>
                        <i
                            style={{
                                width: `${requiredPercent}%`,
                                background: barColour(requiredDone, requiredTotal)
                            }}
                        />
                    </div>
                </div>

                <div className='qrow'>
                    <div className='qtop'>
                        <span>Scored vitals</span>
                        <span
                            style={{
                                color: barColour(scoredVitalsDone, scoredVitalsTotal)
                            }}
                        >
                            {scoredVitalsDone} / {scoredVitalsTotal}
                        </span>
                    </div>
                    <div className='bar'>
                        <i
                            style={{
                                width: `${vitalsPercent}%`,
                                background: barColour(
                                    scoredVitalsDone,
                                    scoredVitalsTotal
                                )
                            }}
                        />
                    </div>
                    {missingVitals.length > 0 && (
                        <div className='msg'>
                            {missingVitals.join(', ')} not yet entered — those rules
                            will be skipped.
                        </div>
                    )}
                </div>
            </div>

            <div className='rcard'>
                <h4 className='blue'>
                    <Info size={16} />
                    System Feedback
                </h4>

                {/* A submit outcome outranks live completeness, otherwise the
                    cleared form would overwrite the result instantly. */}
                {submitState?.status === 'success' ? (
                    <div className='fb'>
                        <div className='ok'>
                            <CircleCheck size={15} />
                            Intake recorded.
                        </div>
                        {/* Scoring runs out-of-band now, so there is no score or
                            queue position to report yet. */}
                        <ul>
                            <li>Intake ID: {submitState.result.intake_id}</li>
                            <li>Queued for scoring — the score and queue position
                                appear once the scorer picks it up.</li>
                        </ul>
                        <Link
                            className='fblink'
                            to={`/intakes/${submitState.result.intake_id}`}
                        >
                            View patient →
                        </Link>
                    </div>
                ) : submitState?.status === 'error' ? (
                    <div className='fb error'>
                        <div className='ok'>
                            <CircleAlert size={15} />
                            {submitState.message}
                        </div>
                        {submitState.requestId && (
                            <ul>
                                <li>Reference: {submitState.requestId}</li>
                            </ul>
                        )}
                    </div>
                ) : requiredComplete ? (
                    <div className='fb'>
                        <div className='ok'>
                            <CircleCheck size={15} />
                            Required fields completed.
                        </div>
                        <ul>
                            <li>
                                Data completeness: {scoredVitalsDone}/
                                {scoredVitalsTotal} scored vitals
                            </li>
                            <li>Ready for scoring (fallbacks will apply)</li>
                        </ul>
                    </div>
                ) : (
                    <div className='fb warn'>
                        <div className='ok'>
                            <CircleAlert size={15} />
                            {missingRequired.length} required field
                            {missingRequired.length === 1 ? '' : 's'} outstanding.
                        </div>
                        <ul>
                            {missingRequired.map((label) => (
                                <li key={label}>{label}</li>
                            ))}
                        </ul>
                    </div>
                )}
            </div>

            <div className='rcard next'>
                <h4>
                    <ListChecks size={16} />
                    What Happens Next?
                </h4>

                {NEXT_STEPS.map((step) => (
                    <div className='step' key={step}>
                        <CircleCheck size={16} />
                        {step}
                    </div>
                ))}
            </div>
        </aside>
    );
}
