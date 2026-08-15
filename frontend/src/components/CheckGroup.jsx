import { useId } from 'react';


/**
 * @typedef {object} CheckOption
 * @property {string} value - The actual form value
 * @property {string} display - The text shown to the user
 */


/**
 * A controlled checkbox group. The parent owns the selected array.
 *
 * @param {object} props
 * @param {string} [props.checkLabel] - the label for the checkboxes
 * @param {string} props.name - the field key reported back through onChange
 * @param {string[]} props.values - the currently selected values
 * @param {(name: string, values: string[]) => void} props.onChange - change handler
 * @param {CheckOption[]} props.options - the checkbox options
 */
export default function CheckGroup({ checkLabel, name, values, onChange, options }) {
    const uid = useId();

    const handleCheckboxChange = (value) => {
        const next = values.includes(value)
            ? values.filter((item) => item !== value)
            : [...values, value];

        onChange(name, next);
    };

    return (
        <div className='field'>
            {checkLabel && <label className='lbl'>{checkLabel}</label>}

            <div className='checks'>
                {options.map((currOption) => {
                    const inputId = `${uid}-${currOption.value}`;
                    // Long labels get two columns so the grid doesn't go ragged.
                    const wide = currOption.display.length > 28;

                    return (
                        <label
                            className={wide ? 'chk chk-wide' : 'chk'}
                            htmlFor={inputId}
                            key={currOption.value}
                        >
                            <input
                                type='checkbox'
                                id={inputId}
                                name={name}
                                value={currOption.value}
                                checked={values.includes(currOption.value)}
                                onChange={() => handleCheckboxChange(currOption.value)}
                            />
                            <span>{currOption.display}</span>
                        </label>
                    );
                })}
            </div>
        </div>
    );
}
