import { useId } from 'react';


/**
 * @typedef {object} DropdownOption
 * @property {string} value - The actual form value
 * @property {string} display - The text shown to the user
 */


/**
 * A controlled select. The parent owns the value.
 *
 * @param {object} props
 * @param {string} [props.dropdownLabel] - the label for the dropdown
 * @param {string} props.name - the field key reported back through onChange
 * @param {string} props.value - the currently selected value
 * @param {(name: string, value: string) => void} props.onChange - change handler
 * @param {DropdownOption[]} props.options - the dropdown's options
 * @param {string} [props.placeholder] - text for the empty leading option
 * @param {boolean} [props.required] - marks the field with a red asterisk
 * @param {string} [props.hint] - small helper text under the field
 * @param {string} [props.error] - validation message; also flags the input invalid
 * @param {string} [props.ariaLabel] - accessible name when there is no visible label
 * @param {boolean} [props.disabled] - blocks selection
 * @param {React.ElementType} [props.icon] - leading icon component
 */
export default function Dropdown({
    dropdownLabel,
    name,
    value,
    onChange,
    options,
    placeholder,
    required = false,
    hint,
    error,
    ariaLabel,
    disabled = false,
    icon: Icon
}) {
    const id = useId();
    const errorId = `${id}-error`;

    const handleChange = (event) => {
        onChange(name, event.target.value);
    };

    const select = (
        <select
            id={id}
            name={name}
            value={value}
            onChange={handleChange}
            disabled={disabled}
            // A visible label should win, so that what a voice-control user
            // says matches what they can see.
            aria-label={dropdownLabel ? undefined : ariaLabel}
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? errorId : undefined}
        >
            {placeholder && (
                <option value='' disabled>
                    {placeholder}
                </option>
            )}

            {options.map((currOption) => (
                <option key={currOption.value} value={currOption.value}>
                    {currOption.display}
                </option>
            ))}
        </select>
    );

    return (
        <div className='field'>
            {dropdownLabel && (
                <label className='lbl' htmlFor={id}>
                    {dropdownLabel}
                    {required && <span className='req'> *</span>}
                </label>
            )}

            {Icon ? (
                <div className='withicon'>
                    <Icon className='field-icon' size={15} />
                    {select}
                </div>
            ) : (
                select
            )}

            {hint && !error && <div className='field-hint'>{hint}</div>}

            {error && (
                <div className='field-error' id={errorId}>
                    {error}
                </div>
            )}
        </div>
    );
}
