import { useRef, useState } from 'react';
import { User, Calendar, Info, ClipboardCheck, UserPlus } from 'lucide-react';

import TextBox from '../components/TextBox';
import TextArea from '../components/TextArea';
import Dropdown from '../components/Dropdown';
import RadioGroup from '../components/RadioGroup';
import CheckGroup from '../components/CheckGroup';
import IntakeRail from '../components/IntakeRail';

import './PatientIntake.css';


// Option values mirror backend/app/utils/enums.py exactly.
const sexOptions = [
    { value: 'F', display: 'Female' },
    { value: 'M', display: 'Male' },
    { value: 'other', display: 'Other' },
    { value: 'unknown', display: 'Unknown' }
];

const pregnancyOptions = [
    { value: 'none', display: 'None' },
    { value: 'pregnant', display: 'Pregnant' },
    { value: 'postpartum', display: 'Postpartum' }
];

const preExistingConditionsOptions = [
    { value: 'diabetes', display: 'Diabetes' },
    { value: 'hypertension', display: 'Hypertension' },
    { value: 'chf', display: 'CHF' },
    { value: 'copd', display: 'COPD' },
    { value: 'prior_mi', display: 'Prior MI / CAD' },
    { value: 'prior_stroke', display: 'Prior Stroke / TIA' },
    { value: 'cancer', display: 'Cancer' },
    { value: 'anticoagulant', display: 'Anticoagulant use' },
    { value: 'immunocompromised', display: 'Immunocompromised (chemo / transplant / chronic steroids)' },
    { value: 'sickle_cell', display: 'Sickle cell disease' }
];

// Strings, not booleans: the DOM only stores input values as strings, so a
// boolean here can never match what comes back out. Converted at submit.
const yesNoOptions = [
    { value: 'yes', display: 'Yes' },
    { value: 'no', display: 'No' }
];

const chiefComplaintOptions = [
    { value: 'cardiac', display: 'Chest pain' },
    { value: 'stroke', display: 'Stroke symptoms' },
    { value: 'respiratory', display: 'Shortness of breath' },
    { value: 'syncope', display: 'Syncope' },
    { value: 'abdominal', display: 'Abdominal pain' },
    { value: 'neuro', display: 'Severe headache' },
    { value: 'minor_injury', display: 'Minor injury' },
    { value: 'minor_general', display: 'Minor complaint' },
    { value: 'general', display: 'Other / general' }
];

const symptomOptions = [
    { value: 'chest_pain', display: 'Chest pain' },
    { value: 'shortness_of_breath', display: 'Shortness of Breath' },
    { value: 'fever', display: 'Fever' },
    { value: 'cough', display: 'Cough' },
    { value: 'dizziness', display: 'Dizziness' },
    { value: 'headache', display: 'Headache' },
    { value: 'nausea_vomiting', display: 'Nausea / Vomiting' },
    { value: 'fatigue', display: 'Fatigue' },
    { value: 'palpitations', display: 'Palpitations' },
    { value: 'abdominal_pain', display: 'Abdominal Pain' },
    { value: 'weakness', display: 'Weakness' },
    { value: 'vague_malaise', display: 'Vague malaise / feeling unwell' },
    { value: 'altered_behaviour', display: 'Altered behaviour / confusion' },
    { value: 'heavy_bleeding', display: 'Heavy bleeding' },
    { value: 'fast_positive', display: 'FAST-positive (stroke screen)' }
];

// Bounds mirror the Field() constraints on IntakeCreate. Integer fields declared
// gt=0 become min={1}, since the HTML min attribute is inclusive.
const vitalsRowOne = [
    { name: 'heart_rate', label: 'Heart Rate (bpm)', min: 1, max: 350, step: 1 },
    { name: 'temperature', label: 'Temperature (°F)', min: 68, max: 115, step: 0.1 },
    { name: 'blood_pressure_systolic', label: 'BP Systolic (mmHg)', min: 1, max: 300, step: 1 },
    { name: 'blood_pressure_diastolic', label: 'BP Diastolic (mmHg)', min: 1, max: 250, step: 1 }
];

const vitalsRowTwo = [
    { name: 'oxygen_saturation', label: 'Oxygen Saturation (%)', min: 0, max: 100, step: 1 },
    { name: 'respiration_rate', label: 'Respiratory Rate (/min)', min: 1, max: 99, step: 1 },
    { name: 'pain_level', label: 'Pain Level (0-10)', min: 0, max: 10, step: 1 },
    { name: 'blood_sugar', label: 'Blood Sugar (mg/dL)', min: 0.1, max: 1600, step: 0.1 }
];

