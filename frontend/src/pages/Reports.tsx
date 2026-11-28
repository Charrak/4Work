import { Fragment, useMemo, useState } from "react";
import { get } from "../api";
import { useAuth } from "../context";
import { useLoad } from "../hooks";
import { billingPeriod, fmtPeriod, Period, PeriodPicker, periodQuery } from "../period";
import type { Dept, Report, ReportRow, Shift, TimeEntry, User } from "../types";
import { buildRow, DEVIATION_LIMIT, PauseCell, type Row } from "./Time";
import { hm } from "../dates";
import { Badge, ErrorBox, Field, Spinner } from "../ui";

const pad = (n: number) => String(n).padStart(2, "0");
const clk = (iso: string) => { const d = new Date(iso); return `${pad(d.getHours())}:${pad(d.getMinutes())}`; };
const dayL = (iso: string) => new Date(iso).toLocaleDateString("de-DE", { weekday: "short", day: "2-digit", month: "2-digit" });
const sg = (m: number) => `${m > 0 ? "+" : m < 0 ? "−" : "±"}${hm(Math.abs(m)).replace(" h", "")}`;

type DetailLine = { key: string; when: string; row: Row | null; shift: Shift | null };

/** Einzelnachweis einer Person: jede Stempelung (Datum, Von, Bis, Pause) und geplante, aber nicht gestempelte Schichten. */
function DetailTable({ lines }: { lines: DetailLine[] }) {
  if (lines.length === 0) return <p className="muted small">Keine Stempelungen oder Schichten im Zeitraum.</p>;
  return (
    <table className="detail">
      <thead><tr><th>Datum</th><th>Soll (Schicht)</th><th>Von</th><th>Bis</th><th className="num">Pause</th><th className="num">Arbeitszeit</th><th className="num">Diff</th><th>Status</th></tr></thead>
      <tbody>
        {lines.map(({ key, when, row: r, shift }) => (
          <tr key={key} className={r?.deviation && !r.approved ? "row-check" : ""}>
            <td>{dayL(when)}</td>
            <td>{shift ? `${clk(shift.start)}–${clk(shift.end)}` : <span className="muted">ungeplant</span>}</td>
            <td>{r ? <>{r.orig_clock_in && r.edited_at && clk(r.orig_clock_in) !== clk(r.clock_in) && <s className="orig">{clk(r.orig_clock_in)}</s>}{clk(r.clock_in)}</> : "—"}</td>
            <td>{r?.clock_out ? <>{r.orig_clock_out && r.edited_at && clk(r.orig_clock_out) !== clk(r.clock_out) && <s className="orig">{clk(r.orig_clock_out)}</s>}{clk(r.clock_out)}</> : r ? "läuft" : "—"}</td>
            <td className="num">{r ? <PauseCell r={r} /> : "—"}</td>
            <td className="num"><b>{r?.net != null ? hm(r.net) : "—"}</b></td>
            <td className={`num ${r?.diff != null && Math.abs(r.diff) > DEVIATION_LIMIT ? "txt-bad" : ""}`}>{r?.diff != null ? sg(r.diff) : "—"}</td>
            <td>{!r ? <Badge kind="bad">nicht gestempelt</Badge> : r.approved ? <Badge kind="ok">{r.deviation ? "Geprüft" : "Freigegeben"}</Badge> : r.deviation ? <Badge kind="bad">Prüfen</Badge> : <Badge kind="warn">Offen</Badge>}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

const nf = (n: number) => n.toLocaleString("de-DE", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const SUM_KEYS = ["contract_hours", "planned_hours", "worked_hours", "approved_hours", "overtime_hours", "labor_cost", "surcharge_cost", "gross_cost"] as const;
type SumKey = (typeof SUM_KEYS)[number];

export default function Reports() {
  const { can } = useAuth();
  const [period, setPeriod] = useState<Period>(billingPeriod(0));
  const [dept, setDept] = useState<number | "">("");
  const [selected, setSelected] = useState<Set<number> | null>(null); // null = alle
  const [showMoney, setShowMoney] = useState(true);
  const [showLaw, setShowLaw] = useState(true);
  const [onlyActive, setOnlyActive] = useState(true);
  const [showDetail, setShowDetail] = useState(false);
  const [openIds, setOpenIds] = useState<Set<number>>(new Set());
  const detailAllowed = can("time.approve");
  const { q, valid } = periodQuery(period);
  const rep = useLoad(() => (valid ? get<Report>(`/reports/summary?${q}`) : Promise.resolve(null)), [q]);
  const users = useLoad(() => (can("users.view") ? get<User[]>("/users") : Promise.resolve([] as User[])), []);
  const depts = useLoad(() => get<Dept[]>("/departments"), []);
  const wantDetail = detailAllowed && (showDetail || openIds.size > 0);
  const tooLong = valid && (new Date(period.to).getTime() - new Date(period.from).getTime()) / 86400000 > 92;
  const entries = useLoad(() => (wantDetail && valid ? get<TimeEntry[]>(`/time/entries?${q}&all=true`) : Promise.resolve([] as TimeEntry[])), [q, wantDetail]);
  const shifts = useLoad(() => (wantDetail && valid && !tooLong && can("shifts.view") ? get<Shift[]>(`/shifts?${q}`) : Promise.resolve([] as Shift[])), [q, wantDetail]);
  const userById = useMemo(() => new Map((users.data ?? []).map((u) => [u.id, u])), [users.data]);

  // Personen, die nach Abteilung/aktiv in Frage kommen (Grundlage für die Auswahl)
  const pool = (rep.data?.rows ?? []).filter((r) => {
    const u = userById.get(r.user_id);
    if (onlyActive && u && !u.is_active && r.worked_hours === 0 && r.planned_hours === 0) return false;
    if (dept !== "" && u && !u.department_ids.includes(dept)) return false;
    return true;
  });
  const rows = pool.filter((r) => selected === null || selected.has(r.user_id));
  const totals = Object.fromEntries(SUM_KEYS.map((k) => [k, rows.reduce((a, r) => a + (r[k] ?? 0), 0)])) as Record<SumKey, number>;

  // Einzelnachweis je Person aufbauen
  const details = useMemo(() => {
    const byShift = new Map((shifts.data ?? []).map((s) => [s.id, s]));
    const out = new Map<number, DetailLine[]>();
    const add = (uid: number, l: DetailLine) => { if (!out.has(uid)) out.set(uid, []); out.get(uid)!.push(l); };
    const stamped = new Set<number>();
    for (const e of entries.data ?? []) {
      const sh = e.shift_id != null ? byShift.get(e.shift_id) ?? null : null;
      if (sh) stamped.add(sh.id);
      add(e.user_id, { key: `e${e.id}`, when: e.clock_in, row: buildRow(e, sh, !!userById.get(e.user_id)?.is_minor), shift: sh });
    }
    const now = Date.now();
    for (const s of shifts.data ?? []) {
      if (s.user_id != null && !stamped.has(s.id) && s.published && new Date(s.end).getTime() < now)
        add(s.user_id, { key: `s${s.id}`, when: s.start, row: null, shift: s });
    }
    out.forEach((l) => l.sort((a, b) => a.when.localeCompare(b.when)));
    return out;
  }, [entries.data, shifts.data, userById]);
  const colCount = 6 + (showMoney ? 3 : 0) + (showLaw ? 1 : 0);
  const toggleOpen = (id: number) => setOpenIds((o) => { const n = new Set(o); if (n.has(id)) n.delete(id); else n.add(id); return n; });

  const toggle = (id: number) => {
    const next = new Set(selected ?? pool.map((r) => r.user_id));
    if (next.has(id)) next.delete(id); else next.add(id);
    setSelected(next.size === pool.length ? null : next);
  };
  const isOn = (id: number) => selected === null || selected.has(id);
  const csvHref = valid ? `/api/reports/payroll.csv?${q}` : undefined;
  const deptName = dept === "" ? "" : depts.data?.find((d) => d.id === dept)?.name ?? "";

  return (
    <>
      <div className="spread no-print">
        <h1>Berichte</h1>
        <div className="row">
          {csvHref && <a className="btn" href={csvHref}>CSV für Lohnabrechnung</a>}
          <button className="btn primary" onClick={() => window.print()} disabled={rows.length === 0}>🖨️ Drucken</button>
        </div>
      </div>

      <section className="card no-print">
        <div className="card-head"><h2>Filter</h2></div>
        <div className="stack">
          <PeriodPicker value={period} onChange={setPeriod} />
          <div className="row">
            <div className="grow">
              <Field label="Abteilung">
                <select value={dept} onChange={(e) => { setDept(e.target.value ? Number(e.target.value) : ""); setSelected(null); }}>
                  <option value="">Alle Abteilungen</option>
                  {(depts.data ?? []).map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
                </select>
              </Field>
            </div>
            <div className="grow stack" style={{ paddingTop: "1.2rem" }}>
              <label className="inline-check"><input type="checkbox" checked={showMoney} onChange={(e) => setShowMoney(e.target.checked)} /><span>Lohnkosten (€) anzeigen</span></label>
              <label className="inline-check"><input type="checkbox" checked={showLaw} onChange={(e) => setShowLaw(e.target.checked)} /><span>Arbeitszeitrecht anzeigen</span></label>
              {detailAllowed && <label className="inline-check"><input type="checkbox" checked={showDetail} onChange={(e) => setShowDetail(e.target.checked)} /><span>Einzelnachweis für alle (Datum, Von, Bis, Pause)</span></label>}
              <label className="inline-check"><input type="checkbox" checked={onlyActive} onChange={(e) => setOnlyActive(e.target.checked)} /><span>Inaktive ohne Stunden ausblenden</span></label>
            </div>
          </div>
          {pool.length > 0 && (
            <div className="field">
              <span>Mitarbeiter ({rows.length} von {pool.length} ausgewählt)</span>
              <div className="chips">
                {pool.map((r) => (
                  <button type="button" key={r.user_id} className={`chip ${isOn(r.user_id) ? "on" : ""}`} aria-pressed={isOn(r.user_id)} onClick={() => toggle(r.user_id)}>
                    {isOn(r.user_id) ? "✓ " : ""}{r.name}
                  </button>
                ))}
              </div>
              <div className="row" style={{ marginTop: ".4rem" }}>
                <button type="button" className="link small" onClick={() => setSelected(null)}>Alle</button>
                <button type="button" className="link small" onClick={() => setSelected(new Set())}>Keine</button>
              </div>
            </div>
          )}
        </div>
      </section>

      <ErrorBox error={rep.error} onRetry={rep.reload} />
      {!valid && <div className="alert error">Bitte einen gültigen Zeitraum wählen („Bis“ nach „Von“).</div>}
      {rep.loading && !rep.data && <Spinner />}
      {wantDetail && tooLong && <div className="alert error">Der Einzelnachweis mit Soll-Werten ist für höchstens 93 Tage möglich.</div>}
      {wantDetail && entries.error && <ErrorBox error={entries.error} onRetry={entries.reload} />}
      {rep.data && (
        <section className="card report-print">
          <div className="print-only timesheet-head">
            <div><b>Stundenübersicht</b><br />{fmtPeriod(period)}{deptName && ` · ${deptName}`}</div>
            <img src="/logo.png" alt="" />
          </div>
          <div className="card-head no-print"><h2>Stunden pro Mitarbeiter</h2><span className="muted">{fmtPeriod(period)}</span></div>
          {rows.length === 0 ? <p className="muted center pad">Keine Mitarbeiter ausgewählt.</p> : (
            <div className="table-wrap">
              <table>
                <thead><tr>
                  <th>Name</th><th className="num">Vertrag (h)</th><th className="num">Geplant (h)</th><th className="num">Gearbeitet (h)</th><th className="num">Freigegeben (h)</th><th className="num">Mehr/Minder (h)</th>
                  {showMoney && <><th className="num">Grundlohn (€)</th><th className="num">Zuschläge (€)</th><th className="num">Brutto (€)</th></>}
                  {showLaw && <th>Arbeitszeitrecht</th>}
                </tr></thead>
                <tbody>
                  {rows.map((r: ReportRow) => {
                    const open = detailAllowed && (showDetail || openIds.has(r.user_id));
                    return (
                    <Fragment key={r.user_id}>
                    <tr>
                      <td>{detailAllowed
                        ? <button type="button" className={`expander ${open ? "open" : ""}`} onClick={() => toggleOpen(r.user_id)} aria-expanded={open} title="Einzelnachweis ein-/ausblenden"><span aria-hidden>▸</span>{r.name}</button>
                        : r.name}</td><td className="num">{r.contract_hours ? nf(r.contract_hours) : "–"}</td><td className="num">{nf(r.planned_hours)}</td><td className="num">{nf(r.worked_hours)}</td><td className="num">{nf(r.approved_hours)}</td>
                      <td className={`num ${r.overtime_hours < 0 ? "neg" : r.overtime_hours > 0 ? "pos" : ""}`}>{nf(r.overtime_hours)}</td>
                      {showMoney && <><td className="num">{nf(r.labor_cost)}</td><td className="num">{nf(r.surcharge_cost)}</td><td className="num">{nf(r.gross_cost)}</td></>}
                      {showLaw && (
                        <td className="wrap">
                          {r.over_limit_days + r.over_limit_weeks > 0 ? <Badge kind="bad">{r.over_limit_days} Tag(e), {r.over_limit_weeks} Woche(n) über Grenze</Badge> : <Badge kind="ok">Tage/Wochen ok</Badge>}{" "}
                          <Badge kind={r.avg_over_limit ? "bad" : "muted"}>Ø 26 Wo.: {nf(r.avg_weekly_hours_26w)} h</Badge>
                          {r.is_minijob && r.minijob_months_over > 0 && <> <Badge kind="bad">Minijob-Grenze ({nf(r.minijob_limit)} €) in {r.minijob_months_over} Monat(en) überschritten</Badge></>}
                        </td>
                      )}
                    </tr>
                    {open && (
                      <tr className="detail-row"><td colSpan={colCount}>
                        {entries.loading && !entries.data ? <span className="muted small">Lädt…</span> : <DetailTable lines={details.get(r.user_id) ?? []} />}
                      </td></tr>
                    )}
                    </Fragment>
                    );
                  })}
                </tbody>
                <tfoot>
                  <tr>
                    <th>Summe ({rows.length})</th><th className="num">{nf(totals.contract_hours)}</th><th className="num">{nf(totals.planned_hours)}</th><th className="num">{nf(totals.worked_hours)}</th><th className="num">{nf(totals.approved_hours)}</th><th className="num">{nf(totals.overtime_hours)}</th>
                    {showMoney && <><th className="num">{nf(totals.labor_cost)}</th><th className="num">{nf(totals.surcharge_cost)}</th><th className="num">{nf(totals.gross_cost)}</th></>}
                    {showLaw && <th></th>}
                  </tr>
                </tfoot>
              </table>
            </div>
          )}
          <p className="muted small">Gearbeitet = abgeschlossene Stempelungen abzüglich Pause (die der Schicht, sonst die gesetzliche Mindestpause). Mehr/Minder = gearbeitet minus Soll der bereits beendeten Schichten. Vertrag = Vertragsstunden pro Woche, auf den Zeitraum umgerechnet.{showMoney && " Grundlohn = gearbeitete Stunden × gültiger Stundensatz, Zuschläge nach den Einstellungen. Brutto-Vorbereitung ohne Steuer und Sozialversicherung."} Die Stempelzeiten jeder Person im Detail stehen unter „Zeit“.</p>
        </section>
      )}
    </>
  );
}
