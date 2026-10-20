/**
 * API client. The base URL comes from NEXT_PUBLIC_API_URL (default http://localhost:8000).
 *
 * The operator API key is never bundled into the frontend. An operator types it
 * into the "Operator access" dialog; it is kept in sessionStorage for the current
 * browser session only and sent as X-API-Key on requests.
 */

export const API_BASE = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
const KEY_STORAGE = "gapminer.operatorKey";

export class ApiError extends Error {
  constructor(message: string, public status: number, public detail?: unknown) {
    super(message);
  }
}

export function getOperatorKey(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.sessionStorage.getItem(KEY_STORAGE);
  } catch {
    return null;
  }
}

export function setOperatorKey(key: string | null) {
  try {
    if (key) window.sessionStorage.setItem(KEY_STORAGE, key);
    else window.sessionStorage.removeItem(KEY_STORAGE);
  } catch {
    /* storage unavailable: key lives only in memory for this page */
  }
  window.dispatchEvent(new Event("operator-key-changed"));
}

function messageFrom(body: unknown, status: number): string {
  if (body && typeof body === "object") {
    const d = (body as { detail?: unknown }).detail;
    if (typeof d === "string") return d;
    if (d && typeof d === "object" && "message" in (d as object)) return String((d as { message: unknown }).message);
    if (Array.isArray(d) && d[0]?.msg) return d.map((x: { msg: string; loc?: string[] }) => `${x.loc?.slice(-1)[0] ?? ""}: ${x.msg}`).join("; ");
  }
  if (status === 0) return "Cannot reach the API server. Is the backend running?";
  return `Request failed (HTTP ${status})`;
}

export async function request<T = unknown>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const key = getOperatorKey();
  if (key) headers.set("X-API-Key", key);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { ...init, headers });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ApiError(messageFrom(null, 0), 0);
  }
  const text = await res.text();
  const body = text ? safeJson(text) : null;
  if (!res.ok) throw new ApiError(messageFrom(body, res.status), res.status, body);
  return body as T;
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

export const api = {
  get: <T = unknown>(path: string, signal?: AbortSignal) => request<T>(path, { signal }),
  post: <T = unknown>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body instanceof FormData ? body : body === undefined ? undefined : JSON.stringify(body) }),
  patch: <T = unknown>(path: string, body: unknown) => request<T>(path, { method: "PATCH", body: JSON.stringify(body) }),
};

export type Params = Record<string, string | number | boolean | null | undefined>;

export function qs(params: Params): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "" || v === false) continue;
    sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

/** URL for a file download that respects the same filters as the current view. */
export function downloadUrl(path: string, params: Params): string {
  return `${API_BASE}${path}${qs(params)}`;
}
