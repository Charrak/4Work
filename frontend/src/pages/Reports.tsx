import { useState } from "react";
import { get } from "../api";
import { useLoad } from "../hooks";
import { ymd } from "../dates";
import type { Report } from "../types";
import { Badge, Card, ErrorBox, Field, Spinner } from "../ui";

const nf = (n: number) => n.toLocaleString("de-DE", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export default function Reports() {
  const now = new Date();
  const [from, setFrom] = useState(ymd(new Date(now.getFullYear(), now.getMonth(), 1)));
  const [to, setTo] = useState(ymd(new Date(now.getFullYear(), now.getMonth() + 1, 0)));
  // Zeitraum in lokaler Zeit: von 00:00 des Starttags bis 00:00 des Tages nach dem Ende
  const s = new Date(from + "T00:00:00");
  const e = new Date(to + "T00:00:00"); e.setDate(e.getDate() + 1);
  const q = `start=${encodeURIComponent(s.toISOString())}&end=${encodeURIComponent(e.toISOString())}`;
  const valid = e > s;
  const rep = useLoad(() => (valid ? get<Report>(`/reports/summary?${q}`) : Promise.resolve(null)), [q]);

  return (
    <>
      <h1>Berichte</h1>
      <Card title="Zeitraum" actions={valid && <a className="btn" href={`/api/reports/payroll.csv?${q}`}>CSV für Lohnabrechnung</a>}>
        <div className="row">
          <div className="grow"><Field label="Von"><input type="date" value={from} onChange={(ev) => setFrom(ev.target.value)} /></Field></div>
          <div className="grow"><Field label="Bis"><input type="date" value={to} onChange={(ev) => setTo(ev.target.value)} /></Field></div>
        </div>
      </Card>
      <ErrorBox error={rep.error} onRetry={rep.reload} />
      {rep.loading && !rep.data && <Spinner />}
      {rep.data && (
        <Card title="Stunden pro Mitarbeiter">
          <div className="table-wrap">
            <table>
              <thead><tr><th>Name</th><th className="num">Vertrag (h)</th><th className="num">Geplant (h)</th><th className="num">Gearbeitet (h)</th><th className="num">Freigegeben (h)</th><th className="num">Mehr/Minder (h)</th><th className="num">Grundlohn (€)</th><th className="num">Zuschläge (€)</th><th className="num">Brutto (€)</th><th>Arbeitszeitrecht</th></tr></thead>
              <tbody>
                {rep.data.rows.map((r) => (
                  <tr key={r.user_id}><td>{r.name}</td><td className="num">{r.contract_hours ? nf(r.contract_hours) : "–"}</td><td className="num">{nf(r.planned_hours)}</td><td className="num">{nf(r.worked_hours)}</td><td className="num">{nf(r.approved_hours)}</td><td className="num">{nf(r.overtime_hours)}</td><td className="num">{nf(r.labor_cost)}</td><td className="num">{nf(r.surcharge_cost)}</td><td className="num">{nf(r.gross_cost)}</td>
                    <td>
                      {r.over_limit_days + r.over_limit_weeks > 0 ? <Badge kind="bad">{r.over_limit_days} Tag(e), {r.over_limit_weeks} Woche(n) über Grenze</Badge> : <Badge kind="ok">Tage/Wochen ok</Badge>}{" "}
                      <Badge kind={r.avg_over_limit ? "bad" : "muted"}>Ø 26 Wo.: {nf(r.avg_weekly_hours_26w)} h</Badge>
                      {r.is_minijob && r.minijob_months_over > 0 && <> <Badge kind="bad">Minijob-Grenze ({nf(r.minijob_limit)} €) in {r.minijob_months_over} Monat(en) überschritten</Badge></>}
                    </td></tr>
                ))}
                <tr><th>Summe</th><th className="num">{nf(rep.data.totals.contract_hours)}</th><th className="num">{nf(rep.data.totals.planned_hours)}</th><th className="num">{nf(rep.data.totals.worked_hours)}</th><th className="num">{nf(rep.data.totals.approved_hours)}</th><th className="num">{nf(rep.data.totals.overtime_hours)}</th><th className="num">{nf(rep.data.totals.labor_cost)}</th><th className="num">{nf(rep.data.totals.surcharge_cost)}</th><th className="num">{nf(rep.data.totals.gross_cost)}</th><th></th></tr>
              </tbody>
            </table>
          </div>
          <p className="muted small">Grundlohn = gearbeitete Stunden × der am jeweiligen Tag gültige Stundensatz; Zuschläge nach den Einstellungen (Nacht/Sonntag/Feiertag). Das ist eine Brutto-Vorbereitung – Lohnsteuer und Sozialversicherung werden hier nicht berechnet. Gearbeitet zählt nur abgeschlossene Stempelungen, abzüglich Pause (die der Schicht, sonst die gesetzliche Mindestpause). Mehr/Minder = gearbeitet minus Soll der bereits beendeten Schichten. Vertrag = Vertragsstunden pro Woche, auf den Zeitraum umgerechnet. „Höchstarbeitszeit“ zählt Tage und Wochen, in denen die Grenzwerte aus den Einstellungen überschritten wurden (Standard 10 h pro Tag, 48 h pro Woche).</p>
        </Card>
      )}
    </>
  );
}
