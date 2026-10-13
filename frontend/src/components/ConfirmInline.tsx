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
}: Props) {
  const [armed, setArmed] = useState(false);
  const sz = size === 'sm' ? ' btn-sm' : '';
  if (!armed) {
    return (
      <button
        type="button"
        className={`btn${sz}${danger ? ' btn-danger-outline' : ''}`}
        disabled={disabled || pending}
        onClick={() => setArmed(true)}
      >
        {pending ? '…' : label}
      </button>
    );
  }
  return (
    <span className="confirm-inline" role="group" aria-label={`Confirm ${label}`}>
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
