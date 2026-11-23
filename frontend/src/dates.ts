const pad = (n: number) => String(n).padStart(2, "0");

export const addDays = (d: Date, n: number): Date => { const x = new Date(d); x.setDate(x.getDate() + n); return x; };
export const startOfDay = (d: Date): Date => new Date(d.getFullYear(), d.getMonth(), d.getDate());
export const startOfWeek = (d: Date): Date => addDays(startOfDay(d), -((d.getDay() + 6) % 7));
export const ymd = (d: Date): string => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
export const fmtTime = (s: string): string => new Date(s).toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
export const fmtDay = (d: Date): string => d.toLocaleDateString("de-DE", { weekday: "short", day: "2-digit", month: "2-digit" });
export const fmtDate = (s: string | Date): string =>
  (typeof s === "string" && /^\d{4}-\d{2}-\d{2}$/.test(s) ? new Date(s + "T00:00:00") : new Date(s))
    .toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit", year: "numeric" });
export const fmtDateTime = (s: string): string => `${fmtDate(s)} ${fmtTime(s)}`;
export const toInput = (s: string): string => { const d = new Date(s); return `${ymd(d)}T${pad(d.getHours())}:${pad(d.getMinutes())}`; };
export const fromInput = (v: string): string => new Date(v).toISOString();
export const hm = (m: number | null): string => (m == null ? "läuft" : `${Math.floor(m / 60)}:${pad(m % 60)} h`);
export const weekLabel = (monday: Date): string => `${fmtDate(monday)} – ${fmtDate(addDays(monday, 6))}`;
