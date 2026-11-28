import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { del, get, patch, post } from "../api";
import { useAuth, useToast } from "../context";
import { useLoad } from "../hooks";
import { useLive } from "../live";
import { fmtDateTime, fromInput, hm, toInput } from "../dates";
import { ClockPanel } from "../clock";
import { billingPeriod, fmtPeriod, Period, PeriodPicker, periodQuery } from "../period";
import type { Company, Dept, Shift, TimeEntry, User } from "../types";
import { Badge, Btn, Card, Empty, ErrorBox, Field, Modal } from "../ui";

/** Gesetzliche Mindestpause wie im Server (§ 4 ArbZG / § 11 JArbSchG), falls keine Schicht zugeordnet ist. */
function legalBreak(grossMin: number, minor: boolean): number {
  if (minor) return grossMin > 360 ? 60 : grossMin > 270 ? 30 : 0;
  return grossMin > 540 ? 45 : grossMin > 360 ? 30 : 0;
}

const pad = (n: number) => String(n).padStart(2, "0");
const clock = (iso: string) => { const d = new Date(iso); return `${pad(d.getHours())}:${pad(d.getMinutes())}`; };
const dayLabel = (iso: string) => new Date(iso).toLocaleDateString("de-DE", { weekday: "short", day: "2-digit", month: "2-digit", year: "numeric" });

/** Abweichung Soll/Ist, ab der Vorgesetzte bzw. Planer den Eintrag einzeln prüfen müssen (Minuten). */
export const DEVIATION_LIMIT = 30;

export type Row = TimeEntry & {
  gross: number | null; brk: number; net: number | null; brkFromShift: boolean;
  /** Woher die Pause stammt: gestempelt, aus der Schicht oder gesetzliche Mindestpause */
  brkSource: "stamped" | "stamped+legal" | "shift" | "legal"; brkStamped: number | null;
  shift: Shift | null; soll: number | null; diff: number | null; startDiff: number | null; endDiff: number | null;
  deviation: boolean; reason: string;
};
type Who = "me" | "all" | number;
type StatusFilter = "all" | "open" | "approved" | "check";

const signed = (m: number) => `${m > 0 ? "+" : m < 0 ? "−" : "±"}${hm(Math.abs(m)).replace(" h", "")}`;
const minutesBetween = (a: string, b: string) => Math.round((new Date(b).getTime() - new Date(a).getTime()) / 60000);

/** Ist-Eintrag mit Soll (Schicht) vergleichen. */
export function buildRow(e: TimeEntry, shift: Shift | null, minor: boolean): Row {
  const gross = e.clock_out ? minutesBetween(e.clock_in, e.clock_out) : null;
  // gleiche Logik wie im Server (reports.effective_break)
  const legal = gross == null ? 0 : legalBreak(gross, minor);
  const stamped = e.break_taken_min ?? null;
  let brk = 0;
  let brkSource: Row["brkSource"] = "legal";
  if (gross != null) {
    if (stamped != null) { brk = Math.max(stamped, legal); brkSource = stamped >= legal ? "stamped" : "stamped+legal"; }
    else if (shift && shift.break_minutes > 0) { brk = shift.break_minutes; brkSource = "shift"; }
    else { brk = legal; brkSource = "legal"; }
  }
  const net = gross == null ? null : Math.max(0, gross - brk);
  const soll = shift ? Math.max(0, minutesBetween(shift.start, shift.end) - shift.break_minutes) : null;
  const diff = net != null && soll != null ? net - soll : null;
  const startDiff = shift ? minutesBetween(shift.start, e.clock_in) : null;
  const endDiff = shift && e.clock_out ? minutesBetween(shift.end, e.clock_out) : null;
  let reason = "";
  if (e.clock_out) {
    if (!shift) reason = "Ohne geplante Schicht gestempelt";
    else if (Math.abs(diff!) > DEVIATION_LIMIT) reason = `Arbeitszeit weicht um ${signed(diff!)} h vom Soll ab`;
    else if (Math.abs(startDiff!) > DEVIATION_LIMIT) reason = `Kommen ${signed(startDiff!)} h gegenüber Schichtbeginn`;
    else if (Math.abs(endDiff!) > DEVIATION_LIMIT) reason = `Gehen ${signed(endDiff!)} h gegenüber Schichtende`;
  }
  return { ...e, gross, brk, net, brkFromShift: brkSource === "shift", brkSource, brkStamped: stamped, shift, soll, diff, startDiff, endDiff, deviation: reason !== "", reason };
}

