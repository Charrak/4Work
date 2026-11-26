import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { get, post } from "../api";
import { useToast } from "../context";
import { useLoad } from "../hooks";
import { fmtDate, fmtTime, ymd } from "../dates";
import { WEEKDAYS, type AutoplanPerson, type AutoplanResult, type AutoplanSlot, type Dept, type HoursOverview, type ShiftTemplate } from "../types";
import { Badge, Btn, Card, Empty, ErrorBox, Field, Spinner } from "../ui";

const h = (v: number | null | undefined): string => (v === null || v === undefined ? "–" : v.toLocaleString("de-DE", { maximumFractionDigits: 1 }));
const blankSlot = (): AutoplanSlot => ({ weekdays: [0, 1, 2, 3, 4], template_id: null, start_time: "08:00", end_time: "16:00", break_minutes: 30, count: 1 });

/** Abrechnungszeitraum (Standard 15.–14.) zu einem Datum; Starttag kommt aus der Einstellung des Servers. */
function periodOf(day: Date, startDay: number): { start: Date; end: Date } {
  const y = day.getFullYear(), m = day.getMonth();
  if (startDay <= 1) return { start: new Date(y, m, 1), end: new Date(y, m + 1, 0) };
  const start = day.getDate() >= startDay ? new Date(y, m, startDay) : new Date(y, m - 1, startDay);
  return { start, end: new Date(start.getFullYear(), start.getMonth() + 1, startDay - 1) };
}

