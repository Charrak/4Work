import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, del, get, patch, post } from "../api";
import { useAuth, useToast } from "../context";
import { useLoad } from "../hooks";
import { useLive } from "../live";
import { addDays, fmtDay, fmtTime, startOfWeek, weekLabel, ymd } from "../dates";
import type { Claim, Dept, Shift, ShiftTemplate, User } from "../types";
import { Badge, Btn, Card, ErrorBox, Field, Modal, Spinner } from "../ui";

export default function Schedule() {
  const { me, can } = useAuth();
  const toast = useToast();
  const manage = can("shifts.manage");
  const [monday, setMonday] = useState(startOfWeek(new Date()));
  const [dept, setDept] = useState<number | "">("");
  const [edit, setEdit] = useState<{ shift?: Shift; day?: Date; blank?: boolean } | null>(null);

  const depts = useLoad(() => get<Dept[]>("/departments"), []);
  const users = useLoad(() => (can("users.view") ? get<User[]>("/users") : Promise.resolve([] as User[])), []);
  const range = `start=${encodeURIComponent(monday.toISOString())}&end=${encodeURIComponent(addDays(monday, 7).toISOString())}${dept ? `&department_id=${dept}` : ""}`;
  const shifts = useLoad(() => get<Shift[]>(`/shifts?${range}`), [range]);
  useLive(["shifts.changed"], shifts.reload);

  const deptIndex = useMemo(() => new Map((depts.data ?? []).map((d, i) => [d.id, i])), [depts.data]);
  const deptName = (id: number) => depts.data?.find((d) => d.id === id)?.name ?? "";
  const days = Array.from({ length: 7 }, (_, i) => addDays(monday, i));
  const todayKey = ymd(new Date());
  const byDay = (d: Date) => (shifts.data ?? []).filter((s) => ymd(new Date(s.start)) === ymd(d));
  const drafts = (shifts.data ?? []).filter((s) => !s.published).length;

  const publish = async () => {
    try {
      const r = await post<{ published: number }>("/shifts/publish", {
        start: monday.toISOString(), end: addDays(monday, 7).toISOString(), department_id: dept || null });
      toast(r.published ? `${r.published} Schicht(en) veröffentlicht` : "Nichts zu veröffentlichen", r.published ? "ok" : "info");
      shifts.reload();
    } catch (e) { toast((e as Error).message, "error"); }
  };

  const copyToNext = async () => {
    if (!window.confirm("Diese Woche in die nächste Woche kopieren? Die Kopien sind zunächst Entwürfe.")) return;
    try {
      const r = await post<{ created: number; unassigned_due_to_conflict: number }>("/shifts/copy-week", {
        source_start: ymd(monday), target_start: ymd(addDays(monday, 7)), department_id: dept || null });
      toast(`${r.created} Schicht(en) kopiert${r.unassigned_due_to_conflict ? `, ${r.unassigned_due_to_conflict} ohne Person (Konflikt/Urlaub)` : ""}`);
      setMonday(addDays(monday, 7));
    } catch (e) { toast((e as Error).message, "error"); }
  };

  return (
    <>
      <div className="spread"><h1>Dienstplan</h1>
        <div className="row">
          <button className="btn" onClick={() => setMonday(addDays(monday, -7))} aria-label="Vorherige Woche">‹</button>
          <button className="btn" onClick={() => setMonday(startOfWeek(new Date()))}>Heute</button>
          <button className="btn" onClick={() => setMonday(addDays(monday, 7))} aria-label="Nächste Woche">›</button>
        </div>
      </div>
      <p className="muted"><b>{weekLabel(monday)}</b></p>
      <div className="row" style={{ marginBottom: ".75rem" }}>
        <select style={{ width: "auto" }} value={dept} onChange={(e) => setDept(e.target.value ? Number(e.target.value) : "")} aria-label="Abteilung">
          <option value="">Alle Abteilungen</option>
          {(depts.data ?? []).map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
        </select>
        {manage && <Btn onClick={publish} kind="primary">Veröffentlichen{drafts ? ` (${drafts})` : ""}</Btn>}
        {manage && <button className="btn" onClick={() => setEdit({ day: monday, blank: true })}>+ Schichten anlegen</button>}
        {manage && <Btn onClick={copyToNext}>Woche kopieren</Btn>}
        {manage && <Link className="btn" style={{ textDecoration: "none", display: "inline-flex", alignItems: "center" }} to="/autoplaner">Autoplaner</Link>}
        {can("availability.manage") && <Link className="btn" style={{ textDecoration: "none", display: "inline-flex", alignItems: "center" }} to="/verfuegbarkeit">Verfügbarkeiten</Link>}
      </div>
      <ErrorBox error={shifts.error} onRetry={shifts.reload} />
      {shifts.loading && !shifts.data && <Spinner />}
      <div className="week">
        {days.map((d) => (
          <div key={d.toISOString()} className={`day ${ymd(d) === todayKey ? "today" : ""}`}>
            <h4>{fmtDay(d)}{manage && <button className="link" onClick={() => setEdit({ day: d })}>+ Schicht</button>}</h4>
            {byDay(d).map((s) => (
              <button key={s.id} onClick={() => setEdit({ shift: s })}
                className={`shift dept${(deptIndex.get(s.department_id) ?? 0) % 2} ${s.user_id === null ? "open" : ""} ${s.published ? "" : "draft"} ${s.user_id === me!.id ? "mine" : ""}`}>
                <b>{fmtTime(s.start)}–{fmtTime(s.end)}</b>
                {s.user_name ?? "Offene Schicht"}
                <div className="muted small">{deptName(s.department_id)}{s.note ? ` · ${s.note}` : ""}</div>
                {!s.published && <Badge kind="muted">Entwurf</Badge>}
                {s.pending_claims > 0 && <Badge kind="warn">{s.pending_claims} Anfrage(n)</Badge>}
              </button>
            ))}
          </div>
        ))}
      </div>
      {edit && (
        <ShiftModal shift={edit.shift} day={edit.day} blank={edit.blank} depts={depts.data ?? []} users={users.data ?? []} manage={manage}
          defaultDept={dept || depts.data?.[0]?.id}
          onClose={() => setEdit(null)} onChanged={() => { setEdit(null); shifts.reload(); }} />
      )}
    </>
  );
}

const WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"];
const pad2 = (n: number) => String(n).padStart(2, "0");
const hhmm = (iso: string) => { const d = new Date(iso); return `${pad2(d.getHours())}:${pad2(d.getMinutes())}`; };

/** Beginn/Ende aus Datum + Uhrzeiten; Ende vor Beginn = Nachtschicht bis zum Folgetag. */
function toRange(day: Date, from: string, to: string): { start: string; end: string } {
  const s = new Date(`${ymd(day)}T${from}`);
  let e = new Date(`${ymd(day)}T${to}`);
  if (e <= s) e = addDays(e, 1);
  return { start: s.toISOString(), end: e.toISOString() };
}

function durationLabel(from: string, to: string): string {
  if (!from || !to) return "";
  const [fh, fm] = from.split(":").map(Number);
  const [th, tm] = to.split(":").map(Number);
  let m = (th * 60 + tm) - (fh * 60 + fm);
  if (m <= 0) m += 24 * 60;
  return `${Math.floor(m / 60)}:${pad2(m % 60)} h`;
}

type Pending = { label: string; body: Record<string, unknown>; warnings: string[] };

function ShiftModal({ shift, day, blank, depts, users, manage, defaultDept, onClose, onChanged }: {
  shift?: Shift; day?: Date; blank?: boolean; depts: Dept[]; users: User[]; manage: boolean; defaultDept?: number;
  onClose: () => void; onChanged: () => void;
}) {
  const { me, can } = useAuth();
  const toast = useToast();
  const base = day ?? new Date(shift?.start ?? Date.now());
  const weekStart = startOfWeek(base);
  const [deptId, setDeptId] = useState<number>(shift?.department_id ?? defaultDept ?? depts[0]?.id ?? 0);
  const [userId, setUserId] = useState<number | "">(shift?.user_id ?? "");
  const [date, setDate] = useState(ymd(base));
  const [from, setFrom] = useState(shift ? hhmm(shift.start) : "08:00");
  const [to, setTo] = useState(shift ? hhmm(shift.end) : "16:00");
  const [weekdays, setWeekdays] = useState<number[]>(day && !blank ? [(day.getDay() + 6) % 7] : []);
  const [weeks, setWeeks] = useState(1);
  const [note, setNote] = useState(shift?.note ?? "");
  const [breakMin, setBreakMin] = useState<number>(shift?.break_minutes ?? 0);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [pending, setPending] = useState<Pending[]>([]);
  useEffect(() => { setWarnings([]); setPending([]); }, [date, from, to, userId, deptId, weekdays, weeks]);
  const tpls = useLoad(() => (manage && !shift ? get<ShiftTemplate[]>("/shift-templates") : Promise.resolve([] as ShiftTemplate[])), [manage, shift?.id]);
  const [needsApproval, setNeedsApproval] = useState(shift?.claim_requires_approval ?? true);
  const [error, setError] = useState<string | null>(null);
  const [swapTo, setSwapTo] = useState<number | "">("");
  const claims = useLoad(() => (shift && manage && shift.user_id === null ? get<Claim[]>(`/shifts/${shift.id}/claims`) : Promise.resolve([] as Claim[])), [shift?.id]);

  const candidates = users.filter((u) => u.is_active && u.department_ids.includes(deptId));
  const toggleDay = (i: number) => setWeekdays((w) => (w.includes(i) ? w.filter((x) => x !== i) : [...w, i].sort()));

  const run = async (fn: () => Promise<unknown>, okMsg: string) => {
    setError(null);
    try { await fn(); if (okMsg) toast(okMsg); onChanged(); }
    catch (e) {
      const err = e as ApiError;
      const w = (err.detail as any)?.warnings;
      if (err.status === 422 && Array.isArray(w)) { setWarnings(w); setError(null); return; }
      setError(err.isConflict && (err.detail as any)?.current_version
        ? "Diese Schicht wurde inzwischen von jemand anderem geändert. Bitte schließen und neu öffnen."
        : err.message);
    }
  };

  const common = () => ({ department_id: deptId, user_id: userId === "" ? null : userId, note, break_minutes: breakMin, claim_requires_approval: needsApproval });

  // Bestehende Schicht ändern
  const saveEdit = () => run(async () => {
    const r = toRange(new Date(`${date}T00:00`), from, to);
    await patch(`/shifts/${shift!.id}`, { ...common(), ...r, ignore_warnings: warnings.length > 0, version: shift!.version });
  }, "Gespeichert");

  // Neue Schichten: ausgewählte Wochentage × Anzahl Wochen
  const saveNew = async () => {
    setError(null);
    let items: Pending[];
    if (pending.length > 0) {
      items = pending.map((p) => ({ ...p, body: { ...p.body, ignore_warnings: true } }));
    } else {
      if (weekdays.length === 0) { setError("Bitte mindestens einen Wochentag auswählen."); return; }
      if (!from || !to) { setError("Bitte Uhrzeit von und bis angeben."); return; }
      items = [];
      for (let w = 0; w < weeks; w++) {
        for (const wd of weekdays) {
          const d = addDays(weekStart, w * 7 + wd);
          items.push({ label: `${fmtDay(d)}, ${from}–${to}`, body: { ...common(), ...toRange(d, from, to), ignore_warnings: false }, warnings: [] });
        }
      }
    }
    let created = 0;
    const stillPending: Pending[] = [];
    const errors: string[] = [];
    for (const it of items) {
      try { await post("/shifts", it.body); created++; }
      catch (e) {
        const err = e as ApiError;
        const w = (err.detail as any)?.warnings;
        if (err.status === 422 && Array.isArray(w)) stillPending.push({ ...it, warnings: w });
        else errors.push(`${it.label}: ${err.message}`);
      }
    }
    if (created) toast(`${created} Schicht(en) angelegt`, "ok");
    if (stillPending.length === 0 && errors.length === 0) { onChanged(); return; }
    setPending(stillPending);
    if (errors.length) setError(errors.join(" · "));
  };

  // Ansicht für Schichtmitarbeiter (und Planer ohne Bearbeitungsrecht)
  if (!manage) {
    const s = shift!;
    const isMine = s.user_id === me!.id;
    const colleagues = users.filter((u) => u.is_active && u.id !== me!.id && u.department_ids.includes(s.department_id));
    const future = new Date(s.start) > new Date();
    return (
      <Modal title="Schicht" onClose={onClose}>
        <div className="stack">
          <p><b>{fmtDay(new Date(s.start))}</b>, {fmtTime(s.start)}–{fmtTime(s.end)} Uhr<br />
            {s.user_name ?? "Offene Schicht"}<br /><span className="muted">{depts.find((d) => d.id === s.department_id)?.name} {s.break_minutes > 0 && `· Pause ${s.break_minutes} min`} {s.note && `· ${s.note}`}</span></p>
          <ErrorBox error={error} />
          {s.user_id === null && can("swap.request") && <Btn kind="primary" onClick={() => run(async () => {
            const r = await post<{ status: string }>(`/shifts/${s.id}/claim`);
            toast(r.status === "assigned" ? "Schicht übernommen" : "Anfrage gesendet");
          }, "")}>Schicht übernehmen</Btn>}
          {isMine && can("swap.request") && future && (
            <>
              {colleagues.length > 0 && (
                <Field label="Tausch anfragen bei">
                  <select value={swapTo} onChange={(e) => setSwapTo(e.target.value ? Number(e.target.value) : "")}>
                    <option value="">Alle Kollegen der Abteilung</option>
                    {colleagues.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
                  </select>
                </Field>
              )}
              <Btn kind="primary" onClick={() => run(() => post("/swaps", { shift_id: s.id, to_user_id: swapTo === "" ? null : swapTo }), "Tauschanfrage gesendet")}>Tausch anfragen</Btn>
            </>
          )}
        </div>
      </Modal>
    );
  }

  const ownSwappable = shift && shift.user_id === me!.id && shift.published && new Date(shift.start) > new Date() && can("swap.request");

  return (
    <Modal title={shift ? "Schicht bearbeiten" : "Schichten anlegen"} onClose={onClose}>
      <div className="stack">
        {!shift && (tpls.data ?? []).length > 0 && (
          <Field label="Vorlage verwenden" hint="Füllt Zeiten, Pause und Notiz aus">
            <select value="" onChange={(e) => {
              const t = (tpls.data ?? []).find((x) => x.id === Number(e.target.value));
              if (!t) return;
              setFrom(t.start_time.slice(0, 5)); setTo(t.end_time.slice(0, 5));
              setBreakMin(t.break_minutes); setNote(t.note);
              if (t.department_id) { setDeptId(t.department_id); setUserId(""); }
            }}>
              <option value="">— Vorlage wählen —</option>
              {(tpls.data ?? []).map((t) => <option key={t.id} value={t.id}>{t.name} ({t.start_time}–{t.end_time})</option>)}
            </select>
          </Field>
        )}
        <div className="row">
          <div className="grow">
            <Field label="Abteilung">
              <select value={deptId} onChange={(e) => { setDeptId(Number(e.target.value)); setUserId(""); }}>
                {depts.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
              </select>
            </Field>
          </div>
          <div className="grow">
            <Field label="Person">
              <select value={userId} onChange={(e) => setUserId(e.target.value ? Number(e.target.value) : "")}>
                <option value="">— Offene Schicht —</option>
                {candidates.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
              </select>
            </Field>
          </div>
        </div>

        {shift ? (
          <Field label="Datum"><input type="date" value={date} onChange={(e) => setDate(e.target.value)} /></Field>
        ) : (
          <div className="field">
            <span>Wochentage <small className="muted">(Woche ab {fmtDay(weekStart)})</small></span>
            <div className="weekday-pick" role="group" aria-label="Wochentage">
              {WEEKDAYS.map((w, i) => (
                <button type="button" key={w} className={weekdays.includes(i) ? "on" : ""} aria-pressed={weekdays.includes(i)} onClick={() => toggleDay(i)}>
                  {w}<small>{addDays(weekStart, i).getDate()}.</small>
                </button>
              ))}
            </div>
            <div className="row" style={{ marginTop: ".4rem" }}>
              <button type="button" className="link small" onClick={() => setWeekdays([0, 1, 2, 3, 4])}>Mo–Fr</button>
              <button type="button" className="link small" onClick={() => setWeekdays([0, 1, 2, 3, 4, 5])}>Mo–Sa</button>
              <button type="button" className="link small" onClick={() => setWeekdays([])}>keine</button>
            </div>
          </div>
        )}

        <div className="row">
          <div className="grow"><Field label="Von"><input type="time" step={300} value={from} onChange={(e) => setFrom(e.target.value)} /></Field></div>
          <div className="grow"><Field label="Bis"><input type="time" step={300} value={to} onChange={(e) => setTo(e.target.value)} /></Field></div>
          <div className="grow"><Field label="Pause (Min.)"><input type="number" min={0} max={240} step={5} value={breakMin} onChange={(e) => setBreakMin(Math.max(0, Number(e.target.value) || 0))} /></Field></div>
        </div>
        <p className="muted small" style={{ marginTop: ".35rem" }}>
          Dauer {durationLabel(from, to)}{to && from && to <= from ? " · endet am Folgetag" : ""} · Pause 0 = gesetzliche Mindestpause bei der Auswertung
        </p>

        {!shift && (
          <Field label="Wiederholen" hint={weekdays.length ? `Es werden ${weekdays.length * weeks} Schicht(en) als Entwurf angelegt.` : undefined}>
            <select value={weeks} onChange={(e) => setWeeks(Number(e.target.value))}>
              {[1, 2, 3, 4, 6, 8, 12].map((n) => <option key={n} value={n}>{n === 1 ? "nur diese Woche" : `${n} Wochen`}</option>)}
            </select>
          </Field>
        )}

        <Field label="Notiz"><input value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} placeholder="z. B. Frühschicht, Theke, Rehasport" /></Field>
        {userId === "" && (
          <label className="inline-check"><input type="checkbox" checked={needsApproval} onChange={(e) => setNeedsApproval(e.target.checked)} />
            <span>Übernahme erst nach meiner Freigabe</span></label>
        )}
        {claims.data && claims.data.length > 0 && (
          <div>
            <b>Anfragen</b>
            {claims.data.filter((c) => c.status === "pending").map((c) => (
              <div className="list-item" key={c.id}>
                <span>{c.user_name}</span>
                <span className="row">
                  <Btn kind="primary" onClick={() => run(() => post(`/shifts/claims/${c.id}/decide`, { approve: true }), "Zugeteilt")}>Zuteilen</Btn>
                  <Btn onClick={() => run(() => post(`/shifts/claims/${c.id}/decide`, { approve: false }), "Abgelehnt")}>Ablehnen</Btn>
                </span>
              </div>
            ))}
          </div>
        )}
        {warnings.length > 0 && (
          <div className="alert error" role="alert">
            <b>Planungshinweis</b>
            <ul>{warnings.map((w) => <li key={w}>{w}</li>)}</ul>
            <small>Mit „Trotzdem speichern“ übergehen Sie den Hinweis bewusst (wird protokolliert). Ändern Sie die Zeiten, um ihn zu beseitigen.</small>
          </div>
        )}
        {pending.length > 0 && (
          <div className="alert error" role="alert">
            <b>Planungshinweise für {pending.length} Schicht(en) – noch nicht angelegt</b>
            <ul>{pending.map((p) => <li key={p.label}>{p.label}: {p.warnings.join(" ")}</li>)}</ul>
            <small>Mit „Trotzdem anlegen“ werden diese Schichten trotzdem gespeichert (wird protokolliert).</small>
          </div>
        )}
        <ErrorBox error={error} />
        {ownSwappable && (
          <Btn onClick={() => run(() => post("/swaps", { shift_id: shift!.id }), "Tauschanfrage gesendet")}>Eigene Schicht zum Tausch anbieten</Btn>
        )}
        <div className="spread">
          {shift ? <Btn kind="danger" onClick={() => window.confirm("Schicht wirklich löschen?") ? run(() => del(`/shifts/${shift.id}`), "Gelöscht") : undefined}>Löschen</Btn> : <span />}
          {shift
            ? <Btn kind="primary" onClick={saveEdit}>{warnings.length > 0 ? "Trotzdem speichern" : "Speichern"}</Btn>
            : <Btn kind="primary" onClick={saveNew}>{pending.length > 0 ? "Trotzdem anlegen" : `Anlegen${weekdays.length ? ` (${weekdays.length * weeks})` : ""}`}</Btn>}
        </div>
      </div>
    </Modal>
  );
}
