// Single fetch wrapper for the backend JSON API.

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

type UnauthorizedHandler = () => void;

let unauthorizedHandler: UnauthorizedHandler | null = null;

/** App registers a handler so 401s re-check auth status and route to /login or /setup. */
export function setUnauthorizedHandler(fn: UnauthorizedHandler | null): void {
  unauthorizedHandler = fn;
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

/** Turns FastAPI error bodies (string detail or 422 validation list) into one readable string. */
export function formatDetail(body: unknown, fallback: string): string {
  if (!isRecord(body)) return fallback;
  const detail = body.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    const parts = detail.map((d: unknown) => {
      if (!isRecord(d)) return String(d);
      const loc = Array.isArray(d.loc)
        ? d.loc.filter((x: unknown) => x !== 'body').map((x: unknown) => String(x)).join('.')
        : '';
      const msg = typeof d.msg === 'string' ? d.msg : JSON.stringify(d);
      return loc ? `${loc}: ${msg}` : msg;
    });
    return parts.join('; ') || fallback;
  }
  if (detail !== undefined) return JSON.stringify(detail);
  return fallback;
}

export type ApiInit = Omit<RequestInit, 'body'> & { body?: unknown; query?: Record<string, QueryValue> };
export type QueryValue = string | number | boolean | null | undefined;

export function buildQuery(query: Record<string, QueryValue> | undefined): string {
  if (!query) return '';
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v === undefined || v === null || v === '') continue;
    params.set(k, String(v));
  }
  const s = params.toString();
  return s ? `?${s}` : '';
}

export async function api<T>(path: string, init: ApiInit = {}): Promise<T> {
  const { body, query, headers, ...rest } = init;
  const hasBody = body !== undefined;
  let res: Response;
  try {
    res = await fetch(path + buildQuery(query), {
      credentials: 'same-origin',
      ...rest,
      headers: {
        Accept: 'application/json',
        ...(hasBody ? { 'Content-Type': 'application/json' } : {}),
        ...headers,
      },
      body: hasBody ? JSON.stringify(body) : undefined,
    });
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : String(e);
    throw new ApiError(0, `Network error: ${msg}`);
  }

  if (res.status === 204) return undefined as T;

  const text = await res.text();
  let parsed: unknown = undefined;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = undefined;
    }
  }

  if (!res.ok) {
    const detail = formatDetail(parsed, text.slice(0, 300) || `${res.status} ${res.statusText}`);
    if (res.status === 401 && !path.startsWith('/api/auth/') && unauthorizedHandler) {
      unauthorizedHandler();
    }
    throw new ApiError(res.status, detail);
  }
  return parsed as T;
}

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.detail;
  if (e instanceof Error) return e.message;
  return String(e);
}
