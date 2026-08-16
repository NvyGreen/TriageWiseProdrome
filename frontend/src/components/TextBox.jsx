import { useId } from 'react';


/**
 * A controlled single-line input. The parent owns the value.
 *
 * @param {object} props
 * @param {string} props.boxLabel - the label for the text box
 * @param {string} props.name - the field key reported back through onChange
 * @param {string} props.value - the current value
 * @param {(name: string, value: string) => void} props.onChange - change handler
 * @param {string} [props.type] - input type, e.g. 'text' | 'number' | 'date'
 * @param {string} [props.placeholder] - the placeholder inside the text box
 * @param {boolean} [props.required] - marks the field with a red asterisk
 * @param {string} [props.hint] - small helper text under the field
 * @param {string} [props.error] - validation message; also flags the input invalid
 * @param {string} [props.ariaLabel] - accessible name when there is no visible label
 * @param {React.ElementType} [props.icon] - leading icon component
 * @param {number} [props.min] - numeric/date lower bound
 * @param {number} [props.max] - numeric/date upper bound
 * @param {number|string} [props.step] - numeric step
 * @param {number} [props.maxLength] - character limit
 */
export default function TextBox({
    boxLabel,
    name,
    value,
    onChange,
    type = 'text',
    placeholder,
    required = false,
    hint,
    error,
    ariaLabel,
    icon: Icon,
    min,
    max,
    step,
    maxLength
}) {
    const id = useId();
    const errorId = `${id}-error`;
    const hintId = `${id}-hint`;

    const handleChange = (event) => {
        onChange(name, event.target.value);
    };

    const input = (
        <input
            type={type}
            id={id}
            name={name}
            value={value}
            onChange={handleChange}
            placeholder={placeholder}
            min={min}
            max={max}
            step={step}
            maxLength={maxLength}
            // A visible label should win, so that what a voice-control user
            // says matches what they can see.
            aria-label={boxLabel ? undefined : ariaLabel}
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? errorId : hint ? hintId : undefined}
        />
    );

    return (
        <div className='field'>
            {boxLabel && (
                <label className='lbl' htmlFor={id}>
                    {boxLabel}
                    {required && <span className='req'> *</span>}
                </label>
            )}

            {Icon ? (
                <div className='withicon'>
                    <Icon className='field-icon' size={15} />
                    {input}
                </div>
            ) : (
                input
            )}

            {hint && !error && (
                <div className='field-hint' id={hintId}>
                    {hint}
                </div>
            )}

            {error && (
                <div className='field-error' id={errorId}>
                    {error}
                </div>
            )}
        </div>
    );
}
