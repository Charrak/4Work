export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
  get isOffline(): boolean { return this.status === 0 || this.status === 503; }
  get isConflict(): boolean { return this.status === 409; }
}

function csrf(): string {
  const m = document.cookie.match(/(?:^|; )csrf_token=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : "";
}

function messageFrom(detail: any, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (detail && typeof detail.message === "string") return detail.message;
  if (Array.isArray(detail)) return detail.map((d) => String(d.msg ?? "").replace(/^Value error, /, "")).join(" ");
  return fallback;
}

export async function api<T = any>(path: string, opts: { method?: string; body?: unknown } = {}): Promise<T> {
  const method = opts.method ?? "GET";
  const headers: Record<string, string> = {};
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET") headers["X-CSRF-Token"] = csrf();
  let res: Response;
  try {
    res = await fetch("/api" + path, {
      method, headers, credentials: "same-origin",
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    });
  } catch {
    throw new ApiError(0, "Keine Internetverbindung");
  }
  if (res.status === 503) throw new ApiError(503, "Keine Internetverbindung oder Server nicht erreichbar");
  if (res.status === 401 && !path.startsWith("/auth/login")) window.dispatchEvent(new Event("session-expired"));
  if (!res.ok) {
    let detail: unknown = null;
    try { detail = (await res.json()).detail; } catch { /* kein JSON */ }
    throw new ApiError(res.status, messageFrom(detail, `Fehler ${res.status}`), detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

/** Datei hochladen (roher Body, Metadaten als Query-Parameter). */
export async function uploadFile<T = any>(path: string, file: File): Promise<T> {
  let res: Response;
  try {
    res = await fetch("/api" + path, {
      method: "POST", credentials: "same-origin", body: file,
      headers: { "Content-Type": "application/octet-stream", "X-CSRF-Token": csrf() },
    });
  } catch {
    throw new ApiError(0, "Keine Internetverbindung");
  }
  if (res.status === 401) window.dispatchEvent(new Event("session-expired"));
  if (!res.ok) {
    let detail: unknown = null;
    try { detail = (await res.json()).detail; } catch { /* kein JSON */ }
    throw new ApiError(res.status, messageFrom(detail, `Fehler ${res.status}`), detail);
  }
  return res.json() as Promise<T>;
}

export const get = <T = any>(p: string) => api<T>(p);
export const post = <T = any>(p: string, body?: unknown) => api<T>(p, { method: "POST", body: body ?? {} });
export const patch = <T = any>(p: string, body: unknown) => api<T>(p, { method: "PATCH", body });
export const put = <T = any>(p: string, body: unknown) => api<T>(p, { method: "PUT", body });
export const del = <T = any>(p: string) => api<T>(p, { method: "DELETE" });

/** Datei-Download mit Anmeldung (z. B. DSGVO-Export). */
export async function downloadJson(path: string, filename: string): Promise<void> {
  const data = await get(path);
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
  const a = document.createElement("a");
  a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
}

/** Beliebige Datei (z. B. Dokument) mit Anmeldung herunterladen. */
export async function downloadFile(path: string, filename: string): Promise<void> {
  let res: Response;
  try { res = await fetch("/api" + path, { credentials: "same-origin" }); }
  catch { throw new ApiError(0, "Keine Internetverbindung"); }
  if (!res.ok) throw new ApiError(res.status, res.status === 404 ? "Dokument nicht gefunden" : `Fehler ${res.status}`);
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url; a.download = filename; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}

// ---------- Offline-Warteschlange (nur für Aktionen ohne Zeitstempel-Bedeutung) ----------
interface Queued { id: string; path: string; method: string; body: unknown; label: string; userId: number | null }
const QKEY = "dienstplan.queue.v1";
const readQ = (): Queued[] => { try { return JSON.parse(localStorage.getItem(QKEY) || "[]"); } catch { return []; } };
const writeQ = (q: Queued[]) => { try { localStorage.setItem(QKEY, JSON.stringify(q)); } catch { /* voll */ } };
export const queueLength = (): number => readQ().length;

// Benutzer, dem neue Einträge zugeordnet werden (wird vom AuthProvider gesetzt).
let queueUser: number | null = null;
export const setQueueUser = (id: number | null) => { queueUser = id; };
/** Löscht die Warteschlange komplett (z. B. beim Abmelden). Liefert die Zahl verworfener Einträge. */
export function clearQueue(): number {
  const n = readQ().length;
  try { localStorage.removeItem(QKEY); } catch { /* egal */ }
  window.dispatchEvent(new Event("queue-changed"));
  return n;
}

/** Führt die Aktion aus; ist man offline, wird sie gemerkt und später automatisch gesendet. */
export async function mutateOrQueue<T = any>(label: string, path: string, method: string, body: unknown): Promise<{ queued: boolean; data?: T }> {
  try {
    return { queued: false, data: await api<T>(path, { method, body }) };
  } catch (e) {
    if (e instanceof ApiError && e.isOffline) {
      writeQ([...readQ(), { id: crypto.randomUUID(), path, method, body, label, userId: queueUser }]);
      window.dispatchEvent(new Event("queue-changed"));
      return { queued: true };
    }
    throw e;
  }
}

/**
 * Sendet gemerkte Aktionen der Reihe nach, aber nur die des angemeldeten Benutzers.
 * Einträge anderer Benutzer (oder ohne Zuordnung) werden NIE gesendet, sondern verworfen und gemeldet.
 */
export async function flushQueue(userId: number): Promise<string[]> {
  const notes: string[] = [];
  const all = readQ();
  const foreign = all.filter((i) => i.userId !== userId);
  let q = all.filter((i) => i.userId === userId);
  if (foreign.length) {
    notes.push(`Verworfen: ${foreign.length} nicht gesendete Aktion(en) eines anderen Benutzers`);
    writeQ(q);
  }
  while (q.length) {
    const item = q[0];
    try {
      await api(item.path, { method: item.method, body: item.body });
      notes.push(`Gesendet: ${item.label}`);
    } catch (e) {
      if (e instanceof ApiError && e.isOffline) break;           // weiterhin offline
      notes.push(`Nicht gesendet (${item.label}): ${(e as Error).message}`);
    }
    q = q.slice(1);
    writeQ(q);
  }
  window.dispatchEvent(new Event("queue-changed"));
  return notes;
}
