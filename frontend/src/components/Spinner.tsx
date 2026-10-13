export function Spinner({ label = 'Loading…', inline = false }: { label?: string; inline?: boolean }) {
  return (
    <span className={inline ? 'spinner-wrap inline' : 'spinner-wrap'} role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      <span className={inline ? 'sr-only' : 'muted'}>{label}</span>
    </span>
  );
}

export function LoadingBlock({ label }: { label?: string }) {
  return (
    <div className="loading-block">
      <Spinner label={label} />
    </div>
  );
}