/** Pause mit Herkunft: ☕ gestempelt, 📅 laut Schicht, § gesetzliche Mindestpause. */
export function PauseCell({ r }: { r: Row }) {
  if (r.gross == null) return <>{r.break_start ? <Badge kind="warn">Pause läuft</Badge> : "—"}</>;
  if (r.brkSource === "stamped+legal")
    return <span title={`Gestempelt ${r.brkStamped} min – gesetzlich mindestens ${r.brk} min, daher werden ${r.brk} min abgezogen`}><s className="orig">{r.brkStamped}</s>{r.brk} min §</span>;
  const mark = r.brkSource === "stamped" ? " ☕" : r.brkSource === "shift" ? " 📅" : " §";
  return <span title={r.brkSource === "stamped" ? "gestempelte Pause" : r.brkSource === "shift" ? "Pause laut Schicht" : "gesetzliche Mindestpause"}>{r.brk} min{mark}</span>;
}

/** Korrigierte Zeit: Original durchgestrichen darüber, neue Zeit darunter. */
function Corrected({ orig, now, edited }: { orig?: string | null; now: string | null; edited: boolean }) {
  const changed = edited && (orig ?? null) !== now && !(orig && now && clock(orig) === clock(now) && new Date(orig).toDateString() === new Date(now).toDateString());
  return (
    <>
      {changed && <s className="orig" title="ursprünglich gestempelt">{orig ? clock(orig) : "—"}</s>}
      {now ? clock(now) : null}
    </>
  );
}

function Delta({ m }: { m: number | null }) {
  if (m == null || Math.abs(m) < 5) return null;
  return <small className={`delta ${Math.abs(m) > DEVIATION_LIMIT ? "bad" : "warn"}`}> {m > 0 ? "+" : "−"}{Math.abs(m)}</small>;
}

