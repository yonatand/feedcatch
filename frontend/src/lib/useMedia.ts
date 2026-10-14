import { useSyncExternalStore } from 'react';

/** Must match the `max-width: 900px` breakpoint in styles.css. */
export const MOBILE_QUERY = '(max-width: 900px)';

let mql: MediaQueryList | null = null;
function getMql(): MediaQueryList | null {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return null;
  if (!mql) mql = window.matchMedia(MOBILE_QUERY);
  return mql;
}

function subscribe(cb: () => void): () => void {
  const m = getMql();
  if (!m) return () => undefined;
  m.addEventListener('change', cb);
  return () => m.removeEventListener('change', cb);
}

/** True at the mobile layout width (<= 900px). Used to swap complex tables for explicit card lists. */
export function useIsMobile(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => getMql()?.matches ?? false,
    () => false,
  );
}