function HoursTable({ rows, preview }: { rows: AutoplanPerson[]; preview?: boolean }) {
  if (!rows.length) return <Empty>Keine Personen in dieser Abteilung.</Empty>;
  return (
    <div style={{ overflowX: "auto" }}>
      <table>
        <thead>
          <tr>
            <th>Person</th>
            {preview && <th>Zeitraum</th>}
            <th title="Wochenstunden × Tage / 7">Soll</th>
            <th title="Genehmigter Urlaub/Abwesenheit an Arbeitstagen zählt als erfüllt">Urlaub</th>
            <th title="Soll minus Urlaub: so viele Stunden sollen geplant werden">Von (Ziel)</th>
            <th title="Obergrenze (Überstunden-Spielraum, bei Minijob Verdienstgrenze)">Bis (Max)</th>
            {preview && <th>Schon geplant</th>}
            {preview && <th>Neu</th>}
            <th>Gesamt</th>
            <th>Rest bis Max</th>
            {preview && <th title="Stunden der gewünschten Schichten, bei denen die Person nicht gesperrt ist">Verfügbar</th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((p) => {
            const over = p.max_h !== null && p.gesamt_h > p.max_h + 0.01;
            const under = p.ziel_h !== null && p.gesamt_h < p.ziel_h - 0.01;
            return (
              <tr key={`${p.user_id}-${p.period_start}`}>
                <td>{p.name} {p.is_minijob && <Badge kind="info">Minijob</Badge>} {p.is_casual && <Badge kind="muted">Aushilfe – kein Stundenkonto</Badge>}</td>
                {preview && <td className="small">{fmtDate(p.period_start)}–{fmtDate(p.period_end)}</td>}
                <td>{h(p.soll_h)}</td>
                <td>{p.urlaub_h ? h(p.urlaub_h) : "–"}</td>
                <td>{h(p.ziel_h)}</td>
                <td>{h(p.max_h)}{p.minijob_max_h !== null && p.is_minijob ? <span className="muted small"> (Minijob)</span> : null}</td>
                {preview && <td>{h(p.geplant_vorher_h)}</td>}
                {preview && <td><b>{h(p.neu_h)}</b></td>}
                <td>{h(p.gesamt_h)} {over ? <Badge kind="bad">über Max</Badge> : under ? <Badge kind="warn">unter Ziel</Badge> : p.ziel_h !== null ? <Badge kind="ok">ok</Badge> : null}</td>
                <td>{h(p.rest_h)}</td>
                {preview && <td>{h(p.verfuegbar_h)}</td>}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default function Autoplan() {
  const toast = useToast();
  const depts = useLoad(() => get<Dept[]>("/departments"), []);
  const tpls = useLoad(() => get<ShiftTemplate[]>("/shift-templates"), []);
  const [dept, setDept] = useState<number | "">("");
  const deptId = dept === "" ? (depts.data?.[0]?.id ?? "") : dept;
  const [overtime, setOvertime] = useState(0);

  const overview = useLoad(() => get<HoursOverview>(`/autoplan/hours${deptId ? `?department_id=${deptId}&overtime_pct=${overtime}` : ""}`), [deptId, overtime]);
  const sd = overview.data?.start_day ?? 15;
  const nextPeriod = useMemo(() => {
    const cur = periodOf(new Date(), sd);
    const start = new Date(cur.end.getFullYear(), cur.end.getMonth(), cur.end.getDate() + 1);
    return { cur, next: periodOf(start, sd) };
  }, [sd]);

  const [from, setFrom] = useState<string>("");
  const [to, setTo] = useState<string>("");
  const [slots, setSlots] = useState<AutoplanSlot[]>([blankSlot()]);
  const [createOpen, setCreateOpen] = useState(true);
  const [workDays, setWorkDays] = useState(true);
  const [res, setRes] = useState<AutoplanResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const start = from || ymd(nextPeriod.next.start);
  const end = to || ymd(nextPeriod.next.end);
  const setSlot = (i: number, patch: Partial<AutoplanSlot>) => { setSlots((l) => l.map((x, j) => (j === i ? { ...x, ...patch } : x))); setRes(null); };
  const applyTemplate = (i: number, id: string) => {
    const t = (tpls.data ?? []).find((x) => x.id === Number(id));
    setSlot(i, t ? { template_id: t.id, start_time: t.start_time, end_time: t.end_time, break_minutes: t.break_minutes } : { template_id: null });
  };

  const body = (apply: boolean) => ({
    department_id: deptId, start, end, apply, create_open: createOpen, overtime_pct: overtime, respect_work_days: workDays,
    slots: slots.map((s) => ({ ...s, template_id: s.template_id ?? undefined })),
  });
  const run = async (apply: boolean) => {
    setError(null);
    if (!deptId) { setError("Bitte eine Abteilung wählen."); return; }
    try {
      const r = await post<AutoplanResult>("/autoplan", body(apply));
      setRes(r);
      if (apply) { toast(`Übernommen: ${(r.counts.created ?? 0) + (r.counts.filled_existing ?? 0)} Schichten geplant (noch unveröffentlicht)`); overview.reload(); }
    } catch (e) { setError((e as Error).message); }
  };

  const byDay = useMemo(() => {
    const m = new Map<string, AutoplanResult["created"]>();
    (res?.created ?? []).forEach((c) => m.set(c.date, [...(m.get(c.date) ?? []), c]));
    return [...m.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [res]);

  return (
    <>
      <h1>Autoplaner</h1>
      <p className="muted small">
        Verteilt Schichten fair auf passende Personen – unter Beachtung von Verfügbarkeit, Urlaub, Arbeitstagen, Vertragsstunden, Ruhezeit, Höchstarbeitszeit,
        Jugendschutz und Minijob-Grenze. Abgerechnet wird vom {sd}. bis zum {sd - 1 || "Monatsende"}{sd > 1 ? ". des Folgemonats" : ""}. Der Vorschlag wird erst nach „Übernehmen“
        gespeichert und ist dann noch <b>unveröffentlicht</b>. Danach im <Link to="/plan">Dienstplan</Link> prüfen, anpassen und veröffentlichen.
      </p>

      <Card title={`Stundenrahmen im aktuellen Abrechnungszeitraum${overview.data ? ` (${fmtDate(overview.data.period_start)}–${fmtDate(overview.data.period_end)})` : ""}`}>
        <div className="row" style={{ marginBottom: ".5rem", flexWrap: "wrap" }}>
          <select style={{ width: "auto" }} value={deptId} onChange={(e) => { setDept(Number(e.target.value)); setRes(null); }} aria-label="Abteilung">
            {(depts.data ?? []).map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select>
          <label className="inline-check"><span>Überstunden-Spielraum</span>
            <select style={{ width: "auto" }} value={overtime} onChange={(e) => setOvertime(Number(e.target.value))}>
              {[0, 5, 10, 15, 20, 25].map((p) => <option key={p} value={p}>{p} %</option>)}
            </select>
          </label>
        </div>
        <ErrorBox error={overview.error} onRetry={overview.reload} />
        {overview.loading && !overview.data && <Spinner />}
        {overview.data && <HoursTable rows={overview.data.people} />}
        <p className="muted small">
          Von = Soll aus den Wochenstunden (anteilig bei Ein-/Austritt) minus Urlaub. Bis = Von plus Überstunden-Spielraum, bei Minijob höchstens Verdienstgrenze ÷ Stundensatz.
          Aushilfen haben kein Stundenkonto (kein Soll, keine Plus-/Minusstunden): Sie werden nachrangig nach Verfügbarkeit eingeplant, Einsätze mindestens 4 Tage im Voraus (§ 12 TzBfG), bei Minijob bis zur Verdienstgrenze. Gleiches gilt für Personen ohne Wochenstunden.
        </p>
      </Card>

      <Card title="Bedarf festlegen">
        <div className="row" style={{ flexWrap: "wrap", alignItems: "end" }}>
          <Field label="Von"><input type="date" value={start} onChange={(e) => { setFrom(e.target.value); setRes(null); }} /></Field>
          <Field label="Bis"><input type="date" value={end} onChange={(e) => { setTo(e.target.value); setRes(null); }} /></Field>
          <Btn onClick={() => { setFrom(ymd(nextPeriod.cur.start)); setTo(ymd(nextPeriod.cur.end)); setRes(null); }}>Dieser Zeitraum</Btn>
          <Btn onClick={() => { setFrom(ymd(nextPeriod.next.start)); setTo(ymd(nextPeriod.next.end)); setRes(null); }}>Nächster Zeitraum</Btn>
        </div>
        <div className="stack" style={{ marginTop: ".75rem" }}>
          {slots.map((s, i) => (
            <div key={i} className="card" style={{ padding: ".6rem" }}>
              <div className="row" style={{ flexWrap: "wrap", gap: ".25rem" }}>
                {WEEKDAYS.map((d, n) => (
                  <label key={d} className="inline-check">
                    <input type="checkbox" checked={s.weekdays.includes(n)}
                      onChange={(e) => setSlot(i, { weekdays: e.target.checked ? [...s.weekdays, n].sort() : s.weekdays.filter((x) => x !== n) })} />
                    <span>{d.slice(0, 2)}</span>
                  </label>
                ))}
              </div>
              <div className="row" style={{ flexWrap: "wrap", alignItems: "end" }}>
                <Field label="Vorlage">
                  <select value={s.template_id ?? ""} onChange={(e) => applyTemplate(i, e.target.value)}>
                    <option value="">– eigene Zeiten –</option>
                    {(tpls.data ?? []).filter((t) => !t.department_id || t.department_id === deptId).map((t) => <option key={t.id} value={t.id}>{t.name} ({t.start_time}–{t.end_time})</option>)}
                  </select>
                </Field>
                <Field label="Beginn"><input type="time" value={s.start_time} onChange={(e) => setSlot(i, { start_time: e.target.value, template_id: null })} /></Field>
                <Field label="Ende"><input type="time" value={s.end_time} onChange={(e) => setSlot(i, { end_time: e.target.value, template_id: null })} /></Field>
                <Field label="Pause (Min.)"><input type="number" min={0} max={240} value={s.break_minutes} onChange={(e) => setSlot(i, { break_minutes: Number(e.target.value) })} /></Field>
                <Field label="Personen"><input type="number" min={1} max={20} value={s.count} onChange={(e) => setSlot(i, { count: Math.max(1, Number(e.target.value)) })} /></Field>
                {slots.length > 1 && <button className="link" onClick={() => { setSlots((l) => l.filter((_, j) => j !== i)); setRes(null); }}>Entfernen</button>}
              </div>
            </div>
          ))}
          <div><Btn onClick={() => { setSlots((l) => [...l, blankSlot()]); setRes(null); }}>+ Weiterer Bedarf (z. B. Spätschicht)</Btn></div>
          <label className="inline-check"><input type="checkbox" checked={workDays} onChange={(e) => { setWorkDays(e.target.checked); setRes(null); }} />
            <span>Nur an den Arbeitstagen laut Vertrag einteilen</span></label>
          <label className="inline-check"><input type="checkbox" checked={createOpen} onChange={(e) => { setCreateOpen(e.target.checked); setRes(null); }} />
            <span>Nicht besetzbare Schichten als offene Schichten anlegen (Mitarbeiter können sie übernehmen)</span></label>
        </div>
        <ErrorBox error={error} />
        <div className="row" style={{ marginTop: ".75rem" }}>
          <Btn kind="primary" onClick={() => run(false)}>Vorschlag berechnen</Btn>
          {res && !res.applied && (res.counts.created || res.counts.filled_existing || res.counts.open_created) ? <Btn onClick={() => run(true)}>Übernehmen (unveröffentlicht)</Btn> : null}
        </div>
      </Card>

      {res && (
        <>
          <Card title={res.applied ? "Übernommen" : "Vorschau (noch nichts gespeichert)"}>
            <p>
              <Badge kind="ok">{(res.counts.created ?? 0) + (res.counts.filled_existing ?? 0)} besetzt</Badge>{" "}
              {res.counts.open_created ? <Badge kind="info">{res.counts.open_created} offen angelegt</Badge> : null}{" "}
              {res.counts.unfilled ? <Badge kind="bad">{res.counts.unfilled} nicht besetzbar</Badge> : <Badge kind="ok">alles besetzt</Badge>}
            </p>
            {res.unfilled.length > 0 && (
              <div className="stack">
                {res.unfilled.map((u, i) => (
                  <div key={`${u.start}-${i}`} className="muted small">
                    <b>{fmtDate(u.date)} {fmtTime(u.start)}–{fmtTime(u.end)}</b>: {u.missing} fehlt – Gründe: {Object.entries(u.reasons).map(([k, v]) => `${k} (${v})`).join(", ") || "keine passende Person in der Abteilung"}
                  </div>
                ))}
              </div>
            )}
            <div style={{ overflowX: "auto", marginTop: ".5rem" }}>
              <table>
                <thead><tr><th>Tag</th><th>Zeit</th><th>Person</th><th>Std.</th></tr></thead>
                <tbody>
                  {byDay.flatMap(([d, list]) => list.map((c, i) => (
                    <tr key={`${d}-${i}-${c.start}`}>
                      <td>{i === 0 ? fmtDate(d) : ""}</td>
                      <td>{fmtTime(c.start)}–{fmtTime(c.end)}</td>
                      <td>{c.open ? <Badge kind="info">offen</Badge> : c.user_name}</td>
                      <td>{h(c.hours)}</td>
                    </tr>
                  )))}
                </tbody>
              </table>
            </div>
          </Card>
          <Card title="Stunden je Person und Abrechnungszeitraum nach diesem Vorschlag">
            <HoursTable rows={res.people} preview />
          </Card>
        </>
      )}
    </>
  );
}
