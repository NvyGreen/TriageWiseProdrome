import { useId } from 'react';


/**
 * A controlled multi-line input. The parent owns the value.
 *
 * @param {object} props
 * @param {string} props.areaLabel - the label for the text area
 * @param {string} props.name - the field key reported back through onChange
 * @param {string} props.value - the current value
 * @param {(name: string, value: string) => void} props.onChange - change handler
 * @param {string} [props.placeholder] - the placeholder inside the text area
 * @param {boolean} [props.required] - marks the field with a red asterisk
 * @param {number} [props.rows] - visible line count
 * @param {string} [props.error] - validation message; also flags the input invalid
 */
export default function TextArea({
    areaLabel,
    name,
    value,
    onChange,
    placeholder,
    required = false,
    rows = 3,
    error
}) {
    const id = useId();
    const errorId = `${id}-error`;

    const handleChange = (event) => {
        onChange(name, event.target.value);
    };

    return (
        <div className='field'>
            <label className='lbl' htmlFor={id}>
                {areaLabel}
                {required && <span className='req'> *</span>}
            </label>

            <textarea
                id={id}
                name={name}
                value={value}
                onChange={handleChange}
                placeholder={placeholder}
                rows={rows}
                aria-invalid={error ? true : undefined}
                aria-describedby={error ? errorId : undefined}
            />

            {error && (
                <div className='field-error' id={errorId}>
                    {error}
                </div>
            )}
        </div>
    );
}
