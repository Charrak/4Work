import { useEffect, useState } from "react";
import { get, post } from "./api";
import { useToast } from "./context";
import { fmtTime, hm } from "./dates";
import { useLoad } from "./hooks";
import { useLive } from "./live";
import type { TimeEntry } from "./types";
import { Btn, ErrorBox } from "./ui";

type Status = { clocked_in: boolean; on_break?: boolean; entry: TimeEntry | null };

/** Gesetzliche Mindestpause (§ 4 ArbZG) für eine Arbeitszeit in Minuten. */
const legalFor = (workMin: number) => (workMin > 540 ? 45 : workMin > 360 ? 30 : 0);

/**
 * Stempeluhr mit Pause. Ablauf:
 *  nicht eingestempelt → [Einstempeln]
 *  eingestempelt       → [Pause starten] [Ausstempeln]
 *  in Pause            → [Pause beenden] [Ausstempeln] (Ausstempeln beendet die Pause automatisch)
 */
export function ClockPanel({ onChanged }: { onChanged?: () => void }) {
  const toast = useToast();
  const [loc, setLoc] = useState(false);
  const [now, setNow] = useState(Date.now());
  const st = useLoad(() => get<Status>("/time/status"), []);
  useLive(["time.changed"], st.reload);
  useEffect(() => { const t = window.setInterval(() => setNow(Date.now()), 20000); return () => window.clearInterval(t); }, []);

  const e = st.data?.entry ?? null;
  const onBreak = !!e?.break_start;
  const runningBreak = e?.break_start ? Math.max(0, Math.round((now - new Date(e.break_start).getTime()) / 60000)) : 0;
  const pause = (e?.break_taken_min ?? 0) + runningBreak;
  const present = e ? Math.max(0, Math.round((now - new Date(e.clock_in).getTime()) / 60000)) : 0;
  const work = Math.max(0, present - pause);
  const legal = legalFor(present);
  const missing = e && !onBreak && pause < legal ? legal - pause : 0;

  const act = async (fn: () => Promise<unknown>, msg: string) => {
    try { await fn(); toast(msg); st.reload(); onChanged?.(); }
    catch (err) { toast((err as Error).message, "error"); }
  };

  const clockIn = () => act(async () => {
    let pos: { lat: number; lon: number } | null = null;
    if (loc && navigator.geolocation) {
      pos = await new Promise((res) => navigator.geolocation.getCurrentPosition(
        (p) => res({ lat: p.coords.latitude, lon: p.coords.longitude }), () => res(null), { timeout: 8000 }));
    }
    await post("/time/clock-in", { consent_location: !!pos, lat: pos?.lat, lon: pos?.lon });
  }, "Eingestempelt");

  const clockOut = () => {
    if (missing > 0 && !window.confirm(`Bisher ${pause} min Pause. Gesetzlich vorgeschrieben sind bei ${hm(present)} Anwesenheit mindestens ${legal} min – die fehlende Pause wird bei der Auswertung automatisch abgezogen. Trotzdem ausstempeln?`)) return;
    act(() => post("/time/clock-out"), "Ausgestempelt");
  };

  return (
    <section className="card clock-card">
      <div className="card-head"><h2>Stempeluhr</h2>{e && <span className={`clock-pill ${onBreak ? "brk" : "on"}`}>{onBreak ? "Pause" : "Arbeit"}</span>}</div>
      {st.error && <ErrorBox error={st.error.includes("Internet") ? "Stempeln ist nur mit Internetverbindung möglich." : st.error} onRetry={st.reload} />}
      {st.data && (
        <div className="stack">
          {e ? (
            <div className="clock-grid">
              <div><small>Eingestempelt</small><b>{fmtTime(e.clock_in)} Uhr</b></div>
              <div><small>Arbeitszeit</small><b>{hm(work)}</b></div>
              <div><small>Pause</small><b>{pause} min{onBreak ? " …" : ""}</b></div>
            </div>
          ) : <p className="clock-state"><span className="dot" aria-hidden /><span>Sie sind aktuell nicht eingestempelt.</span></p>}
          {onBreak && <p className="small">Pause läuft seit {fmtTime(e!.break_start!)} Uhr ({runningBreak} min).</p>}
          {missing > 0 && <p className="small clock-hint">⚠ Gesetzliche Pause: Bei über {present > 540 ? "9" : "6"} Stunden sind mindestens {legal} Minuten Pause vorgeschrieben – noch {missing} min offen.</p>}
          {!e && (
            <label className="inline-check"><input type="checkbox" checked={loc} onChange={(ev) => setLoc(ev.target.checked)} />
              <span className="small">Standort beim Stempeln speichern (freiwillig)</span></label>
          )}
          <div className="row">
            {!e && <Btn kind="primary" onClick={clockIn}>Einstempeln</Btn>}
            {e && !onBreak && <Btn kind="primary" onClick={() => act(() => post("/time/break-start"), "Pause gestartet")}>☕ Pause starten</Btn>}
            {e && onBreak && <Btn kind="primary" onClick={() => act(() => post("/time/break-end"), "Pause beendet")}>▶ Pause beenden</Btn>}
            {e && <Btn kind="danger" onClick={clockOut}>Ausstempeln</Btn>}
          </div>
        </div>
      )}
    </section>
  );
}
