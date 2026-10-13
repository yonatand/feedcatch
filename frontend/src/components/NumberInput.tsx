import { useEffect, useRef, useState } from 'react';

type Props = {
  id?: string;
  value: number | null;
  onChange: (v: number | null) => void;
  integer?: boolean;
  min?: number;
  max?: number;
  step?: number | 'any';
  placeholder?: string;
  disabled?: boolean;
  required?: boolean;
  className?: string;
};

/** Number input that keeps raw text while typing ("-", "1.") and emits number | null. */
export function NumberInput({ id, value, onChange, integer = true, min, max, step, placeholder, disabled, required, className }: Props) {
  const [text, setText] = useState(value === null ? '' : String(value));
  const last = useRef<number | null>(value);

  useEffect(() => {
    if (value !== last.current) {
      last.current = value;
      setText(value === null ? '' : String(value));
    }
  }, [value]);

  return (
    <input
      id={id}
      type="number"
      inputMode={integer ? 'numeric' : 'decimal'}
      className={className}
      value={text}
      min={min}
      max={max}
      step={step ?? (integer ? 1 : 'any')}
      placeholder={placeholder}
      disabled={disabled}
      required={required}
      onChange={(e) => {
        const raw = e.target.value;
        setText(raw);
        const t = raw.trim();
        let next: number | null = null;
        if (t !== '') {
          const n = Number(t);
          next = Number.isFinite(n) ? (integer ? Math.trunc(n) : n) : null;
        }
        last.current = next;
        onChange(next);
      }}
    />
  );
}
