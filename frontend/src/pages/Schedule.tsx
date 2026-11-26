import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, del, get, patch, post } from "../api";
import { useAuth, useToast } from "../context";
import { useLoad } from "../hooks";
import { useLive } from "../live";
import { addDays, fmtDay, fmtTime, fromInput, startOfWeek, toInput, weekLabel, ymd } from "../dates";
import type { Claim, Dept, Shift, ShiftTemplate, User } from "../types";
import { Badge, Btn, Card, ErrorBox, Field, Modal, Spinner } from "../ui";

export default function Schedule() {
  const { me, can } = useAuth();
  const toast = useToast();
  const manage = can("shifts.manage");
  const [monday, setMonday] = useState(startOfWeek(new Date()));
  const [dept, setDept] = useState<number | "">("");
  const [edit, setEdit] = useState<{ shift?: Shift; day?: Date } | null>(null);

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
    // Hinweis: Der Server rechnet Wochen in UTC; Schichten, die lokal vor ca. 02:00 Uhr beginnen, können abweichen.
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
        <ShiftModal shift={edit.shift} day={edit.day} depts={depts.data ?? []} users={users.data ?? []} manage={manage}
          defaultDept={dept || depts.data?.[0]?.id}
          onClose={() => setEdit(null)} onChanged={() => { setEdit(null); shifts.reload(); }} />
      )}
    </>
  );
}

function ShiftModal({ shift, day, depts, users, manage, defaultDept, onClose, onChanged }: {
  shift?: Shift; day?: Date; depts: Dept[]; users: User[]; manage: boolean; defaultDept?: number;
  onClose: () => void; onChanged: () => void;
}) {
  const { me, can } = useAuth();
  const toast = useToast();
  const base = day ?? new Date(shift?.start ?? Date.now());
  const [deptId, setDeptId] = useState<number>(shift?.department_id ?? defaultDept ?? depts[0]?.id ?? 0);
  const [userId, setUserId] = useState<number | "">(shift?.user_id ?? "");
  const [start, setStart] = useState(shift ? toInput(shift.start) : `${ymd(base)}T08:00`);
  const [end, setEnd] = useState(shift ? toInput(shift.end) : `${ymd(base)}T16:00`);
  const [note, setNote] = useState(shift?.note ?? "");
  const [breakMin, setBreakMin] = useState<number>(shift?.break_minutes ?? 0);
  const [warnings, setWarnings] = useState<string[]>([]);
  useEffect(() => setWarnings([]), [start, end, userId, deptId]); // geänderte Eingaben → Hinweise neu prüfen
  const tpls = useLoad(() => (manage && !shift ? get<ShiftTemplate[]>("/shift-templates") : Promise.resolve([] as ShiftTemplate[])), [manage, shift?.id]);
  const [needsApproval, setNeedsApproval] = useState(shift?.claim_requires_approval ?? true);
  const [error, setError] = useState<string | null>(null);
  const claims = useLoad(() => (shift && manage && shift.user_id === null ? get<Claim[]>(`/shifts/${shift.id}/claims`) : Promise.resolve([] as Claim[])), [shift?.id]);

  const candidates = users.filter((u) => u.is_active && u.department_ids.includes(deptId));

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

  const save = () => run(async () => {
    const body = { ignore_warnings: warnings.length > 0, department_id: deptId, user_id: userId === "" ? null : userId, start: fromInput(start), end: fromInput(end), note, break_minutes: breakMin, claim_requires_approval: needsApproval };
    if (shift) await patch(`/shifts/${shift.id}`, { ...body, version: shift.version });
    else await post("/shifts", body);
  }, "Gespeichert");

  // Ansicht für Schichtmitarbeiter (und Planer ohne Bearbeitungsrecht)
  if (!manage) {
    const s = shift!;
    const isMine = s.user_id === me!.id;
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
          {isMine && can("swap.request") && <Btn onClick={() => run(() => post("/swaps", { shift_id: s.id }), "Tauschanfrage gesendet")}>Tausch anfragen</Btn>}
        </div>
      </Modal>
    );
  }

  return (
    <Modal title={shift ? "Schicht bearbeiten" : "Neue Schicht"} onClose={onClose}>
      <div className="stack">
        {!shift && (tpls.data ?? []).length > 0 && (
          <Field label="Vorlage verwenden" hint="Füllt Zeiten, Pause und Notiz aus">
            <select value="" onChange={(e) => {
              const t = (tpls.data ?? []).find((x) => x.id === Number(e.target.value));
              if (!t) return;
              const d = ymd(base);
              const s = new Date(`${d}T${t.start_time}`); let en = new Date(`${d}T${t.end_time}`);
              if (en <= s) en = addDays(en, 1); // Nachtschicht über Mitternacht
              setStart(toInput(s.toISOString())); setEnd(toInput(en.toISOString()));
              setBreakMin(t.break_minutes); setNote(t.note);
              if (t.department_id) { setDeptId(t.department_id); setUserId(""); }
            }}>
              <option value="">— Vorlage wählen —</option>
              {(tpls.data ?? []).map((t) => <option key={t.id} value={t.id}>{t.name} ({t.start_time}–{t.end_time})</option>)}
            </select>
          </Field>
        )}
        <Field label="Abteilung">
          <select value={deptId} onChange={(e) => { setDeptId(Number(e.target.value)); setUserId(""); }}>
            {depts.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select>
        </Field>
        <Field label="Person" hint="Leer lassen für eine offene Schicht, die Mitarbeiter übernehmen können">
          <select value={userId} onChange={(e) => setUserId(e.target.value ? Number(e.target.value) : "")}>
            <option value="">— Offene Schicht —</option>
            {candidates.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
          </select>
        </Field>
        <div className="row">
          <div className="grow"><Field label="Beginn"><input type="datetime-local" value={start} onChange={(e) => setStart(e.target.value)} /></Field></div>
          <div className="grow"><Field label="Ende"><input type="datetime-local" value={end} onChange={(e) => setEnd(e.target.value)} /></Field></div>
        </div>
        <Field label="Pause (Minuten)" hint="Unbezahlt, wird von der Arbeitszeit abgezogen. 0 = gesetzliche Mindestpause bei Auswertung"><input type="number" min={0} max={240} step={5} value={breakMin} onChange={(e) => setBreakMin(Math.max(0, Number(e.target.value) || 0))} /></Field>
        <Field label="Notiz"><input value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} /></Field>
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
        <ErrorBox error={error} />
        <div className="spread">
          {shift ? <Btn kind="danger" onClick={() => window.confirm("Schicht wirklich löschen?") ? run(() => del(`/shifts/${shift.id}`), "Gelöscht") : undefined}>Löschen</Btn> : <span />}
          <Btn kind="primary" onClick={save}>{warnings.length > 0 ? "Trotzdem speichern" : "Speichern"}</Btn>
        </div>
      </div>
    </Modal>
  );
}
