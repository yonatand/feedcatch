import { useState } from 'react';

type Props = {
  label: string;
  confirmLabel?: string;
  message?: React.ReactNode;
  onConfirm: () => void;
  danger?: boolean;
  disabled?: boolean;
  pending?: boolean;
  size?: 'sm' | 'md';
  /** Accessible name of the first button when `label` alone is ambiguous (e.g. one "Delete" per table row). */
  ariaLabel?: string;
  /** Let a long message wrap even inside tables (where confirm groups otherwise stay on one line). */
  wrap?: boolean;
};

/** Two-step inline confirmation; replaces window.confirm for destructive actions. */
export function ConfirmInline({
  label,
  confirmLabel = 'Confirm',
  message,
  onConfirm,
  danger = true,
  disabled,
  pending,
  size = 'sm',
  ariaLabel,
  wrap = false,
}: Props) {
  const [armed, setArmed] = useState(false);
  const sz = size === 'sm' ? ' btn-sm' : '';
  if (!armed) {
    return (
      <button
        type="button"
        className={`btn${sz}${danger ? ' btn-danger-outline' : ''}`}
        disabled={disabled || pending}
        aria-label={ariaLabel}
        onClick={() => setArmed(true)}
      >
        {pending ? '…' : label}
      </button>
    );
  }
  return (
    <span className={`confirm-inline${wrap ? ' confirm-wrap' : ''}`} role="group" aria-label={`Confirm ${ariaLabel ?? label}`}>
      {message ? <span className="confirm-msg">{message}</span> : null}
      <button
        type="button"
        className={`btn${sz} ${danger ? 'btn-danger' : 'btn-primary'}`}
        disabled={pending}
        onClick={() => {
          setArmed(false);
          onConfirm();
        }}
        autoFocus
      >
        {confirmLabel}
      </button>
      <button type="button" className={`btn${sz} btn-ghost`} onClick={() => setArmed(false)}>
        Cancel
      </button>
    </span>
  );
}
