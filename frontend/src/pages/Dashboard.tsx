import { Link } from "react-router-dom";
import { get, post } from "../api";
import { useAuth, useToast } from "../context";
import { useLoad } from "../hooks";
import { useLive } from "../live";
import { addDays, fmtDate, fmtTime, hm } from "../dates";
import type { Leave, Shift, Swap, TimeEntry } from "../types";
import { billingPeriod, periodQuery } from "../period";
import { buildRow } from "./Time";
import { Card, Empty, ErrorBox } from "../ui";
import { ClockPanel } from "../clock";

function greeting(d: Date): string {
  const h = d.getHours();
  return h < 11 ? "Guten Morgen" : h < 18 ? "Hallo" : "Guten Abend";
}

export default function Dashboard() {
  const { me, can } = useAuth();
  const now = new Date();
  const range = `start=${encodeURIComponent(now.toISOString())}&end=${encodeURIComponent(addDays(now, 14).toISOString())}`;
  const shifts = useLoad(() => (can("shifts.view") ? get<Shift[]>(`/shifts?${range}`) : Promise.resolve([] as Shift[])), []);
  const swaps = useLoad(() => (can("shifts.view") ? get<Swap[]>("/swaps") : Promise.resolve([] as Swap[])), []);
  const leave = useLoad(() => (can("leave.approve") ? get<Leave[]>("/leave?all=true&status=pending") : Promise.resolve([] as Leave[])), []);
  const bq = periodQuery(billingPeriod(0)).q;
  const approver = can("time.approve");
  const tEntries = useLoad(() => (approver ? get<TimeEntry[]>(`/time/entries?${bq}&all=true`) : Promise.resolve([] as TimeEntry[])), []);
  const tShifts = useLoad(() => (approver && can("shifts.view") ? get<Shift[]>(`/shifts?${bq}`) : Promise.resolve([] as Shift[])), []);
  useLive(["shifts.changed", "swaps.changed", "leave.changed"], () => { shifts.reload(); swaps.reload(); leave.reload(); });
  useLive(["time.changed"], () => { tEntries.reload(); });

  const mine = (shifts.data ?? []).filter((s) => s.user_id === me!.id).slice(0, 5);
  const openShifts = (shifts.data ?? []).filter((s) => s.user_id === null && s.published).length;
  const toApprove = (swaps.data ?? []).filter((s) => s.status === "accepted").length;
  const forMe = (swaps.data ?? []).filter((s) => s.status === "open" && s.from_user_id !== me!.id && (s.to_user_id === null || s.to_user_id === me!.id)).length;
  const shiftMap = new Map((tShifts.data ?? []).map((s) => [s.id, s]));
  const toCheck = (tEntries.data ?? []).filter((e) => !e.approved && e.clock_out &&
    buildRow(e, e.shift_id != null ? shiftMap.get(e.shift_id) ?? null : null, false).deviation).length;

  return (
    <>
      <div className="hello">
        <h1>{greeting(now)}, {me!.name.split(" ")[0]}</h1>
        <p>{now.toLocaleDateString("de-DE", { weekday: "long", day: "numeric", month: "long", year: "numeric" })}</p>
      </div>
      <div className="kpis">
        {can("shifts.view") && <Link className="kpi" to="/tausch"><span className="kpi-ico" aria-hidden>📌</span><b>{openShifts}</b>offene Schichten</Link>}
        {can("shifts.view") && <Link className="kpi" to="/tausch"><span className="kpi-ico" aria-hidden>🔁</span><b>{forMe}</b>Tauschanfragen für dich</Link>}
        {can("shifts.manage") && <Link className="kpi" to="/tausch"><span className="kpi-ico" aria-hidden>✅</span><b>{toApprove}</b>Tausch zur Freigabe</Link>}
        {approver && <Link className={`kpi ${toCheck ? "kpi-alert" : ""}`} to="/zeit?filter=pruefen"><span className="kpi-ico" aria-hidden>⚠️</span><b>{toCheck}</b>Zeit-Abweichungen prüfen</Link>}
        {can("leave.approve") && <Link className="kpi" to="/urlaub"><span className="kpi-ico" aria-hidden>🌴</span><b>{leave.data?.length ?? 0}</b>Urlaubsanträge offen</Link>}
      </div>
      {can("time.clock") && <ClockPanel />}
      {can("shifts.view") && (
        <Card title="Meine nächsten Schichten" actions={<Link to="/plan">Zum Dienstplan</Link>}>
          <ErrorBox error={shifts.error} onRetry={shifts.reload} />
          {mine.length === 0 && !shifts.loading && <Empty>In den nächsten 14 Tagen sind keine Schichten für Sie veröffentlicht.</Empty>}
          {mine.map((s) => (
            <div className="list-item" key={s.id}>
              <span className="row">
                <span className="shift-date" aria-hidden>
                  <b>{new Date(s.start).getDate()}</b>
                  <small>{new Date(s.start).toLocaleDateString("de-DE", { weekday: "short" }).replace(".", "")}</small>
                </span>
                <span><b>{fmtDate(s.start)}</b><br /><span className="muted small">{fmtTime(s.start)}–{fmtTime(s.end)} Uhr</span></span>
              </span>
              <span className="muted">{s.note}</span>
            </div>
          ))}
        </Card>
      )}
    </>
  );
}
