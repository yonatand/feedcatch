import { useId } from 'react';

type Props = {
  label: React.ReactNode;
  help?: React.ReactNode;
  error?: string | null;
  badge?: React.ReactNode;
  className?: string;
  children: (id: string) => React.ReactNode;
};

/** Label + control + help/error. Children is a render prop receiving the generated input id. */
export function FormField({ label, help, error, badge, className, children }: Props) {
  const id = useId();
  return (
    <div className={`field${className ? ` ${className}` : ''}`}>
      <label htmlFor={id} className="field-label">
        {label}
        {badge ? <span className="field-badge">{badge}</span> : null}
      </label>
      {children(id)}
      {error ? (
        <div className="field-error" role="alert">
          {error}
        </div>
      ) : help ? (
        <div className="field-help">{help}</div>
      ) : null}
    </div>
  );
}

type CheckProps = {
  label: React.ReactNode;
  checked: boolean;
  onChange: (v: boolean) => void;
  help?: React.ReactNode;
  disabled?: boolean;
  badge?: React.ReactNode;
};

export function CheckField({ label, checked, onChange, help, disabled, badge }: CheckProps) {
  const id = useId();
  return (
    <div className="field field-check">
      <div className="check-row">
        <input
          id={id}
          type="checkbox"
          checked={checked}
          disabled={disabled}
          onChange={(e) => onChange(e.target.checked)}
        />
        <label htmlFor={id}>{label}</label>
        {badge ? <span className="field-badge">{badge}</span> : null}
      </div>
      {help ? <div className="field-help">{help}</div> : null}
    </div>
  );
}