// The only vitals that feed the scoring rules. Temperature and blood sugar are
// recorded but not scored.
const SCORED_VITALS = [
    { name: 'heart_rate', short: 'HR' },
    { name: 'oxygen_saturation', short: 'SpO2' },
    { name: 'respiration_rate', short: 'Respiratory rate' },
    { name: 'blood_pressure_systolic', short: 'BP systolic' },
    { name: 'pain_level', short: 'Pain level' }
];

// Vitals leave the inputs as strings. Blank means "not recorded", which the API
// wants as null — an empty string fails its int/float validation outright.
// These are also the fields the API types as int, so a decimal is rejected.
const INT_VITALS = [
    'heart_rate',
    'blood_pressure_systolic',
    'blood_pressure_diastolic',
    'oxygen_saturation',
    'respiration_rate',
    'pain_level'
];

const FLOAT_VITALS = ['temperature', 'blood_sugar'];

// Always required. Pregnancy and notes join this list only while their section
// is on screen, so the rail counts what the clinician can actually see.
const BASE_REQUIRED = [
    { name: 'name', label: 'Patient name' },
    { name: 'date_of_birth', label: 'Date of birth' },
    { name: 'sex', label: 'Sex / gender' },
    { name: 'chief_complaint', label: 'Chief complaint' }
];

const initialFormData = {
    name: '',
    date_of_birth: '',
    sex: '',
    chief_complaint: '',
    symptoms: [],
    heart_rate: '',
    blood_pressure_systolic: '',
    blood_pressure_diastolic: '',
    temperature: '',
    oxygen_saturation: '',
    respiration_rate: '',
    pain_level: '',
    blood_sugar: '',
    pregnancy_status: 'none',
    pre_existing_conditions: [],
    arrival_by_ambulance: 'no',
    recent_ed_visit_72h: 'no',
    injury_related: 'no',
    notes: ''
};


/** Local YYYY-MM-DD, avoiding the UTC shift that toISOString() introduces. */
function toISODate(date) {
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');

    return `${date.getFullYear()}-${month}-${day}`;
}


/**
 * Mirrors the blocking rules in IntakeCreate so the clinician sees them before
 * a round trip, not as a 422 afterwards.
 */
function validate(data, maxDateOfBirth) {
    const errors = {};

    if (!data.name.trim()) {
        errors.name = 'Patient name is required.';
    }

    if (!data.date_of_birth) {
        errors.date_of_birth = 'Date of birth is required.';
    } else if (data.date_of_birth > maxDateOfBirth) {
        errors.date_of_birth = 'Date of birth cannot be in the future.';
    }

    if (!data.sex) {
        errors.sex = 'Sex / gender is required.';
    }

    if (!data.chief_complaint) {
        errors.chief_complaint = 'A chief complaint is required.';
    }

    if (data.sex === 'F' && !data.pregnancy_status) {
        errors.pregnancy_status = 'Select a pregnancy status.';
    }

    if (data.chief_complaint === 'general' && !data.notes.trim()) {
        errors.notes = 'Describe the complaint when selecting "Other / general".';
    }

    // step="1" only nudges — a decimal can still be typed or pasted into these.
    // Caught here because buildPayload would otherwise parseInt it and submit a
    // silently truncated reading.
    for (const field of INT_VITALS) {
        const raw = data[field].trim();

        if (raw !== '' && !Number.isInteger(Number(raw))) {
            errors[field] = 'Must be a whole number.';
        }
    }

    // Mirrors the check_dia_lower_than_sys validator.
    if (data.blood_pressure_systolic !== '' && data.blood_pressure_diastolic !== '') {
        if (Number(data.blood_pressure_diastolic) >= Number(data.blood_pressure_systolic)) {
            errors.blood_pressure_diastolic = 'Diastolic must be lower than systolic.';
        }
    }

    return errors;
}


const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;

// The API's wording for these is accurate but leaves the clinician without a
// next step, so they are reworded here.
const CODE_MESSAGES = {
    duplicate_request:
        'This intake was already recorded. Reload the page to start a new one.',
    unscoreable:
        'This intake is valid, but it needs more vitals before it can be scored.'
};


// Number() rather than parseInt/parseFloat: those stop at the first character
// they can't read, so "12e2" would become 12 and "5abc" would become 5. This
// also keeps parsing consistent with the integer check in validate().
function toNumberOrNull(value) {
    const trimmed = value.trim();

    if (trimmed === '') {
        return null;
    }

    const parsed = Number(trimmed);

    return Number.isNaN(parsed) ? null : parsed;
}


