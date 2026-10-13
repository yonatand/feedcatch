import { useEffect, useState } from 'react';

export function CopyButton({ text, label = 'Copy' }: { text: string; label?: string }) {
  const [state, setState] = useState<'idle' | 'ok' | 'err'>('idle');

  useEffect(() => {
    if (state === 'idle') return undefined;
    const t = window.setTimeout(() => setState('idle'), 1500);
    return () => window.clearTimeout(t);
  }, [state]);

  const copy = async () => {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
      } else {
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.setAttribute('readonly', '');
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        const ok = document.execCommand('copy');
        document.body.removeChild(ta);
        if (!ok) throw new Error('copy failed');
      }
      setState('ok');
    } catch {
      setState('err');
    }
  };

  return (
    <button type="button" className="btn btn-sm btn-ghost" onClick={() => void copy()}>
      {state === 'ok' ? 'Copied' : state === 'err' ? 'Copy failed' : label}
    </button>
  );
}
