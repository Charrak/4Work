import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { downloadFile, get, put, uploadFile } from "../api";
import { useAuth, useToast } from "../context";
import { useLoad } from "../hooks";
import { fmtDate, fmtDateTime } from "../dates";
import { DOC_CATEGORY, ROLE_LABEL, WEEKDAYS, type Dept, type Role } from "../types";
import { Badge, Btn, Card, Empty, ErrorBox, Field, Spinner } from "../ui";

interface FileData {
  profile: { id: number; version: number; name: string; email: string; role: Role; is_active: boolean; department_ids: number[];
    created_at: string; phone: string | null; job_title: string | null; hire_date: string | null; contract_end: string | null; hr_note: string | null };
  contract: { weekly_hours: number | null; work_days: string; vacation_days: number; hourly_rate: number | null;
    is_minor: boolean; is_minijob: boolean; minijob_limit: number | null };
  wages: { id: number; hourly_rate: number; valid_from: string }[];
  year: number;
  leave: { entitlement: number; used: number; pending: number; remaining: number; vacation_days_taken: number; sick_days: number };
  time: Record<string, number | null>;
  documents: { id: number; category: string; title: string; filename: string; size: number; created_at: string }[];
  history: { id: number; action: string; detail: string; created_at: string }[];
}

const nf = (n: number | null | undefined) => (n == null ? "–" : n.toLocaleString("de-DE", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
const ACTION: Record<string, string> = {
  "user.create": "Angelegt", "user.update": "Stammdaten geändert", "user.lock": "Gesperrt", "user.unlock": "Entsperrt",
  "user.set_password": "Passwort durch Verwaltung gesetzt", "user.wage_change": "Stundensatz geändert",
  "user.wage_below_minimum": "Stundensatz unter Mindestlohn bestätigt", "personnel.update": "Personalakte geändert",
  "document.upload": "Dokument hochgeladen", "document.delete": "Dokument gelöscht", "shift.warning_ignored": "Planungshinweis übergangen",
};

export default function Personnel() {
  const { id } = useParams();
  const { can } = useAuth();
  const toast = useToast();
  const data = useLoad(() => get<FileData>(`/personnel/${id}`), [id]);
  const depts = useLoad(() => get<Dept[]>("/departments"), []);
  const [f, setF] = useState({ phone: "", job_title: "", hire_date: "", contract_end: "", hr_note: "" });
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const [cat, setCat] = useState("vertrag");
  const [title, setTitle] = useState("");

  useEffect(() => {
    const p = data.data?.profile;
    if (p) setF({ phone: p.phone ?? "", job_title: p.job_title ?? "", hire_date: p.hire_date ?? "", contract_end: p.contract_end ?? "", hr_note: p.hr_note ?? "" });
  }, [data.data]);

  if (data.loading && !data.data) return <Spinner />;
  if (!data.data) return <><Link to="/verwaltung">← Zurück</Link><ErrorBox error={data.error} onRetry={data.reload} /></>;
  const d = data.data, p = d.profile, c = d.contract;
  const deptNames = p.department_ids.map((i) => depts.data?.find((x) => x.id === i)?.name).filter(Boolean).join(", ") || "–";

  const save = async () => {
    setError(null);
    try {
      await put(`/personnel/${p.id}`, { version: p.version, phone: f.phone, job_title: f.job_title, hr_note: f.hr_note,
        hire_date: f.hire_date || null, contract_end: f.contract_end || null });
      toast("Personalakte gespeichert"); data.reload();
    } catch (e) { setError((e as Error).message); }
  };
  const upload = async () => {
    const file = fileRef.current?.files?.[0];
    if (!file) { setError("Bitte zuerst eine Datei auswählen."); return; }
    setError(null);
    try {
      await uploadFile(`/documents?${new URLSearchParams({ filename: file.name, title: title.trim(), category: cat, user_id: String(p.id) })}`, file);
      toast("Dokument hochgeladen"); setTitle(""); if (fileRef.current) fileRef.current.value = ""; data.reload();
    } catch (e) { setError((e as Error).message); }
  };

  return (
    <>
      <p><Link to="/verwaltung">← Verwaltung</Link></p>
      <h1>Personalakte: {p.name} {!p.is_active && <Badge kind="bad">gesperrt</Badge>}</h1>
      <p className="muted small">Vertraulich. Jeder Abruf dieser Akte wird protokolliert. Krankheitsgründe werden nicht gespeichert.</p>
      <ErrorBox error={error} />

      <Card title="Stammdaten">
        <div className="stack">
          <p><b>{p.email}</b> · {ROLE_LABEL[p.role]} · Abteilung: {deptNames}<br /><span className="muted small">Konto angelegt am {fmtDate(p.created_at)}</span></p>
          <div className="row">
            <div className="grow"><Field label="Telefon"><input value={f.phone} maxLength={40} onChange={(e) => setF({ ...f, phone: e.target.value })} /></Field></div>
            <div className="grow"><Field label="Funktion / Position"><input value={f.job_title} maxLength={100} placeholder="z. B. Physiotherapeutin" onChange={(e) => setF({ ...f, job_title: e.target.value })} /></Field></div>
          </div>
          <div className="row">
            <div className="grow"><Field label="Eintritt"><input type="date" value={f.hire_date} onChange={(e) => setF({ ...f, hire_date: e.target.value })} /></Field></div>
            <div className="grow"><Field label="Vertragsende (falls befristet)"><input type="date" value={f.contract_end} onChange={(e) => setF({ ...f, contract_end: e.target.value })} /></Field></div>
          </div>
          <Field label="Interne Notiz" hint="Nur für die Verwaltung sichtbar. Keine Gesundheitsdaten oder Diagnosen eintragen."><textarea rows={4} maxLength={4000} value={f.hr_note} onChange={(e) => setF({ ...f, hr_note: e.target.value })} /></Field>
          <div><Btn kind="primary" onClick={save}>Speichern</Btn></div>
        </div>
      </Card>

      <Card title="Vertrag und Lohn">
        <p>
          Vertragsstunden: <b>{c.weekly_hours ?? "nicht festgelegt"}</b>{c.weekly_hours ? " h/Woche" : ""} · Arbeitstage: <b>{c.work_days.split("").map((n) => WEEKDAYS[Number(n) - 1].slice(0, 2)).join(", ")}</b> · Urlaubsanspruch: <b>{c.vacation_days} Tage</b><br />
          Aktueller Stundensatz: <b>{c.hourly_rate != null ? `${nf(c.hourly_rate)} €` : "–"}</b>
          {c.is_minijob && <> · <Badge kind="info">Minijob{c.minijob_limit ? `, max. ${nf(c.minijob_limit)} €/Monat` : ""}</Badge></>}
          {c.is_minor && <> · <Badge kind="warn">Jugendlich</Badge></>}
        </p>
        {d.wages.length > 0 && <>
          <b>Stundensatz-Verlauf</b>
          {d.wages.map((w) => <div className="list-item" key={w.id}><span>ab {fmtDate(w.valid_from)}</span><b>{nf(w.hourly_rate)} €</b></div>)}
        </>}
        <p className="muted small">Änderungen an Vertrag und Lohn: Verwaltung → Benutzer → Bearbeiten.</p>
      </Card>

      <Card title={`Urlaub und Fehltage ${d.year}`}>
        <p>
          Anspruch <b>{d.leave.entitlement}</b> · genommen <b>{d.leave.used}</b> · beantragt <b>{d.leave.pending}</b> · Rest <b>{d.leave.remaining}</b> Tage<br />
          Krankheitstage (genehmigt): <b>{d.leave.sick_days}</b>
        </p>
      </Card>

      <Card title={`Arbeitszeit ${d.year} (bis heute)`}>
        <div className="table-wrap"><table><tbody>
          <tr><td>Gearbeitet</td><td className="num">{nf(d.time.worked_hours)} h</td><td>Geplant</td><td className="num">{nf(d.time.planned_hours)} h</td></tr>
          <tr><td>Mehr/Minder</td><td className="num">{nf(d.time.overtime_hours)} h</td><td>Ø 26 Wochen</td><td className="num">{nf(d.time.avg_weekly_hours_26w)} h/Woche</td></tr>
          <tr><td>Nacht / Sonntag / Feiertag</td><td className="num">{nf(d.time.night_hours)} / {nf(d.time.sunday_hours)} / {nf(d.time.holiday_hours)} h</td><td>Brutto (Vorbereitung)</td><td className="num">{nf(d.time.gross_cost)} €</td></tr>
          <tr><td>Tage über Höchstarbeitszeit</td><td className="num">{d.time.over_limit_days ?? 0}</td><td>Wochen über Höchstarbeitszeit</td><td className="num">{d.time.over_limit_weeks ?? 0}</td></tr>
        </tbody></table></div>
      </Card>

      <Card title="Dokumente">
        {d.documents.length === 0 && <Empty>{can("documents.manage") ? "Keine Dokumente." : "Dokumente sehen nur Nutzer mit dem Recht „Dokumente verwalten“."}</Empty>}
        {d.documents.map((x) => (
          <div className="list-item" key={x.id}>
            <span><b>{x.title || x.filename}</b><br /><span className="muted small">{DOC_CATEGORY[x.category] ?? x.category} · {fmtDate(x.created_at)}</span></span>
            <button className="link" onClick={() => downloadFile(`/documents/${x.id}/download`, x.filename).catch((e) => toast((e as Error).message, "error"))}>Herunterladen</button>
          </div>
        ))}
        {can("documents.manage") && (
          <div className="stack" style={{ marginTop: ".75rem" }}>
            <b>Dokument hinzufügen</b>
            <input ref={fileRef} type="file" accept=".pdf,.jpg,.jpeg,.png,.docx,.xlsx" aria-label="Datei" />
            <div className="row">
              <input className="grow" placeholder="Titel (optional)" value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} aria-label="Titel" />
              <select value={cat} onChange={(e) => setCat(e.target.value)} aria-label="Art">{Object.keys(DOC_CATEGORY).map((k) => <option key={k} value={k}>{DOC_CATEGORY[k]}</option>)}</select>
              <Btn onClick={upload}>Hochladen</Btn>
            </div>
          </div>
        )}
      </Card>

      <Card title="Verlauf (letzte 40 Einträge)">
        {d.history.length === 0 && <Empty>Noch keine Einträge.</Empty>}
        {d.history.map((h) => <div className="list-item" key={h.id}><span>{ACTION[h.action] ?? h.action}</span><span className="muted small">{fmtDateTime(h.created_at)}</span></div>)}
      </Card>
    </>
  );
}
