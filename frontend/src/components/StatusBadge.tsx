type Tone = 'grey' | 'green' | 'red' | 'blue' | 'orange' | 'purple' | 'yellow';

const TONES: Record<string, Tone> = {
  // downloads
  pending: 'grey',
  submitted: 'green',
  failed: 'red',
  exists: 'blue',
  path_mismatch: 'orange',
  // entry outcomes
  accepted: 'green',
  rejected: 'grey',
  no_match: 'grey',
  duplicate: 'blue',
  historical: 'purple',
  unprocessed: 'yellow',
  // feed status
  ok: 'green',
  error: 'red',
  never: 'grey',
  // activity levels
  info: 'blue',
  warning: 'orange',
  // generic
  enabled: 'green',
  disabled: 'grey',
  monitored: 'green',
  unmonitored: 'grey',
  matched: 'green',
  env: 'purple',
};

const LABELS: Record<string, string> = {
  path_mismatch: 'path mismatch',
  no_match: 'no match',
};

export function StatusBadge({ status, tone, title }: { status: string; tone?: Tone; title?: string }) {
  const t = tone ?? TONES[status] ?? 'grey';
  return (
    <span className={`badge badge-${t}`} title={title}>
      {LABELS[status] ?? status}
    </span>
  );
}

export function Badge({ children, tone = 'grey', title }: { children: React.ReactNode; tone?: Tone; title?: string }) {
  return (
    <span className={`badge badge-${tone}`} title={title}>
      {children}
    </span>
  );
}

export function BoolMark({ value }: { value: boolean | null | undefined }) {
  if (value === null || value === undefined) return <span className="muted">—</span>;
  return value ? (
    <span className="pass" aria-label="yes">
      ✓
    </span>
  ) : (
    <span className="fail" aria-label="no">
      ✗
    </span>
  );
}
