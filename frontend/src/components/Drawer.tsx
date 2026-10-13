import { useEffect, useRef } from 'react';

type Props = {
  title: React.ReactNode;
  onClose: () => void;
  children: React.ReactNode;
  wide?: boolean;
};

/** Right-side drawer with backdrop; Escape closes; focus moves into the panel. */
export function Drawer({ title, onClose, children, wide }: Props) {
  const panel = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    const prev = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    panel.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeRef.current();
    };
    document.addEventListener('keydown', onKey);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = overflow;
      prev?.focus();
    };
  }, []);

  return (
    <div className="drawer-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div
        className={`drawer${wide ? ' drawer-wide' : ''}`}
        role="dialog"
        aria-modal="true"
        tabIndex={-1}
        ref={panel}
      >
        <div className="drawer-header">
          <h2>{title}</h2>
          <button type="button" className="btn btn-sm btn-ghost" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>
        <div className="drawer-body">{children}</div>
      </div>
    </div>
  );
}
