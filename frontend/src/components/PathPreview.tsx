import { CopyButton } from './CopyButton';

type Props = {
  path: string | null | undefined;
  label?: string;
  loading?: boolean;
  error?: string | null;
  note?: boolean;
};

/** Shows a qBittorrent save path string. The app never creates or touches this path. */
export function PathPreview({ path, label = 'qBittorrent save path', loading, error, note = false }: Props) {
  return (
    <div className="path-preview">
      <div className="path-label">{label}</div>
      {error ? (
        <div className="field-error">{error}</div>
      ) : loading ? (
        <code className="path muted">computing…</code>
      ) : path ? (
        <div className="path-row">
          <code className="path">{path}</code>
          <CopyButton text={path} />
        </div>
      ) : (
        <code className="path muted">—</code>
      )}
      {note ? (
        <div className="field-help">
          Path as seen by qBittorrent. It is only sent to qBittorrent as <code>savepath</code>; this app never creates or
          touches it.
        </div>
      ) : null}
    </div>
  );
}
