import { useEffect, useRef, useState } from 'react';
import { joinList, splitList } from '../lib/format';

type Props = {
  id?: string;
  value: string[];
  onChange: (v: string[]) => void;
  placeholder?: string;
  disabled?: boolean;
};

function sameList(a: readonly string[], b: readonly string[]): boolean {
  return a.length === b.length && a.every((x, i) => x === b[i]);
}

/** Comma-separated text input that maps to string[]. Keeps raw text while typing. */
export function ListInput({ id, value, onChange, placeholder, disabled }: Props) {
  const [text, setText] = useState(() => joinList(value));
  const last = useRef<string[]>(value);

  useEffect(() => {
    // Only resync when the value changed from outside (not from our own typing).
    if (!sameList(value, last.current)) {
      last.current = value;
      setText(joinList(value));
    }
  }, [value]);

  return (
    <input
      id={id}
      type="text"
      value={text}
      placeholder={placeholder}
      disabled={disabled}
      autoComplete="off"
      onChange={(e) => {
        setText(e.target.value);
        const next = splitList(e.target.value);
        last.current = next;
        onChange(next);
      }}
      onBlur={() => setText(joinList(last.current))}
    />
  );
}
