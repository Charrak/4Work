import { get, post } from "../api";
import { useAuth, useToast } from "../context";
import { useLoad } from "../hooks";
import { useLive } from "../live";
import { addDays, fmtDay, fmtTime } from "../dates";
import type { Shift, Swap } from "../types";
import { Btn, Card, Empty, ErrorBox, StatusBadge } from "../ui";

export default function Swaps() {
  const { me, can } = useAuth();
  const toast = useToast();
  const now = new Date();
  const swaps = useLoad(() => get<Swap[]>("/swaps"), []);
  const open = useLoad(() => get<Shift[]>(`/shifts?start=${encodeURIComponent(now.toISOString())}&end=${encodeURIComponent(addDays(now, 60).toISOString())}`), []);
  useLive(["shifts.changed", "swaps.changed"], () => { swaps.reload(); open.reload(); });

  const act = async (fn: () => Promise<unknown>, msg: string) => {
    try { await fn(); toast(msg); swaps.reload(); open.reload(); } catch (e) { toast((e as Error).message, "error"); }
  };
  const openShifts = (open.data ?? []).filter((s) => s.user_id === null && s.published);
  const list = swaps.data ?? [];
  // Nur Anfragen, die ich auch annehmen darf (an alle oder gezielt an mich)
  const forMe = list.filter((s) => s.status === "open" && s.from_user_id !== me!.id && (s.to_user_id === null || s.to_user_id === me!.id));
  const mine = list.filter((s) => s.from_user_id === me!.id);
  const approvals = list.filter((s) => s.status === "accepted");
  const activeSwapShifts = new Set(list.filter((s) => s.status === "open" || s.status === "accepted").map((s) => s.shift_id));
  const myShifts = (open.data ?? []).filter((s) => s.user_id === me!.id && s.published && new Date(s.start) > now && !activeSwapShifts.has(s.id));
  const when = (s: Swap) => `${fmtDay(new Date(s.shift_start))}, ${fmtTime(s.shift_start)}–${fmtTime(s.shift_end)}`;

  return (
    <>
      <h1>Tausch &amp; offene Schichten</h1>
      <ErrorBox error={swaps.error} onRetry={swaps.reload} />
      {can("shifts.manage") && (
        <Card title="Zur Freigabe">
          {approvals.length === 0 && <Empty>Keine Tauschanfragen warten auf Freigabe.</Empty>}
          {approvals.map((s) => (
            <div className="list-item" key={s.id}>
              <span><b>{when(s)}</b><br />{s.from_user_name} → {s.to_user_name}</span>
              <span className="row">
                <Btn kind="primary" onClick={() => act(() => post(`/swaps/${s.id}/decide`, { approve: true }), "Tausch genehmigt")}>Genehmigen</Btn>
                <Btn onClick={() => act(() => post(`/swaps/${s.id}/decide`, { approve: false }), "Tausch abgelehnt")}>Ablehnen</Btn>
              </span>
            </div>
          ))}
        </Card>
      )}
      <Card title="Kollegen suchen Ersatz">
        {forMe.length === 0 && <Empty>Aktuell sucht niemand Ersatz.</Empty>}
        {forMe.map((s) => (
          <div className="list-item" key={s.id}>
            <span><b>{when(s)}</b><br />{s.from_user_name}{s.to_user_id === me!.id && <> <span className="badge info">an dich</span></>}</span>
            {can("swap.request") && <Btn kind="primary" onClick={() => act(() => post(`/swaps/${s.id}/accept`), "Angenommen – wartet auf Freigabe")}>Übernehmen</Btn>}
          </div>
        ))}
      </Card>
      {can("swap.request") && (
        <Card title="Eigene Schicht zum Tausch anbieten">
          {myShifts.length === 0 && <Empty>Sie haben in den nächsten 60 Tagen keine veröffentlichten Schichten, die getauscht werden können.</Empty>}
          {myShifts.map((s) => (
            <div className="list-item" key={s.id}>
              <span><b>{fmtDay(new Date(s.start))}, {fmtTime(s.start)}–{fmtTime(s.end)}</b>{s.note && <><br /><span className="muted">{s.note}</span></>}</span>
              <Btn onClick={() => act(() => post("/swaps", { shift_id: s.id }), "Tauschanfrage an alle Kollegen gesendet")}>Tausch anfragen</Btn>
            </div>
          ))}
        </Card>
      )}
      <Card title="Meine Tauschanfragen">
        {mine.length === 0 && <Empty>Sie haben keine Tauschanfragen. Tippen Sie im Dienstplan auf Ihre Schicht, um einen Tausch anzufragen.</Empty>}
        {mine.map((s) => (
          <div className="list-item" key={s.id}>
            <span><b>{when(s)}</b><br />{s.to_user_name ? `mit ${s.to_user_name}` : "an alle"}</span>
            <span className="row"><StatusBadge status={s.status} />
              {(s.status === "open" || s.status === "accepted") && <Btn onClick={() => act(() => post(`/swaps/${s.id}/cancel`), "Storniert")}>Stornieren</Btn>}
            </span>
          </div>
        ))}
      </Card>
      <Card title="Offene Schichten">
        {openShifts.length === 0 && <Empty>Es gibt keine offenen Schichten.</Empty>}
        {openShifts.map((s) => (
          <div className="list-item" key={s.id}>
            <span><b>{fmtDay(new Date(s.start))}, {fmtTime(s.start)}–{fmtTime(s.end)}</b><br /><span className="muted">{s.note}</span></span>
            {can("swap.request") && <Btn kind="primary" onClick={() => act(async () => {
              const r = await post<{ status: string }>(`/shifts/${s.id}/claim`);
              toast(r.status === "assigned" ? "Schicht übernommen" : "Anfrage gesendet");
            }, "")}>Übernehmen</Btn>}
          </div>
        ))}
      </Card>
    </>
  );
}