function buildPayload(formData) {
    const payload = {
        ...formData,
        // Back to real booleans for the API.
        arrival_by_ambulance: formData.arrival_by_ambulance === 'yes',
        recent_ed_visit_72h: formData.recent_ed_visit_72h === 'yes',
        injury_related: formData.injury_related === 'yes',
        notes: formData.notes.trim() || null,
        source: 'form'
    };

    [...INT_VITALS, ...FLOAT_VITALS].forEach((field) => {
        payload[field] = toNumberOrNull(formData[field]);
    });

    return payload;
}


/** randomUUID needs a secure context, which includes localhost. */
function createIdempotencyKey() {
    if (globalThis.crypto?.randomUUID) {
        return globalThis.crypto.randomUUID();
    }

    return `intake-${Date.now()}-${Math.random().toString(16).slice(2, 10)}`;
}


function capitalise(text) {
    return text.charAt(0).toUpperCase() + text.slice(1);
}


/**
 * Flattens the API's response envelopes into one shape. Successes are wrapped
 * as { payload, meta }, handled errors as { error }, and the non-500
 * HTTPException branch as { detail }.
 */
function interpretError(status, data) {
    const apiError = data?.error;

    if (!apiError) {
        const detail = typeof data?.detail === 'string' ? data.detail : null;

        return {
            message: detail || `Submission failed (HTTP ${status}).`,
            fieldErrors: {}
        };
    }

    // Validation details name the model field, and those match the form state
    // keys, so most land straight on the input that caused them.
    const fieldErrors = {};
    const unmapped = [];

    for (const detail of apiError.details ?? []) {
        if (detail.field in initialFormData) {
            fieldErrors[detail.field] = capitalise(detail.issue);
        } else {
            unmapped.push(`${detail.field} — ${detail.issue}`);
        }
    }

    const fieldCount = Object.keys(fieldErrors).length;
    let message = CODE_MESSAGES[apiError.code] ?? apiError.message;

    if (fieldCount > 0) {
        message = `${fieldCount} field${fieldCount === 1 ? '' : 's'} need${
            fieldCount === 1 ? 's' : ''
        } attention.`;
    } else if (unmapped.length > 0) {
        message = `${message} (${unmapped.join('; ')})`;
    }

    return { message, fieldErrors, requestId: apiError.request_id };
}


