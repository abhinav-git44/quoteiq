export const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  detail: any;
  constructor(status: number, detail: any) {
    super(typeof detail === "string" ? detail : detail?.message || `HTTP ${status}`);
    this.status = status;
    this.detail = detail;
  }
}

export function token(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem("quoteiq_token");
  } catch {
    return null;
  }
}

export function setSession(t: string | null, user?: any) {
  try {
    if (t) {
      localStorage.setItem("quoteiq_token", t);
      if (user) localStorage.setItem("quoteiq_user", JSON.stringify(user));
    } else {
      localStorage.removeItem("quoteiq_token");
      localStorage.removeItem("quoteiq_user");
    }
  } catch {
    /* storage unavailable */
  }
}

export async function api<T = any>(path: string, opts: RequestInit & { json?: any } = {}): Promise<T> {
  const headers: Record<string, string> = { ...(opts.headers as Record<string, string>) };
  const t = token();
  if (t) headers["Authorization"] = `Bearer ${t}`;
  let body = opts.body;
  if (opts.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.json);
  }
  const res = await fetch(`${API}${path}`, { ...opts, headers, body });
  if (res.status === 401 && typeof window !== "undefined" && !path.startsWith("/api/auth/login")) {
    setSession(null);
    window.location.href = "/login";
  }
  if (!res.ok) {
    let detail: any = res.statusText;
    try {
      detail = (await res.json()).detail;
    } catch {
      /* not json */
    }
    throw new ApiError(res.status, detail);
  }
  const ct = res.headers.get("content-type") || "";
  return (ct.includes("application/json") ? res.json() : (res.blob() as any)) as Promise<T>;
}

/** Authenticated file fetch -> object URL (files are behind auth). */
export async function fileUrl(path: string): Promise<string> {
  const blob = await api<Blob>(path);
  return URL.createObjectURL(blob);
}

export async function download(path: string, filename?: string) {
  const url = await fileUrl(path);
  const a = document.createElement("a");
  a.href = url;
  if (filename) a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}
