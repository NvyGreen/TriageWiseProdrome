import { useId } from 'react';


/**
 * @typedef {object} RadioOption
 * @property {string} value - The actual form value
 * @property {string} display - The text shown to the user
 */


/**
 * A controlled radio group. The parent owns the value.
 *
 * Values must be strings: the DOM stores input values as strings, so a boolean
 * option value can never match what comes back out of the event.
 *
 * @param {object} props
 * @param {string} [props.radioLabel] - the label for the radio group
 * @param {string} props.name - the field key, also the radio group name
 * @param {string} props.value - the currently selected value
 * @param {(name: string, value: string) => void} props.onChange - change handler
 * @param {RadioOption[]} props.options - the radio options
 * @param {string} [props.error] - validation message; also flags the group invalid
 */
export default function RadioGroup({ radioLabel, name, value, onChange, options, error }) {
    // Scopes input ids to this instance, so repeated Yes/No groups on the same
    // page don't collide and steal each other's label clicks.
    const uid = useId();
    const errorId = `${uid}-error`;

    const handleChange = (event) => {
        onChange(name, event.target.value);
    };

    return (
        <div className='field'>
            {radioLabel && <label className='lbl'>{radioLabel}</label>}

            <div className='radios' role='radiogroup' aria-describedby={error ? errorId : undefined}>
                {options.map((currOption) => {
                    const inputId = `${uid}-${currOption.value}`;

                    return (
                        <label className='radio' htmlFor={inputId} key={currOption.value}>
                            <input
                                type='radio'
                                id={inputId}
                                name={`${uid}-${name}`}
                                value={currOption.value}
                                checked={value === currOption.value}
                                onChange={handleChange}
                                aria-invalid={error ? true : undefined}
                            />
                            <span>{currOption.display}</span>
                        </label>
                    );
                })}
            </div>

            {error && (
                <div className='field-error' id={errorId}>
                    {error}
                </div>
            )}
        </div>
    );
}
