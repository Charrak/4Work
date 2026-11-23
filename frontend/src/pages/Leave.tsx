import { useState } from "react";
import { get, mutateOrQueue, post } from "../api";
import { useAuth, useToast } from "../context";
import { useLoad } from "../hooks";
import { useLive } from "../live";
import { addDays, fmtDate, ymd } from "../dates";
import { KIND_LABEL, type Absence, type Leave as LeaveT, type LeaveBalance } from "../types";
import { Btn, Card, Empty, ErrorBox, Field, StatusBadge } from "../ui";

export default function Leave() {
  const { can } = useAuth();
  const toast = useToast();
  const year = new Date().getFullYear();
  const bal = useLoad(() => get<LeaveBalance>(`/leave/balance?year=${year}`), [year]);
  const mine = useLoad(() => get<LeaveT[]>("/leave"), []);
  const pending = useLoad(() => (can("leave.approve") ? get<LeaveT[]>("/leave?all=true&status=pending") : Promise.resolve([] as LeaveT[])), []);
  const abs = useLoad(() => (can("shifts.view") ? get<Absence[]>(`/leave/absences?start=${ymd(new Date())}&end=${ymd(addDays(new Date(), 60))}`) : Promise.resolve([] as Absence[])), []);
  useLive(["leave.changed"], () => { bal.reload(); mine.reload(); pending.reload(); abs.reload(); });
  const today = ymd(new Date());
  const [start, setStart] = useState(today);
  const [end, setEnd] = useState(today);
  const [note, setNote] = useState("");
  const [kind, setKind] = useState("vacation");
  const [error, setError] = useState<string | null>(null);

  const reloadAll = () => { bal.reload(); mine.reload(); pending.reload(); };
  const request = async () => {
    setError(null);
    try {
      const r = await mutateOrQueue(KIND_LABEL[kind], "/leave", "POST", { start_date: start, end_date: end, kind, note });
      toast(r.queued ? "Offline: Antrag wird später gesendet" : kind === "sick" ? "Krankmeldung gesendet" : "Antrag gesendet", r.queued ? "info" : "ok");
      setNote(""); reloadAll();
    } catch (e) { setError((e as Error).message); }
  };
  const decide = async (id: number, approve: boolean) => {
    const comment = approve ? "" : (window.prompt("Begründung (optional)") ?? "");
    try { await post(`/leave/${id}/decide`, { approve, comment }); toast(approve ? "Genehmigt" : "Abgelehnt"); reloadAll(); }
    catch (e) { toast((e as Error).message, "error"); }
  };
  const cancel = async (id: number) => {
    try { await post(`/leave/${id}/cancel`); toast("Storniert"); reloadAll(); } catch (e) { toast((e as Error).message, "error"); }
  };

  return (
    <>
      <h1>Urlaub</h1>
      {bal.data && can("leave.request") && (
        <div className="kpis" style={{ marginBottom: "1rem" }}>
          <div className="kpi"><b>{bal.data.entitlement}</b>Tage {year}</div>
          <div className="kpi"><b>{bal.data.used}</b>genommen/genehmigt</div>
          <div className="kpi"><b>{bal.data.pending}</b>beantragt</div>
          <div className="kpi"><b>{bal.data.remaining}</b>verbleibend</div>
        </div>
      )}
      {can("leave.approve") && (
        <Card title="Anträge zur Entscheidung">
          {(pending.data ?? []).length === 0 && <Empty>Keine offenen Anträge.</Empty>}
          {(pending.data ?? []).map((l) => (
            <div className="list-item" key={l.id}>
              <span><b>{l.user_name}</b> <span className="badge info">{KIND_LABEL[l.kind] ?? l.kind}</span><br />{fmtDate(l.start_date)} – {fmtDate(l.end_date)} ({l.days} Werktage){l.note && <><br /><span className="muted">{l.note}</span></>}</span>
              <span className="row">
                <Btn kind="primary" onClick={() => decide(l.id, true)}>Genehmigen</Btn>
                <Btn onClick={() => decide(l.id, false)}>Ablehnen</Btn>
              </span>
            </div>
          ))}
        </Card>
      )}
      {can("leave.request") && (
        <Card title="Urlaub oder Abwesenheit melden">
          <div className="stack">
            <Field label="Art"><select value={kind} onChange={(e) => setKind(e.target.value)}>
              {["vacation", "sick", "special", "wish"].map((k) => <option key={k} value={k}>{KIND_LABEL[k]}</option>)}
            </select></Field>
            {kind === "sick" && <p className="muted small">Krankmeldungen können auch rückwirkend erfasst werden. Bitte keine Diagnose eintragen; die Krankschreibung (AU) laden Sie unter „Dokumente“ hoch.</p>}
            <div className="row">
              <div className="grow"><Field label="Von"><input type="date" value={start} min={kind === "sick" ? undefined : today} onChange={(e) => { setStart(e.target.value); if (e.target.value > end) setEnd(e.target.value); }} /></Field></div>
              <div className="grow"><Field label="Bis"><input type="date" value={end} min={start} onChange={(e) => setEnd(e.target.value)} /></Field></div>
            </div>
            <Field label="Notiz (optional)"><input value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} /></Field>
            <ErrorBox error={error} />
            <Btn kind="primary" onClick={request}>{kind === "sick" ? "Krankmeldung senden" : "Antrag senden"}</Btn>
          </div>
        </Card>
      )}
      {can("shifts.view") && (
        <Card title="Wer ist abwesend? (nächste 60 Tage)">
          <ErrorBox error={abs.error} onRetry={abs.reload} />
          {(abs.data ?? []).length === 0 && !abs.loading && <Empty>Keine genehmigten Abwesenheiten.</Empty>}
          {(abs.data ?? []).map((a, i) => (
            <div className="list-item" key={i}><span><b>{a.user_name}</b></span>
              <span className="muted">{fmtDate(a.start_date)} – {fmtDate(a.end_date)} · {KIND_LABEL[a.kind] ?? a.kind}</span></div>
          ))}
        </Card>
      )}
      <Card title="Meine Anträge">
        <ErrorBox error={mine.error} onRetry={mine.reload} />
        {(mine.data ?? []).length === 0 && !mine.loading && <Empty>Noch keine Anträge.</Empty>}
        {(mine.data ?? []).map((l) => (
          <div className="list-item" key={l.id}>
            <span><b>{fmtDate(l.start_date)} – {fmtDate(l.end_date)}</b> ({l.days} Tage) <span className="badge">{KIND_LABEL[l.kind] ?? l.kind}</span>
              {l.decision_comment && <><br /><span className="muted">{l.decision_comment}</span></>}</span>
            <span className="row"><StatusBadge status={l.status} />
              {(l.status === "pending" || l.status === "approved") && new Date(l.start_date) > new Date() && <Btn onClick={() => cancel(l.id)}>Stornieren</Btn>}
            </span>
          </div>
        ))}
      </Card>
    </>
  );
}
