import { useState } from "react";
import { get, patch, post } from "../api";
import { useAuth, useToast } from "../context";
import { useLoad } from "../hooks";
import { useLive } from "../live";
import { addDays, fmtDateTime, fromInput, hm, toInput } from "../dates";
import type { TimeEntry } from "../types";
import { Badge, Btn, Card, Empty, ErrorBox, Field, Modal } from "../ui";

export default function Time() {
  const { can } = useAuth();
  const toast = useToast();
  const [all, setAll] = useState(false);
  const [editing, setEditing] = useState<TimeEntry | null>(null);
  const [loc, setLoc] = useState(false);
  const now = new Date();
  const range = `start=${encodeURIComponent(addDays(now, -31).toISOString())}&end=${encodeURIComponent(addDays(now, 1).toISOString())}`;
  const st = useLoad(() => (can("time.clock") ? get<{ clocked_in: boolean; entry: TimeEntry | null }>("/time/status") : Promise.resolve(null)), []);
  const entries = useLoad(() => get<TimeEntry[]>(`/time/entries?${range}${all ? "&all=true" : ""}`), [all]);
  const refresh = () => { st.reload(); entries.reload(); };
  useLive(["time.changed"], refresh);

  const toggle = async () => {
    try {
      if (st.data?.clocked_in) { await post("/time/clock-out"); toast("Ausgestempelt"); }
      else {
        let pos: { lat: number; lon: number } | null = null;
        if (loc && navigator.geolocation) {
          pos = await new Promise((res) => navigator.geolocation.getCurrentPosition(
            (p) => res({ lat: p.coords.latitude, lon: p.coords.longitude }), () => res(null), { timeout: 8000 }));
        }
        await post("/time/clock-in", { consent_location: !!pos, lat: pos?.lat, lon: pos?.lon });
        toast("Eingestempelt");
      }
      refresh();
    } catch (e) { toast((e as Error).message, "error"); }
  };

  const total = (entries.data ?? []).reduce((a, e) => a + (e.minutes ?? 0), 0);

  return (
    <>
      <h1>Zeiterfassung</h1>
      {can("time.clock") && (
        <Card title="Stempeluhr">
          <div className="stack">
            <p>{st.data?.clocked_in ? <>Eingestempelt seit <b>{fmtDateTime(st.data.entry!.clock_in)}</b></> : "Nicht eingestempelt."}</p>
            {st.error && <ErrorBox error="Stempeln ist nur mit Internetverbindung möglich." onRetry={st.reload} />}
            {!st.data?.clocked_in && <label className="inline-check"><input type="checkbox" checked={loc} onChange={(e) => setLoc(e.target.checked)} /><span className="small">Standort speichern (freiwillig)</span></label>}
            <Btn kind={st.data?.clocked_in ? "danger" : "primary"} onClick={toggle} disabled={!st.data}>{st.data?.clocked_in ? "Ausstempeln" : "Einstempeln"}</Btn>
          </div>
        </Card>
      )}
      <Card title={`Letzte 30 Tage – ${hm(total)}`} actions={can("time.approve") && (
        <label className="inline-check"><input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} /><span>Alle Mitarbeiter</span></label>)}>
        <ErrorBox error={entries.error} onRetry={entries.reload} />
        {(entries.data ?? []).length === 0 && !entries.loading && <Empty>Keine Einträge.</Empty>}
        <div className="table-wrap">
          <table>
            <thead><tr>{all && <th>Name</th>}<th>Beginn</th><th>Ende</th><th className="num">Dauer</th><th>Status</th>{can("time.approve") && <th></th>}</tr></thead>
            <tbody>
              {(entries.data ?? []).map((e) => (
                <tr key={e.id}>
                  {all && <td>{e.user_name}</td>}
                  <td>{fmtDateTime(e.clock_in)}</td><td>{e.clock_out ? fmtDateTime(e.clock_out) : "—"}</td>
                  <td className="num">{hm(e.minutes)}</td>
                  <td>{e.approved ? <Badge kind="ok">Freigegeben</Badge> : <Badge kind="warn">Offen</Badge>}</td>
                  {can("time.approve") && <td><button className="link" onClick={() => setEditing(e)}>Prüfen</button></td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      {editing && <EntryModal entry={editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); refresh(); }} />}
    </>
  );
}

function EntryModal({ entry, onClose, onSaved }: { entry: TimeEntry; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const [cin, setCin] = useState(toInput(entry.clock_in));
  const [cout, setCout] = useState(entry.clock_out ? toInput(entry.clock_out) : "");
  const [note, setNote] = useState(entry.note);
  const [error, setError] = useState<string | null>(null);
  const save = async (approved: boolean) => {
    setError(null);
    try {
      await patch(`/time/entries/${entry.id}`, { clock_in: fromInput(cin), clock_out: cout ? fromInput(cout) : null, note, approved });
      toast(approved ? "Freigegeben" : "Gespeichert"); onSaved();
    } catch (e) { setError((e as Error).message); }
  };
  return (
    <Modal title={`Zeiteintrag – ${entry.user_name}`} onClose={onClose}>
      <div className="stack">
        <Field label="Beginn"><input type="datetime-local" value={cin} onChange={(e) => setCin(e.target.value)} /></Field>
        <Field label="Ende"><input type="datetime-local" value={cout} onChange={(e) => setCout(e.target.value)} /></Field>
        <Field label="Notiz"><input value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} /></Field>
        <p className="muted small">Änderungen werden im Protokoll festgehalten.</p>
        <ErrorBox error={error} />
        <div className="spread"><Btn onClick={() => save(false)}>Speichern</Btn><Btn kind="primary" onClick={() => save(true)}>Speichern &amp; freigeben</Btn></div>
      </div>
    </Modal>
  );
}
