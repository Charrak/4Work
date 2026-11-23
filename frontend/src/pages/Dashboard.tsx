import { Link } from "react-router-dom";
import { get, post } from "../api";
import { useAuth, useToast } from "../context";
import { useLoad } from "../hooks";
import { useLive } from "../live";
import { addDays, fmtDate, fmtTime, hm } from "../dates";
import type { Leave, Shift, Swap, TimeEntry } from "../types";
import { Btn, Card, Empty, ErrorBox } from "../ui";
import { useState } from "react";

function ClockCard() {
  const toast = useToast();
  const [loc, setLoc] = useState(false);
  const st = useLoad(() => get<{ clocked_in: boolean; entry: TimeEntry | null }>("/time/status"), []);
  useLive(["time.changed"], st.reload);

  const getPosition = (): Promise<{ lat: number; lon: number } | null> =>
    new Promise((resolve) => {
      if (!loc || !navigator.geolocation) return resolve(null);
      navigator.geolocation.getCurrentPosition(
        (p) => resolve({ lat: p.coords.latitude, lon: p.coords.longitude }), () => resolve(null), { timeout: 8000 });
    });

  const toggle = async () => {
    try {
      if (st.data?.clocked_in) {
        await post("/time/clock-out");
        toast("Ausgestempelt");
      } else {
        const pos = await getPosition();
        await post("/time/clock-in", { consent_location: !!pos, lat: pos?.lat, lon: pos?.lon });
        toast("Eingestempelt");
      }
      st.reload();
    } catch (e) { toast((e as Error).message, "error"); }
  };

  return (
    <Card title="Stempeluhr">
      {st.error && <ErrorBox error={st.error.includes("Internet") ? "Stempeln ist nur mit Internetverbindung möglich." : st.error} onRetry={st.reload} />}
      {st.data && (
        <div className="stack">
          <p>{st.data.clocked_in
            ? <>Eingestempelt seit <b>{fmtTime(st.data.entry!.clock_in)}</b> Uhr.</>
            : "Sie sind aktuell nicht eingestempelt."}</p>
          {!st.data.clocked_in && (
            <label className="inline-check"><input type="checkbox" checked={loc} onChange={(e) => setLoc(e.target.checked)} />
              <span className="small">Standort beim Stempeln speichern (freiwillig)</span></label>
          )}
          <Btn kind={st.data.clocked_in ? "danger" : "primary"} onClick={toggle}>{st.data.clocked_in ? "Ausstempeln" : "Einstempeln"}</Btn>
        </div>
      )}
    </Card>
  );
}

export default function Dashboard() {
  const { me, can } = useAuth();
  const now = new Date();
  const range = `start=${encodeURIComponent(now.toISOString())}&end=${encodeURIComponent(addDays(now, 14).toISOString())}`;
  const shifts = useLoad(() => (can("shifts.view") ? get<Shift[]>(`/shifts?${range}`) : Promise.resolve([] as Shift[])), []);
  const swaps = useLoad(() => (can("shifts.view") ? get<Swap[]>("/swaps") : Promise.resolve([] as Swap[])), []);
  const leave = useLoad(() => (can("leave.approve") ? get<Leave[]>("/leave?all=true&status=pending") : Promise.resolve([] as Leave[])), []);
  useLive(["shifts.changed", "swaps.changed", "leave.changed"], () => { shifts.reload(); swaps.reload(); leave.reload(); });

  const mine = (shifts.data ?? []).filter((s) => s.user_id === me!.id).slice(0, 5);
  const openShifts = (shifts.data ?? []).filter((s) => s.user_id === null && s.published).length;
  const toApprove = (swaps.data ?? []).filter((s) => s.status === "accepted").length;
  const forMe = (swaps.data ?? []).filter((s) => s.status === "open" && s.from_user_id !== me!.id).length;

  return (
    <>
      <h1>Hallo {me!.name.split(" ")[0]}</h1>
      <div className="kpis" style={{ marginBottom: "1rem" }}>
        {can("shifts.view") && <Link className="kpi" to="/tausch"><b>{openShifts}</b>offene Schichten</Link>}
        {can("shifts.view") && <Link className="kpi" to="/tausch"><b>{forMe}</b>Tauschanfragen für dich</Link>}
        {can("shifts.manage") && <Link className="kpi" to="/tausch"><b>{toApprove}</b>Tausch zur Freigabe</Link>}
        {can("leave.approve") && <Link className="kpi" to="/urlaub"><b>{leave.data?.length ?? 0}</b>Urlaubsanträge offen</Link>}
      </div>
      {can("time.clock") && <ClockCard />}
      {can("shifts.view") && (
        <Card title="Meine nächsten Schichten" actions={<Link to="/plan">Zum Dienstplan</Link>}>
          <ErrorBox error={shifts.error} onRetry={shifts.reload} />
          {mine.length === 0 && !shifts.loading && <Empty>In den nächsten 14 Tagen sind keine Schichten für Sie veröffentlicht.</Empty>}
          {mine.map((s) => (
            <div className="list-item" key={s.id}>
              <span><b>{fmtDate(s.start)}</b> {fmtTime(s.start)}–{fmtTime(s.end)}</span>
              <span className="muted">{s.note}</span>
            </div>
          ))}
        </Card>
      )}
    </>
  );
}