function PatientIntake() {
    const [formData, setFormData] = useState(initialFormData);
    const [errors, setErrors] = useState({});
    const [submitting, setSubmitting] = useState(false);

    // Result of the last submit: { status: 'success' | 'error', ... }. Held
    // until the next edit, which hands the rail back to live completeness.
    const [submitState, setSubmitState] = useState(null);

    // Stamped when the intake is opened, not a running clock. Re-stamped after
    // a successful submit, since the cleared form is a new record.
    const [intakeTime, setIntakeTime] = useState(() => new Date());

    // One key per submission attempt. Reused across retries so a resend of the
    // same intake replays rather than duplicating; replaced only after a 201.
    const idempotencyKey = useRef(null);

    if (idempotencyKey.current === null) {
        idempotencyKey.current = createIdempotencyKey();
    }

    const maxDateOfBirth = toISODate(intakeTime);

    // Clearing as soon as a field is corrected keeps stale red text off screen.
    const clearError = (name) => {
        setErrors((prev) => {
            if (!(name in prev)) {
                return prev;
            }

            const next = { ...prev };
            delete next[name];

            return next;
        });
    };

    const updateField = (name, value) => {
        setFormData((prev) => ({ ...prev, [name]: value }));
        clearError(name);
        setSubmitState(null);
    };

    // Pregnancy only applies to female patients. Selecting Female clears the
    // answer so it has to be chosen deliberately; anything else files it as None.
    const handleSexChange = (name, value) => {
        setFormData((prev) => ({
            ...prev,
            sex: value,
            pregnancy_status: value === 'F' ? '' : 'none'
        }));

        clearError('sex');
        clearError('pregnancy_status');
        setSubmitState(null);
    };

    // Notes belong to the complaint that prompted them, so changing the
    // complaint drops them rather than carrying them over.
    const handleComplaintChange = (name, value) => {
        setFormData((prev) => ({ ...prev, chief_complaint: value, notes: '' }));

        clearError('chief_complaint');
        clearError('notes');
        setSubmitState(null);
    };

    const showPregnancy = formData.sex === 'F';
    const showNotes = formData.chief_complaint === 'general';

    const missingVitals = SCORED_VITALS.filter(
        (vital) => formData[vital.name].trim() === ''
    );
    const scoredVitalsEntered = SCORED_VITALS.length - missingVitals.length;

    const requiredFields = [
        ...BASE_REQUIRED,
        ...(showPregnancy
            ? [{ name: 'pregnancy_status', label: 'Pregnancy status' }]
            : []),
        ...(showNotes ? [{ name: 'notes', label: 'Notes' }] : [])
    ];
    const missingRequired = requiredFields.filter(
        (field) => formData[field.name].trim() === ''
    );

    const intakeTimeLabel = intakeTime.toLocaleString('en-US', {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
        hour12: true
    });

    // Runs after the commit that marks inputs invalid, so there is something
    // to focus.
    const focusFirstInvalid = () => {
        requestAnimationFrame(() => {
            document.querySelector('[aria-invalid="true"]')?.focus();
        });
    };

    const handleSubmit = async (event) => {
        event.preventDefault();

        if (submitting) {
            return;
        }

        const nextErrors = validate(formData, maxDateOfBirth);
        setErrors(nextErrors);

        if (Object.keys(nextErrors).length > 0) {
            focusFirstInvalid();
            return;
        }

        setSubmitting(true);
        setSubmitState(null);

        try {
            const response = await fetch(`${API_BASE_URL}/patients/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Idempotency-Key': idempotencyKey.current
                },
                body: JSON.stringify(buildPayload(formData))
            });

            // An error page or a dropped connection mid-body leaves nothing to
            // parse, so the status still has to carry the outcome.
            const data = await response.json().catch(() => null);

            if (!response.ok) {
                const { message, fieldErrors, requestId } = interpretError(
                    response.status,
                    data
                );

                setErrors(fieldErrors);
                setSubmitState({ status: 'error', message, requestId });

                if (Object.keys(fieldErrors).length > 0) {
                    focusFirstInvalid();
                }

                return;
            }

            setSubmitState({ status: 'success', result: data?.payload ?? {} });

            // A recorded intake is finished, so the form resets for the next
            // patient with a fresh key and timestamp.
            setFormData(initialFormData);
            setErrors({});
            setIntakeTime(new Date());
            idempotencyKey.current = createIdempotencyKey();
        } catch (error) {
            console.error('Intake submission failed:', error);

            setSubmitState({
                status: 'error',
                message: 'Could not reach the server. Check the connection and try again.'
            });
        } finally {
            setSubmitting(false);
        }
    };

    const renderVital = (vital) => (
        <TextBox
            key={vital.name}
            boxLabel={vital.label}
            name={vital.name}
            value={formData[vital.name]}
            onChange={updateField}
            error={errors[vital.name]}
            type='number'
            min={vital.min}
            max={vital.max}
            step={vital.step}
            placeholder='Enter value'
        />
    );

    return (
        <div className='content'>
            <form className='formcol' onSubmit={handleSubmit} noValidate>
                <div className='intake-header'>
                    <h1 className='h1'>Patient Intake</h1>
                    <p className='sub'>
                        Enter patient information to calculate severity score and add to
                        triage queue.
                    </p>
                </div>

                <div className='autobar'>
                    <div>
                        <div className='lab'>Intake Time (Auto)</div>
                        <div className='val'>{intakeTimeLabel}</div>
                    </div>
                </div>

                <section className='sec'>
                    <h3>1. Patient Identity</h3>

                    <TextBox
                        boxLabel='Patient Name'
                        name='name'
                        value={formData.name}
                        onChange={updateField}
                        error={errors.name}
                        placeholder='Full name'
                        maxLength={100}
                        required
                        icon={User}
                    />

                    <div className='grid2'>
                        <Dropdown
                            dropdownLabel='Sex / Gender'
                            name='sex'
                            value={formData.sex}
                            onChange={handleSexChange}
                            error={errors.sex}
                            options={sexOptions}
                            placeholder='Select sex / gender'
                            required
                            icon={User}
                        />

                        <TextBox
                            boxLabel='Date of Birth'
                            name='date_of_birth'
                            value={formData.date_of_birth}
                            onChange={updateField}
                            error={errors.date_of_birth}
                            type='date'
                            max={maxDateOfBirth}
                            hint='Age derived from DOB; used by the age scoring rule.'
                            required
                            icon={Calendar}
                        />
                    </div>
                </section>

                {showPregnancy && (
                    <section className='sec'>
                        <h3>
                            2. Pregnancy Status{' '}
                            <span className='hint'>(Shown because sex = Female)</span>
                            <span className='req'> *</span>
                        </h3>

                        <RadioGroup
                            name='pregnancy_status'
                            value={formData.pregnancy_status}
                            onChange={updateField}
                            error={errors.pregnancy_status}
                            options={pregnancyOptions}
                        />

                        <div className='infoline'>
                            <Info size={14} />
                            Pregnancy status helps tailor triage rules (maternal red-flag
                            triggers).
                        </div>
                    </section>
                )}

                <section className='sec'>
                    <h3>
                        3. Pre-existing Conditions{' '}
                        <span className='hint'>(Select all that apply)</span>
                    </h3>

                    <CheckGroup
                        name='pre_existing_conditions'
                        values={formData.pre_existing_conditions}
                        onChange={updateField}
                        options={preExistingConditionsOptions}
                    />

                    <div className='infoline'>
                        <Info size={14} />
                        Provides clinical context. Some (immunocompromised, sickle cell)
                        feed red-flag triggers — flags never change the ESI score.
                    </div>
                </section>

                <section className='sec'>
                    <div className='triple'>
                        <div className='cell'>
                            <div className='t'>4. Arrival by Ambulance</div>
                            <RadioGroup
                                name='arrival_by_ambulance'
                                value={formData.arrival_by_ambulance}
                                onChange={updateField}
                                options={yesNoOptions}
                            />
                        </div>

                        <div className='cell'>
                            <div className='t'>5. Seen in ED within 72 hrs</div>
                            <RadioGroup
                                name='recent_ed_visit_72h'
                                value={formData.recent_ed_visit_72h}
                                onChange={updateField}
                                options={yesNoOptions}
                            />
                        </div>

                        <div className='cell'>
                            <div className='t'>6. Injury / Trauma related</div>
                            <RadioGroup
                                name='injury_related'
                                value={formData.injury_related}
                                onChange={updateField}
                                options={yesNoOptions}
                            />
                        </div>
                    </div>
                </section>

                <section className='sec'>
                    <h3>
                        7. Primary / Chief Complaint{' '}
                        <span className='hint'>(Required)</span>
                        <span className='req'> *</span>
                    </h3>

                    <Dropdown
                        name='chief_complaint'
                        value={formData.chief_complaint}
                        onChange={handleComplaintChange}
                        error={errors.chief_complaint}
                        options={chiefComplaintOptions}
                        placeholder='Select the main reason for the visit'
                    />

                    <div className='infoline'>
                        <Info size={14} />
                        Select the main reason for the visit. This drives scoring (maps to
                        a complaint group).
                    </div>

                    {showNotes && (
                        <TextArea
                            areaLabel='Notes'
                            name='notes'
                            value={formData.notes}
                            onChange={updateField}
                            error={errors.notes}
                            placeholder='Describe the presenting complaint'
                            required
                        />
                    )}
                </section>

                <section className='sec'>
                    <h3>
                        8. Additional Symptoms{' '}
                        <span className='hint'>(Select all that apply)</span>
                    </h3>

                    <CheckGroup
                        name='symptoms'
                        values={formData.symptoms}
                        onChange={updateField}
                        options={symptomOptions}
                    />

                    <div className='infoline'>
                        <Info size={14} />
                        Additional symptoms provide supporting clinical context and may
                        influence severity.
                    </div>
                </section>

                <section className='sec'>
                    <h3>
                        9. Vitals <span className='hint'>(Recommended)</span>
                    </h3>

                    <div className='grid4'>{vitalsRowOne.map(renderVital)}</div>
                    <div className='grid4'>{vitalsRowTwo.map(renderVital)}</div>

                    <div className='vitals-note'>
                        <ClipboardCheck size={15} />
                        Scored vitals: HR, SpO2, Resp Rate, BP-sys, Pain. Temperature and
                        blood sugar are recorded, not scored.
                        <span className='cnt'>
                            {scoredVitalsEntered} / {SCORED_VITALS.length} scored vitals
                            entered
                        </span>
                    </div>
                </section>

                <div className='submit'>
                    <button type='submit' disabled={submitting}>
                        <UserPlus size={17} />
                        {submitting ? 'Submitting…' : 'Submit Patient for Triage'}
                    </button>
                </div>
            </form>

            <IntakeRail
                requiredDone={requiredFields.length - missingRequired.length}
                requiredTotal={requiredFields.length}
                missingRequired={missingRequired.map((field) => field.label)}
                scoredVitalsDone={scoredVitalsEntered}
                scoredVitalsTotal={SCORED_VITALS.length}
                missingVitals={missingVitals.map((vital) => vital.short)}
                submitState={submitState}
            />
        </div>
    );
}

export default PatientIntake;
