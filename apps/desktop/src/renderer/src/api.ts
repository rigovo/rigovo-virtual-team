/* ------------------------------------------------------------------ */
/*  HTTP helpers for communicating with the Rigovo control-plane API   */
/* ------------------------------------------------------------------ */

export const API_BASE =
  (import.meta as ImportMeta & { env: Record<string, string> }).env.VITE_RIGOVO_API ??
  "http://127.0.0.1:8787";

/* ---- readJson ---------------------------------------------------- */

export async function readJson<T>(url: string): Promise<T | null> {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), 7000);
  try {
    const r = await fetch(url, { signal: controller.signal });
    if (!r.ok) return null;
    return (await r.json()) as T;
  } catch {
    return null;
  } finally {
    window.clearTimeout(timeoutId);
  }
}

/* ---- postJson with typed error ----------------------------------- */

export interface PostJsonError {
  __error: true;
  status: number;
  detail: string;
}

export type PostJsonResult<T> = T | PostJsonError | null;

export function isPostError(v: unknown): v is PostJsonError {
  return v != null && typeof v === "object" && "__error" in v;
}

export async function postJson<TReq, TRes>(url: string, body: TReq): Promise<PostJsonResult<TRes>> {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), 10000);
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: controller.signal
    });
    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try {
        const errBody = await res.json();
        if (errBody?.detail) detail = String(errBody.detail);
      } catch { /* ignore parse errors */ }
      return { __error: true, status: res.status, detail };
    }
    return (await res.json()) as TRes;
  } catch {
    return null;
  } finally {
    window.clearTimeout(timeoutId);
  }
}

/* ---- health check ------------------------------------------------ */

export async function isApiHealthy(baseUrl: string): Promise<boolean> {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), 3000);
  try {
    const res = await fetch(`${baseUrl}/health`, { signal: controller.signal });
    return res.ok;
  } catch {
    return false;
  } finally {
    window.clearTimeout(timeoutId);
  }
}

/* ---- Utility functions ------------------------------------------- */

export function isUuid(value: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);
}