export default function Time() {
  const { me, can } = useAuth();
  const toast = useToast();
  const approver = can("time.approve");
  const [editing, setEditing] = useState<TimeEntry | null>(null);
  const [period, setPeriod] = useState<Period>(billingPeriod(0));
  const [params] = useSearchParams();
  const checkLink = approver && params.get("filter") === "pruefen";
  const [who, setWho] = useState<Who>(checkLink ? "all" : "me");
  const [dept, setDept] = useState<number | "">("");
  const [status, setStatus] = useState<StatusFilter>(checkLink ? "check" : "all");
  const { q, valid } = periodQuery(period);
  const tooLong = valid && (new Date(period.to).getTime() - new Date(period.from).getTime()) / 86400000 > 92;

  const whoParam = who === "me" ? "" : who === "all" ? "&all=true" : `&user_id=${who}`;
  const entries = useLoad(() => (valid ? get<TimeEntry[]>(`/time/entries?${q}${whoParam}`) : Promise.resolve([] as TimeEntry[])), [q, whoParam]);
  const shifts = useLoad(() => (valid && !tooLong && can("shifts.view") ? get<Shift[]>(`/shifts?${q}`) : Promise.resolve([] as Shift[])), [q]);
  const users = useLoad(() => (approver && can("users.view") ? get<User[]>("/users") : Promise.resolve([] as User[])), []);
  const depts = useLoad(() => (approver ? get<Dept[]>("/departments") : Promise.resolve([] as Dept[])), []);
  const company = useLoad(() => get<Company>("/auth/company").catch(() => null), []);
  const refresh = () => { entries.reload(); };
  useLive(["time.changed"], refresh);

  const userById = useMemo(() => new Map((users.data ?? []).map((u) => [u.id, u])), [users.data]);
  const shiftById = useMemo(() => new Map((shifts.data ?? []).map((s) => [s.id, s])), [shifts.data]);

  // Einträge aufbereiten, filtern und nach Person gruppieren
  const groups = useMemo(() => {
    const rows: Row[] = (entries.data ?? [])
      .filter((e) => dept === "" || who !== "all" || (userById.get(e.user_id)?.department_ids ?? []).includes(dept))
      .map((e) => {
        const minor = e.user_id === me!.id ? me!.is_minor : !!userById.get(e.user_id)?.is_minor;
        return buildRow(e, e.shift_id != null ? shiftById.get(e.shift_id) ?? null : null, minor);
      })
      .filter((r) => status === "all" || (status === "open" ? !r.approved : status === "approved" ? r.approved : r.deviation && !r.approved))
      .sort((a, b) => a.clock_in.localeCompare(b.clock_in));
    const map = new Map<number, { user_id: number; name: string; rows: Row[] }>();
    for (const r of rows) {
      if (!map.has(r.user_id)) map.set(r.user_id, { user_id: r.user_id, name: r.user_name, rows: [] });
      map.get(r.user_id)!.rows.push(r);
    }
    return [...map.values()].sort((a, b) => a.name.localeCompare(b.name, "de"));
  }, [entries.data, status, dept, who, userById, shiftById, me]);

  const all = groups.flatMap((g) => g.rows);
  const totalNet = all.reduce((a, r) => a + (r.net ?? 0), 0);
  const openRows = all.filter((r) => !r.approved && r.clock_out);
  const toCheck = openRows.filter((r) => r.deviation);
  const unremarkable = openRows.filter((r) => !r.deviation);
  const totalSoll = all.reduce((a, r) => a + (r.soll ?? 0), 0);
  const days = new Set(all.map((r) => `${r.user_id}-${new Date(r.clock_in).toDateString()}`)).size;

  const approveAll = async () => {
    if (!window.confirm(`${unremarkable.length} unauffällige Einträge freigeben? Einträge mit Abweichung über ${DEVIATION_LIMIT} Minuten müssen einzeln geprüft werden.`)) return;
    let ok = 0;
    for (const r of unremarkable) {
      try { await patch(`/time/entries/${r.id}`, { approved: true }); ok++; } catch { /* einzelne Fehler überspringen */ }
    }
    toast(`${ok} Eintrag/Einträge freigegeben`, ok === unremarkable.length ? "ok" : "error");
    entries.reload();
  };

  const whoLabel = who === "me" ? "Meine Zeiten" : who === "all" ? `Alle Mitarbeiter${dept !== "" ? ` · ${depts.data?.find((d) => d.id === dept)?.name ?? ""}` : ""}` : userById.get(who)?.name ?? "";

  return (
    <>
      <div className="spread no-print">
        <h1>Zeiterfassung</h1>
        <div className="row">
          {approver && unremarkable.length > 0 && <Btn onClick={approveAll}>Unauffällige freigeben ({unremarkable.length})</Btn>}
          <button className="btn primary" onClick={() => window.print()} disabled={groups.length === 0}>🖨️ Stundenzettel drucken</button>
        </div>
      </div>

      {can("time.clock") && <div className="no-print"><ClockPanel onChanged={refresh} /></div>}

      <section className="card filter-card">
        <div className="card-head no-print"><h2>Filter</h2></div>
        <div className="no-print stack">
          <PeriodPicker value={period} onChange={setPeriod} />
          <div className="row">
            {approver && (
              <div className="grow">
                <Field label="Mitarbeiter">
                  <select value={String(who)} onChange={(e) => { const v = e.target.value; setWho(v === "me" || v === "all" ? v : Number(v)); }}>
                    <option value="me">Nur ich</option>
                    <option value="all">Alle Mitarbeiter</option>
                    {(users.data ?? []).filter((u) => u.id !== me!.id).sort((a, b) => a.name.localeCompare(b.name, "de")).map((u) => <option key={u.id} value={u.id}>{u.name}{u.is_active ? "" : " (inaktiv)"}</option>)}
                  </select>
                </Field>
              </div>
            )}
            {approver && who === "all" && (users.data ?? []).length > 0 && (
              <div className="grow">
                <Field label="Abteilung">
                  <select value={dept} onChange={(e) => setDept(e.target.value ? Number(e.target.value) : "")}>
                    <option value="">Alle Abteilungen</option>
                    {(depts.data ?? []).map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
                  </select>
                </Field>
              </div>
            )}
            <div className="grow">
              <Field label="Status">
                <select value={status} onChange={(e) => setStatus(e.target.value as StatusFilter)}>
                  <option value="all">Alle Einträge</option>
                  <option value="open">Nur offene</option>
                  <option value="approved">Nur freigegebene</option>
                  <option value="check">Abweichungen &gt; {DEVIATION_LIMIT} min (zu prüfen)</option>
                </select>
              </Field>
            </div>
          </div>
        </div>
        <p className="print-only"><b>{whoLabel}</b> · {fmtPeriod(period)}</p>
      </section>

      <div className="kpis no-print">
        <div className="kpi"><b>{hm(totalSoll)}</b>Soll (geplant)</div>
        <div className="kpi"><b>{hm(totalNet)}</b>Ist (netto)</div>
        <div className={`kpi ${totalNet - totalSoll < 0 ? "kpi-bad" : ""}`}><b>{signed(totalNet - totalSoll)} h</b>Differenz Ist − Soll</div>
        <div className="kpi"><b>{days}</b>Arbeitstage</div>
        <button type="button" className={`kpi kpi-btn ${toCheck.length ? "kpi-alert" : ""}`} onClick={() => setStatus(status === "check" ? "all" : "check")}>
          <b>{toCheck.length}</b>Abweichungen zu prüfen{status === "check" ? " · Filter aktiv" : ""}
        </button>
      </div>

      <ErrorBox error={entries.error} onRetry={entries.reload} />
      {!valid && <div className="alert error">Bitte einen gültigen Zeitraum wählen („Bis“ nach „Von“).</div>}
      {tooLong && <div className="alert error">Der Soll/Ist-Vergleich ist für höchstens 93 Tage möglich. Bitte einen kürzeren Zeitraum wählen, sonst erscheinen alle Einträge als „ungeplant“.</div>}
      {shifts.error && !tooLong && <div className="alert error">Die geplanten Schichten konnten nicht geladen werden ({shifts.error}). Soll-Werte fehlen deshalb.</div>}
      {valid && groups.length === 0 && !entries.loading && <Card><Empty>Keine Stempelzeiten im gewählten Zeitraum.</Empty></Card>}

      {groups.map((g) => {
        const net = g.rows.reduce((a, r) => a + (r.net ?? 0), 0);
        const soll = g.rows.reduce((a, r) => a + (r.soll ?? 0), 0);
        const brk = g.rows.reduce((a, r) => a + (r.gross != null ? r.brk : 0), 0);
        const diffSum = g.rows.reduce((a, r) => a + (r.net ?? 0) - (r.clock_out ? r.soll ?? 0 : 0), 0);
        return (
          <section className="card timesheet" key={g.user_id}>
            <div className="print-only timesheet-head">
              <div><b>{company.data?.company_name ?? "physio & fit VitalZentrum Eschweiler"}</b><br />Stundenzettel</div>
              <img src="/logo.png" alt="" />
            </div>
            <div className="card-head">
              <h2>{g.name}</h2>
              <span className="muted">{fmtPeriod(period)} · Soll <b>{hm(soll)}</b> · Ist <b>{hm(net)}</b> · Diff <b className={diffSum < 0 ? "txt-bad" : diffSum > 0 ? "txt-ok" : ""}>{signed(diffSum)} h</b></span>
            </div>
            <div className="table-wrap">
              <table>
                <thead><tr><th>Datum</th><th>Soll (Schicht)</th><th>Kommen</th><th>Gehen</th><th className="num">Pause</th><th className="num">Soll</th><th className="num">Ist</th><th className="num">Diff</th><th>Status</th><th>Notiz</th>{approver && <th className="no-print"></th>}</tr></thead>
                <tbody>
                  {g.rows.map((r) => (
                    <tr key={r.id} className={r.deviation && !r.approved ? "row-check" : ""}>
                      <td>{dayLabel(r.clock_in)}</td>
                      <td>{r.shift ? `${clock(r.shift.start)}–${clock(r.shift.end)}` : <span className="muted">ungeplant</span>}</td>
                      <td><Corrected orig={r.orig_clock_in} now={r.clock_in} edited={!!r.edited_at} /><Delta m={r.startDiff} /></td>
                      <td>{r.clock_out
                        ? <><Corrected orig={r.orig_clock_out} now={r.clock_out} edited={!!r.edited_at} /><Delta m={r.endDiff} /></>
                        : <Badge kind="info">läuft</Badge>}</td>
                      <td className="num"><PauseCell r={r} /></td>
                      <td className="num">{r.soll == null ? "—" : hm(r.soll)}</td>
                      <td className="num"><b>{r.net == null ? "—" : hm(r.net)}</b></td>
                      <td className={`num ${r.diff == null ? "" : Math.abs(r.diff) > DEVIATION_LIMIT ? "txt-bad" : r.diff !== 0 ? "txt-warn" : ""}`}>{r.diff == null ? "—" : signed(r.diff)}</td>
                      <td>{r.approved
                        ? <Badge kind="ok">{r.deviation ? "Geprüft" : "Freigegeben"}</Badge>
                        : r.deviation ? <span title={r.reason}><Badge kind="bad">Prüfen</Badge></span> : <Badge kind="warn">Offen</Badge>}</td>
                      <td className="wrap small">{r.note}{r.edited_at && <div className="muted">korrigiert von {r.edited_by} am {fmtDateTime(r.edited_at)}</div>}</td>
                      {approver && <td className="no-print"><button className="link" onClick={() => setEditing(r)}>Prüfen</button></td>}
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr><th colSpan={4}>Summe ({g.rows.length} Stempelungen)</th><th className="num">{brk} min</th><th className="num">{hm(soll)}</th><th className="num">{hm(net)}</th><th className={`num ${diffSum < 0 ? "txt-bad" : ""}`}>{signed(diffSum)}</th><th colSpan={approver ? 3 : 2}></th></tr>
                </tfoot>
              </table>
            </div>
            <p className="muted small">Soll = geplante Schicht abzüglich Pause, Ist = gestempelte Zeit abzüglich Pause. Kleine Zahlen bei Kommen/Gehen = Minuten gegenüber dem Schichtbeginn bzw. -ende. Abweichungen über {DEVIATION_LIMIT} Minuten und Stempelungen ohne Schicht müssen von Vorgesetzten oder Planern einzeln geprüft werden. Pause: ☕ gestempelt, 📅 laut Schicht, § gesetzliche Mindestpause (§ 4 ArbZG: über 6 h 30 min, über 9 h 45 min) – wird weniger gestempelt, zählt die gesetzliche.</p>
            <div className="print-only signatures">
              <div><span />Datum, Unterschrift Mitarbeiter/in</div>
              <div><span />Datum, Unterschrift Arbeitgeber</div>
            </div>
          </section>
        );
      })}
      {editing && <EntryModal entry={editing} row={all.find((r) => r.id === editing.id) ?? null} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); refresh(); }} />}
    </>
  );
}

function EntryModal({ entry, row, onClose, onSaved }: { entry: TimeEntry; row: Row | null; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const [cin, setCin] = useState(toInput(entry.clock_in));
  const [cout, setCout] = useState(entry.clock_out ? toInput(entry.clock_out) : "");
  const [note, setNote] = useState(entry.note);
  const [brk, setBrk] = useState<string>(entry.break_taken_min != null ? String(entry.break_taken_min) : "");
  const [error, setError] = useState<string | null>(null);
  const remove = async () => {
    const reason = window.prompt("Eintrag löschen – Begründung (Pflicht, z. B. „Fehlstempelung, doppelt gestempelt“):");
    if (reason === null) return;
    if (reason.trim().length < 5) { setError("Bitte eine Begründung mit mindestens 5 Zeichen angeben."); return; }
    setError(null);
    try { await del(`/time/entries/${entry.id}?reason=${encodeURIComponent(reason.trim())}`); toast("Eintrag gelöscht"); onSaved(); }
    catch (e) { setError((e as Error).message); }
  };
  const save = async (approved: boolean) => {
    setError(null);
    if (approved && row?.deviation && note.trim().length < 5) {
      setError("Bei einer Abweichung über 30 Minuten bitte einen Kontrollvermerk eintragen (z. B. „Überstunden wegen Krankheitsvertretung, abgesprochen“).");
      return;
    }
    try {
      const body: Record<string, unknown> = { clock_in: fromInput(cin), clock_out: cout ? fromInput(cout) : null, note, approved };
      if (brk !== "" && Number(brk) !== (entry.break_taken_min ?? null)) body.break_minutes = Math.max(0, Math.round(Number(brk)));
      await patch(`/time/entries/${entry.id}`, body);
      toast(approved ? "Freigegeben" : "Gespeichert"); onSaved();
    } catch (e) { setError((e as Error).message); }
  };
  return (
    <Modal title={`Zeiteintrag – ${entry.user_name}`} onClose={onClose}>
      <div className="stack">
        {row && (
          <div className="soll-ist">
            <div><small>Soll</small><b>{row.shift ? `${clock(row.shift.start)}–${clock(row.shift.end)}` : "keine Schicht"}</b><span>{row.soll == null ? "—" : hm(row.soll)}</span></div>
            <div><small>Ist</small><b>{clock(row.clock_in)}–{row.clock_out ? clock(row.clock_out) : "läuft"}</b><span>{row.net == null ? "—" : hm(row.net)}</span></div>
            <div><small>Differenz</small><b className={row.deviation ? "txt-bad" : ""}>{row.diff == null ? "—" : `${signed(row.diff)} h`}</b><span>Pause {row.brk} min</span></div>
          </div>
        )}
        {entry.edited_at && (
          <div className="alert info small">
            Ursprünglich gestempelt: <s>{fmtDateTime(entry.orig_clock_in ?? entry.clock_in)} – {entry.orig_clock_out ? fmtDateTime(entry.orig_clock_out) : "—"}</s><br />
            Korrigiert von {entry.edited_by} am {fmtDateTime(entry.edited_at)}
          </div>
        )}
        {row?.deviation && <div className="alert error"><b>Abweichungskontrolle:</b> {row.reason}. Bitte prüfen und einen Kontrollvermerk eintragen, bevor Sie freigeben.</div>}
        <Field label="Beginn"><input type="datetime-local" value={cin} onChange={(e) => setCin(e.target.value)} /></Field>
        <Field label="Ende"><input type="datetime-local" value={cout} onChange={(e) => setCout(e.target.value)} /></Field>
        <Field label="Pause (Minuten)" hint={entry.break_taken_min != null ? `Gestempelt: ${entry.break_taken_min} min. Weniger als gesetzlich vorgeschrieben wird automatisch auf die Mindestpause erhöht.` : "Leer = keine Pause gestempelt (dann gilt die Pause der Schicht bzw. die gesetzliche Mindestpause)."}>
          <input type="number" min={0} max={600} step={5} value={brk} onChange={(e) => setBrk(e.target.value)} placeholder="nicht gestempelt" />
        </Field>
        <Field label={row?.deviation ? "Kontrollvermerk (Pflicht bei Abweichung)" : "Notiz"}><input value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} placeholder={row?.deviation ? "Grund der Abweichung / Absprache" : ""} /></Field>
        <p className="muted small">Änderungen werden im Protokoll festgehalten.</p>
        <ErrorBox error={error} />
        <div className="spread">
          <Btn kind="danger" onClick={remove}>Löschen</Btn>
          <div className="row"><Btn onClick={() => save(false)}>Speichern</Btn><Btn kind="primary" onClick={() => save(true)}>Speichern &amp; freigeben</Btn></div>
        </div>
        <p className="muted small">Gelöschte Einträge werden nur ausgeblendet und mit Begründung protokolliert (Aufbewahrungspflicht für Arbeitszeitnachweise).</p>
      </div>
    </Modal>
  );
}
