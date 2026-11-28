import { addDays, startOfWeek, ymd } from "./dates";
import { Field } from "./ui";

/** Zeitraum als lokale Kalendertage (inklusive), z. B. { from: "2026-11-15", to: "2026-12-14" }. */
export interface Period { from: string; to: string }

/** Abrechnungszeitraum der Firma: 15. bis 14. des Folgemonats. offset = -1 → vorheriger Zeitraum. */
export function billingPeriod(offset = 0, today = new Date()): Period {
  const y = today.getFullYear();
  const m = today.getMonth() + (today.getDate() >= 15 ? 0 : -1) + offset;
  return { from: ymd(new Date(y, m, 15)), to: ymd(new Date(y, m + 1, 14)) };
}

const PRESETS: { key: string; label: string; make: () => Period }[] = [
  { key: "bill", label: "Abrechnungszeitraum (15.–14.)", make: () => billingPeriod(0) },
  { key: "bill-1", label: "Vorheriger Abrechnungszeitraum", make: () => billingPeriod(-1) },
  { key: "week", label: "Diese Woche", make: () => { const m = startOfWeek(new Date()); return { from: ymd(m), to: ymd(addDays(m, 6)) }; } },
  { key: "week-1", label: "Letzte Woche", make: () => { const m = addDays(startOfWeek(new Date()), -7); return { from: ymd(m), to: ymd(addDays(m, 6)) }; } },
  { key: "month", label: "Dieser Monat", make: () => { const n = new Date(); return { from: ymd(new Date(n.getFullYear(), n.getMonth(), 1)), to: ymd(new Date(n.getFullYear(), n.getMonth() + 1, 0)) }; } },
  { key: "month-1", label: "Letzter Monat", make: () => { const n = new Date(); return { from: ymd(new Date(n.getFullYear(), n.getMonth() - 1, 1)), to: ymd(new Date(n.getFullYear(), n.getMonth(), 0)) }; } },
];

/** Query-Parameter start/end (UTC) für den Zeitraum: 00:00 des ersten Tages bis 00:00 nach dem letzten Tag. */
export function periodQuery(p: Period): { q: string; valid: boolean } {
  const s = new Date(p.from + "T00:00:00");
  const e = new Date(p.to + "T00:00:00"); e.setDate(e.getDate() + 1);
  const valid = !isNaN(s.getTime()) && !isNaN(e.getTime()) && e > s;
  return { q: valid ? `start=${encodeURIComponent(s.toISOString())}&end=${encodeURIComponent(e.toISOString())}` : "", valid };
}

export function PeriodPicker({ value, onChange }: { value: Period; onChange: (p: Period) => void }) {
  const match = PRESETS.find((p) => { const x = p.make(); return x.from === value.from && x.to === value.to; });
  return (
    <div className="row period-picker">
      <div className="grow">
        <Field label="Zeitraum">
          <select value={match?.key ?? ""} onChange={(e) => { const p = PRESETS.find((x) => x.key === e.target.value); if (p) onChange(p.make()); }}>
            {!match && <option value="">Eigener Zeitraum</option>}
            {PRESETS.map((p) => <option key={p.key} value={p.key}>{p.label}</option>)}
          </select>
        </Field>
      </div>
      <div className="grow"><Field label="Von"><input type="date" value={value.from} onChange={(e) => onChange({ ...value, from: e.target.value })} /></Field></div>
      <div className="grow"><Field label="Bis"><input type="date" value={value.to} onChange={(e) => onChange({ ...value, to: e.target.value })} /></Field></div>
    </div>
  );
}

export const fmtPeriod = (p: Period): string => {
  const f = (s: string) => new Date(s + "T00:00:00").toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit", year: "numeric" });
  return `${f(p.from)} – ${f(p.to)}`;
};
