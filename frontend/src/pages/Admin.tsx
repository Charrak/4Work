import { useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, del, get, patch, post, put } from "../api";
import { useAuth, useToast } from "../context";
import { useLoad } from "../hooks";
import { fmtDate, fmtDateTime } from "../dates";
import { ROLE_LABEL, WEEKDAYS, type Wage, type AuditEntry, type BackupInfo, type Dept, type Role, type ShiftTemplate, type SystemInfo, type User } from "../types";
import { Badge, Btn, Card, Empty, ErrorBox, Field, Modal, Spinner } from "../ui";

type Tab = "users" | "roles" | "depts" | "templates" | "settings" | "system" | "audit" | "logs" | "backups";

export default function Admin() {
  const { can } = useAuth();
  const tabs: { id: Tab; label: string; show: boolean }[] = [
    { id: "users", label: "Benutzer", show: can("users.manage") },
    { id: "roles", label: "Rollen & Rechte", show: can("roles.manage") },
    { id: "depts", label: "Abteilungen", show: can("shifts.manage") },
    { id: "templates", label: "Schichtvorlagen", show: can("shifts.manage") },
    { id: "settings", label: "Einstellungen", show: can("settings.manage") },
    { id: "system", label: "System", show: can("admin.audit") },
    { id: "audit", label: "Protokoll", show: can("admin.audit") },
    { id: "logs", label: "Fehlerprotokoll", show: can("admin.audit") },
    { id: "backups", label: "Backups", show: can("admin.backup") },
  ];
  const visible = tabs.filter((t) => t.show);
  const [tab, setTab] = useState<Tab>(visible[0]?.id ?? "users");
  return (
    <>
      <h1>Verwaltung</h1>
      <div className="tabs" role="tablist">
        {visible.map((t) => <button key={t.id} role="tab" aria-selected={tab === t.id} className={`btn ${tab === t.id ? "active" : ""}`} onClick={() => setTab(t.id)}>{t.label}</button>)}
      </div>
      {tab === "users" && <Users />}
      {tab === "roles" && <Roles />}
      {tab === "depts" && <Departments />}
      {tab === "templates" && <Templates />}
      {tab === "settings" && <SettingsTab />}
      {tab === "system" && <SystemTab />}
      {tab === "audit" && <AuditTab />}
      {tab === "logs" && <LogsTab />}
      {tab === "backups" && <Backups />}
    </>
  );
}

// ---------- Benutzer ----------
function Users() {
  const toast = useToast();
  const users = useLoad(() => get<User[]>("/users"), []);
  const depts = useLoad(() => get<Dept[]>("/departments"), []);
  const prefs = useLoad(() => get<Record<string, string>>("/admin/settings").catch(() => ({} as Record<string, string>)), []);
  const [edit, setEdit] = useState<User | "new" | null>(null);
  const act = async (fn: () => Promise<unknown>, msg: string) => {
    try { await fn(); toast(msg); users.reload(); } catch (e) { toast((e as Error).message, "error"); }
  };
  const deptNames = (u: User) => (u.department_ids.map((id) => depts.data?.find((d) => d.id === id)?.name).filter(Boolean) as string[]).join(", ");
  return (
    <Card title="Benutzer" actions={<Btn kind="primary" onClick={() => setEdit("new")}>+ Neuer Benutzer</Btn>}>
      <ErrorBox error={users.error} onRetry={users.reload} />
      {users.loading && !users.data && <Spinner />}
      <div className="table-wrap">
        <table>
          <thead><tr><th>Name</th><th>E-Mail</th><th>Rolle</th><th>Abteilung</th><th>Status</th><th></th></tr></thead>
          <tbody>
            {(users.data ?? []).map((u) => (
              <tr key={u.id}>
                <td>{u.name}</td><td>{u.email}</td><td>{ROLE_LABEL[u.role]}</td><td>{deptNames(u)}</td>
                <td>{!u.is_active ? <Badge kind="bad">Gesperrt</Badge> : u.is_locked ? <Badge kind="warn">Temporär gesperrt</Badge> : <Badge kind="ok">Aktiv</Badge>}</td>
                <td className="row">
                  <Link to={`/personal/${u.id}`}>Akte</Link>
                  <button className="link" onClick={() => setEdit(u)}>Bearbeiten</button>
                  {u.is_active
                    ? <button className="link" onClick={() => act(() => post(`/users/${u.id}/lock`), "Gesperrt")}>Sperren</button>
                    : <button className="link" onClick={() => act(() => post(`/users/${u.id}/unlock`), "Entsperrt")}>Entsperren</button>}
                  <button className="link" onClick={() => {
                    const pw = window.prompt(`Neues Passwort für ${u.name} (min. 10 Zeichen, Buchstaben und Ziffern):`);
                    if (pw) act(() => post(`/users/${u.id}/set-password`, { password: pw }), "Passwort gesetzt");
                  }}>Passwort</button>
                  <button className="link" onClick={() => {
                    if (!window.confirm(`${u.name} wirklich löschen? Personenbezogene Daten werden anonymisiert, das lässt sich nicht rückgängig machen.`)) return;
                    act(async () => {
                      try { await del(`/users/${u.id}`); }
                      catch (e) {
                        if ((e as ApiError).status === 409 && window.confirm(`${(e as Error).message}\n\nDokumente jetzt endgültig mitlöschen?`))
                          await del(`/users/${u.id}?delete_documents=true`);
                        else throw e;
                      }
                    }, "Gelöscht");
                  }}>Löschen</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {edit && <UserModal user={edit === "new" ? null : edit} depts={depts.data ?? []} defaultDays={prefs.data?.default_vacation_days} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); users.reload(); }} />}
    </Card>
  );
}

function UserModal({ user, depts, defaultDays, onClose, onSaved }: { user: User | null; depts: Dept[]; defaultDays?: string; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const [name, setName] = useState(user?.name ?? "");
  const [email, setEmail] = useState(user?.email ?? "");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>(user?.role ?? "benutzer");
  const [ids, setIds] = useState<number[]>(user?.department_ids ?? []);
  const [rate, setRate] = useState(user?.hourly_rate?.toString() ?? "");
  const [payType, setPayType] = useState<"hourly" | "monthly">(user?.monthly_salary ? "monthly" : "hourly");
  const [salary, setSalary] = useState(user?.monthly_salary?.toString() ?? "");
  const [days, setDays] = useState((user?.vacation_days ?? (Number(defaultDays) || 30)).toString());
  const [weekly, setWeekly] = useState(user?.weekly_hours?.toString() ?? "");
  const [minor, setMinor] = useState(user?.is_minor ?? false);
  const [minijob, setMinijob] = useState(user?.is_minijob ?? false);
  const [casual, setCasual] = useState(user?.is_casual ?? false);
  const [mjLimit, setMjLimit] = useState(user?.minijob_limit?.toString() ?? "");
  const [rateFrom, setRateFrom] = useState("");
  const [wages, setWages] = useState<Wage[] | null>(null);
  const [workDays, setWorkDays] = useState(user?.work_days ?? "12345");
  const [error, setError] = useState<string | null>(null);
  const toggleDay = (n: number) => setWorkDays((w) => (w.includes(String(n)) ? w.replace(String(n), "") : (w + n).split("").sort().join("")));
  const toggle = (id: number) => setIds((x) => (x.includes(id) ? x.filter((i) => i !== id) : [...x, id]));

  const save = async () => {
    setError(null);
    const num = (v: string) => (v.trim() === "" ? null : Number(v.replace(",", ".")));
    const pay = payType === "monthly"
      ? { monthly_salary: num(salary) }
      : { hourly_rate: num(rate), ...(user?.monthly_salary ? { monthly_salary: 0 } : {}) };
    if (payType === "monthly" && (!num(salary) || !num(weekly))) {
      setError("Für einen Monatslohn bitte Betrag und Vertragsstunden pro Woche angeben.");
      return;
    }
    const common = { name, email, role, department_ids: ids, ...pay, vacation_days: Number(days), work_days: workDays,
      weekly_hours: weekly === "" ? null : Number(weekly.replace(",", ".")),
      is_minor: minor, is_minijob: minijob, is_casual: casual, minijob_limit: minijob && mjLimit.trim() !== "" ? Number(mjLimit.replace(",", ".")) : null, ...(rateFrom ? { rate_valid_from: rateFrom } : {}) };
    const send = (extra: object) => user ? patch(`/users/${user.id}`, { ...common, ...extra, version: user.version }) : post("/users", { ...common, ...extra, password });
    try {
      try { await send({}); }
      catch (e) {
        const err = e as ApiError;
        if (err.status === 422 && Array.isArray((err.detail as any)?.warnings) && window.confirm(`${err.message}\n\nTrotzdem speichern?`)) await send({ ignore_warnings: true });
        else throw e;
      }
      toast("Gespeichert"); onSaved();
    } catch (e) {
      const err = e as ApiError;
      setError(err.isConflict && (err.detail as any)?.current_version ? "Der Benutzer wurde inzwischen geändert. Bitte schließen und neu öffnen." : err.message);
    }
  };
  return (
    <Modal title={user ? "Benutzer bearbeiten" : "Neuer Benutzer"} onClose={onClose}>
      <div className="stack">
        <Field label="Name"><input value={name} onChange={(e) => setName(e.target.value)} /></Field>
        <Field label="E-Mail"><input type="email" value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
        {!user && <Field label="Startpasswort" hint="Mindestens 10 Zeichen mit Buchstaben und Ziffern"><input value={password} onChange={(e) => setPassword(e.target.value)} /></Field>}
        <Field label="Rolle">
          <select value={role} onChange={(e) => setRole(e.target.value as Role)}>
            {(Object.keys(ROLE_LABEL) as Role[]).map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
          </select>
        </Field>
        <div className="field"><span>Abteilungen</span>
          {depts.map((d) => <label key={d.id} className="inline-check"><input type="checkbox" checked={ids.includes(d.id)} onChange={() => toggle(d.id)} />{d.name}</label>)}
        </div>
        <div className="row">
          <div className="grow"><Field label="Vergütung">
            <select value={payType} onChange={(e) => setPayType(e.target.value as "hourly" | "monthly")}>
              <option value="hourly">Stundenlohn</option>
              <option value="monthly">Monatslohn (Festgehalt)</option>
            </select>
          </Field></div>
          {payType === "hourly"
            ? <div className="grow"><Field label="Stundensatz (€)"><input inputMode="decimal" value={rate} onChange={(e) => setRate(e.target.value)} /></Field></div>
            : <div className="grow"><Field label="Monatslohn brutto (€)"><input inputMode="decimal" value={salary} placeholder="z. B. 2800" onChange={(e) => setSalary(e.target.value)} /></Field></div>}
        </div>
        {payType === "monthly" && (
          <p className="muted small" style={{ marginTop: "-.4rem" }}>
            {(() => {
              const s = Number(salary.replace(",", ".")), w = Number(weekly.replace(",", "."));
              return s > 0 && w > 0
                ? <>Entspricht <b>{(s / (w * 13 / 3)).toFixed(2)} € pro Stunde</b> (Monatslohn ÷ ({w} h × 4,33 Wochen)). Damit werden Zuschläge, Mindestlohn und Minijob-Grenze geprüft. Im Bericht zählt pro Abrechnungsmonat der volle Monatslohn, unabhängig von den gestempelten Stunden.</>
                : <>Bitte auch die <b>Vertragsstunden pro Woche</b> eintragen – daraus wird der Stundensatz für Zuschläge und die Mindestlohn-Prüfung berechnet.</>;
            })()}
          </p>
        )}
        <div className="row">
          <div className="grow"><Field label="Urlaubstage/Jahr"><input inputMode="numeric" value={days} onChange={(e) => setDays(e.target.value)} /></Field></div>
          <div className="grow"><Field label="Vertragsstunden/Woche" hint="Leer = nicht festgelegt"><input inputMode="decimal" value={weekly} onChange={(e) => setWeekly(e.target.value)} /></Field></div>
        </div>
        <Field label={payType === "monthly" ? "Monatslohn gilt ab" : "Stundensatz gilt ab"} hint="Leer = ab heute. Frühere Abrechnungszeiträume behalten ihren damaligen Lohn.">
          <input type="date" value={rateFrom} onChange={(e) => setRateFrom(e.target.value)} />
        </Field>
        {user && (
          <div>
            <button className="link" onClick={async () => { try { setWages(await get<Wage[]>(`/users/${user.id}/wages`)); } catch (e) { setError((e as Error).message); } }}>Lohn-Verlauf anzeigen</button>
            {wages && (wages.length === 0 ? <p className="muted small">Noch kein Verlauf.</p> : wages.map((w) => (
              <div className="list-item" key={w.id}><span>ab {fmtDate(w.valid_from)}</span>
                <b>{w.monthly_salary ? `${w.monthly_salary.toFixed(2)} € / Monat (≈ ${w.hourly_rate.toFixed(2)} €/h)` : `${w.hourly_rate.toFixed(2)} € / Stunde`}</b></div>)))}
          </div>
        )}
        <label className="inline-check"><input type="checkbox" checked={minijob} onChange={(e) => setMinijob(e.target.checked)} /><span>Minijob (Verdienstgrenze wird überwacht)</span></label>
        <label className="inline-check"><input type="checkbox" checked={casual} onChange={(e) => setCasual(e.target.checked)} /><span>Aushilfe (kein Stundenkonto: kein Soll, keine Plus-/Minusstunden; Einsatz nach Verfügbarkeit, Ankündigung mind. 4 Tage vorher)</span></label>
        {minijob && (
          <Field label="Maximaler Verdienst pro Monat (€)" hint="Leer = Firmenvorgabe aus den Einstellungen. Gilt für Bericht und Planungshinweis (ohne Zuschläge bei der Planung).">
            <input inputMode="decimal" value={mjLimit} placeholder="Firmenvorgabe" onChange={(e) => setMjLimit(e.target.value)} />
          </Field>
        )}
        <label className="inline-check"><input type="checkbox" checked={minor} onChange={(e) => setMinor(e.target.checked)} /><span>Jugendlich unter 18 (Jugendarbeitsschutz-Regeln: 8 h/Tag, 40 h/Woche, 6–20 Uhr, 12 h Ruhe)</span></label>
        <div className="field"><span>Reguläre Arbeitstage (Teilzeit)</span>
          <div className="row" style={{ flexWrap: "wrap" }}>
            {WEEKDAYS.map((n, i) => <label key={n} className="inline-check"><input type="checkbox" checked={workDays.includes(String(i + 1))} onChange={() => toggleDay(i + 1)} />{n.slice(0, 2)}</label>)}
          </div>
          <small className="muted">Nur diese Tage werden bei Urlaub und Krankheit als Arbeitstage gezählt.</small>
        </div>
        <ErrorBox error={error} />
        <Btn kind="primary" onClick={save}>Speichern</Btn>
      </div>
    </Modal>
  );
}

// ---------- Rollen ----------
function Roles() {
  const toast = useToast();
  const data = useLoad(() => get<{ permissions: Record<string, string>; roles: Record<string, string[]> }>("/roles"), []);
  const [draft, setDraft] = useState<Record<string, string[]> | null>(null);
  const roles = draft ?? data.data?.roles;
  if (data.loading && !data.data) return <Spinner />;
  if (!data.data || !roles) return <ErrorBox error={data.error} onRetry={data.reload} />;
  const toggle = (role: string, perm: string) => setDraft({ ...roles, [role]: roles[role].includes(perm) ? roles[role].filter((p) => p !== perm) : [...roles[role], perm] });
  const save = async (role: string) => {
    try { await put(`/roles/${role}`, { permissions: roles[role] }); toast("Rechte gespeichert"); setDraft(null); data.reload(); }
    catch (e) { toast((e as Error).message, "error"); }
  };
  return (
    <Card title="Rollen & Rechte">
      <p className="muted small">Der Administrator hat immer alle Rechte. Die beiden anderen Rollen sind anpassbar. Änderungen gelten sofort.</p>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Recht</th><th>Administrator</th><th>{ROLE_LABEL.mitarbeiter}</th><th>{ROLE_LABEL.benutzer}</th></tr></thead>
          <tbody>
            {Object.entries(data.data.permissions).map(([perm, label]) => (
              <tr key={perm}>
                <td>{label}</td><td>✓</td>
                {(["mitarbeiter", "benutzer"] as const).map((r) => (
                  <td key={r}><input type="checkbox" checked={roles[r].includes(perm)} onChange={() => toggle(r, perm)} aria-label={`${label} für ${ROLE_LABEL[r]}`} /></td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="row" style={{ marginTop: ".75rem" }}>
        <Btn kind="primary" onClick={() => save("mitarbeiter")}>Rechte „Mitarbeiter“ speichern</Btn>
        <Btn kind="primary" onClick={() => save("benutzer")}>Rechte „Benutzer“ speichern</Btn>
      </div>
    </Card>
  );
}

// ---------- Abteilungen ----------
function Departments() {
  const toast = useToast();
  const depts = useLoad(() => get<Dept[]>("/departments"), []);
  const [name, setName] = useState("");
  const act = async (fn: () => Promise<unknown>, msg: string) => {
    try { await fn(); toast(msg); depts.reload(); } catch (e) { toast((e as Error).message, "error"); }
  };
  return (
    <Card title="Abteilungen">
      <ErrorBox error={depts.error} onRetry={depts.reload} />
      {(depts.data ?? []).map((d) => (
        <div className="list-item" key={d.id}><span>{d.name}</span>
          <span className="row">
            <button className="link" onClick={() => { const n = window.prompt("Neuer Name", d.name); if (n) act(() => patch(`/departments/${d.id}`, { name: n }), "Umbenannt"); }}>Umbenennen</button>
            <button className="link" onClick={() => { if (window.confirm(`Abteilung „${d.name}“ löschen?`)) act(() => del(`/departments/${d.id}`), "Gelöscht"); }}>Löschen</button>
          </span>
        </div>
      ))}
      <div className="row" style={{ marginTop: ".75rem" }}>
        <input className="grow" value={name} placeholder="Neue Abteilung" onChange={(e) => setName(e.target.value)} aria-label="Name der neuen Abteilung" />
        <Btn kind="primary" onClick={async () => { if (name.trim()) { await act(() => post("/departments", { name }), "Angelegt"); setName(""); } }}>Hinzufügen</Btn>
      </div>
    </Card>
  );
}

// ---------- Schichtvorlagen ----------
function Templates() {
  const toast = useToast();
  const tpls = useLoad(() => get<ShiftTemplate[]>("/shift-templates"), []);
  const depts = useLoad(() => get<Dept[]>("/departments"), []);
  const empty = { name: "", department_id: "" as number | "", start_time: "08:00", end_time: "16:00", break_minutes: 30, note: "" };
  const [f, setF] = useState(empty);
  const act = async (fn: () => Promise<unknown>, msg: string) => {
    try { await fn(); toast(msg); tpls.reload(); } catch (e) { toast((e as Error).message, "error"); }
  };
  return (
    <Card title="Schichtvorlagen">
      <p className="muted small">Vorlagen beschleunigen die Planung: Beim Anlegen einer Schicht wählen Sie eine Vorlage, Zeiten und Pause werden übernommen.</p>
      <ErrorBox error={tpls.error} onRetry={tpls.reload} />
      {(tpls.data ?? []).length === 0 && !tpls.loading && <Empty>Noch keine Vorlagen.</Empty>}
      {(tpls.data ?? []).map((t) => (
        <div className="list-item" key={t.id}>
          <span><b>{t.name}</b> · {t.start_time}–{t.end_time} · Pause {t.break_minutes} min
            {t.department_id && <span className="muted"> · {depts.data?.find((d) => d.id === t.department_id)?.name}</span>}</span>
          <button className="link" onClick={() => { if (window.confirm(`Vorlage „${t.name}“ löschen?`)) act(() => del(`/shift-templates/${t.id}`), "Gelöscht"); }}>Löschen</button>
        </div>
      ))}
      <h3>Neue Vorlage</h3>
      <div className="stack">
        <Field label="Name"><input value={f.name} maxLength={100} placeholder="z. B. Frühdienst" onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
        <div className="row">
          <div className="grow"><Field label="Beginn"><input type="time" value={f.start_time} onChange={(e) => setF({ ...f, start_time: e.target.value })} /></Field></div>
          <div className="grow"><Field label="Ende"><input type="time" value={f.end_time} onChange={(e) => setF({ ...f, end_time: e.target.value })} /></Field></div>
          <div className="grow"><Field label="Pause (min)"><input type="number" min={0} max={240} value={f.break_minutes} onChange={(e) => setF({ ...f, break_minutes: Math.max(0, Number(e.target.value) || 0) })} /></Field></div>
        </div>
        <Field label="Abteilung" hint="Optional"><select value={f.department_id} onChange={(e) => setF({ ...f, department_id: e.target.value ? Number(e.target.value) : "" })}>
          <option value="">— alle —</option>
          {(depts.data ?? []).map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
        </select></Field>
        <Field label="Notiz"><input value={f.note} maxLength={500} onChange={(e) => setF({ ...f, note: e.target.value })} /></Field>
        <Btn kind="primary" onClick={async () => {
          if (!f.name.trim()) { toast("Bitte einen Namen eingeben", "error"); return; }
          await act(() => post("/shift-templates", { ...f, department_id: f.department_id === "" ? null : f.department_id }), "Vorlage gespeichert");
          setF(empty);
        }}>Vorlage speichern</Btn>
      </div>
    </Card>
  );
}

// ---------- Einstellungen ----------
function SettingsTab() {
  const toast = useToast();
  const s = useLoad(() => get<Record<string, string>>("/admin/settings"), []);
  const [company, setCompany] = useState<string | null>(null);
  const [vac, setVac] = useState<string | null>(null);
  const [pc, setPc] = useState<string | null>(null);
  const [mw, setMw] = useState<string | null>(null);
  const [md, setMd] = useState<string | null>(null);
  const [mwk, setMwk] = useState<string | null>(null);
  const [sn, setSn] = useState<string | null>(null);
  const [ss, setSs] = useState<string | null>(null);
  const [sh, setSh] = useState<string | null>(null);
  const [mj, setMj] = useState<string | null>(null);
  const [blk, setBlk] = useState<boolean | null>(null);
  const [psd, setPsd] = useState<string | null>(null);
  const save = async () => {
    const values: Record<string, string> = {};
    if (company !== null) values.company_name = company;
    if (vac !== null) values.default_vacation_days = vac;
    if (pc !== null) values.privacy_contact = pc;
    if (mw !== null) values.minimum_wage = mw;
    if (md !== null) values.max_daily_hours = md;
    if (mwk !== null) values.max_weekly_hours = mwk;
    if (sn !== null) values.surcharge_night_pct = sn;
    if (ss !== null) values.surcharge_sunday_pct = ss;
    if (sh !== null) values.surcharge_holiday_pct = sh;
    if (mj !== null) values.minijob_limit = mj;
    if (blk !== null) values.block_clock_over_limit = blk ? "1" : "0";
    if (psd !== null) values.period_start_day = psd;
    try { await put("/admin/settings", { values }); toast("Gespeichert"); s.reload(); } catch (e) { toast((e as Error).message, "error"); }
  };
  if (s.loading && !s.data) return <Spinner />;
  return (
    <Card title="Einstellungen">
      <ErrorBox error={s.error} onRetry={s.reload} />
      <div className="stack">
        <Field label="Firmenname"><input value={company ?? s.data?.company_name ?? ""} onChange={(e) => setCompany(e.target.value)} /></Field>
        <Field label="Standard-Urlaubstage pro Jahr" hint="Vorgabe für neue Benutzer"><input inputMode="numeric" value={vac ?? s.data?.default_vacation_days ?? "30"} onChange={(e) => setVac(e.target.value)} /></Field>
        <Field label="Datenschutz-Ansprechpartner" hint="Wird allen Mitarbeitern unter „Datenschutz“ angezeigt (Name, E-Mail, Telefon)"><input value={pc ?? s.data?.privacy_contact ?? ""} maxLength={300} onChange={(e) => setPc(e.target.value)} /></Field>
        <Field label="Abrechnungszeitraum beginnt am Tag (1–28)" hint="15 = vom 15. bis zum 14. des Folgemonats (Autoplaner und Stundenübersicht); 1 = Kalendermonat"><input inputMode="numeric" maxLength={2} value={psd ?? s.data?.period_start_day ?? "15"} onChange={(e) => setPsd(e.target.value)} /></Field>
        <Field label="Gesetzlicher Mindestlohn (€/Std.)" hint="Beim Speichern eines niedrigeren Stundenlohns erscheint ein Hinweis. Bitte bei Änderung des Mindestlohns anpassen."><input inputMode="decimal" value={mw ?? s.data?.minimum_wage ?? "13.9"} onChange={(e) => setMw(e.target.value)} /></Field>
        <div className="row">
          <div className="grow"><Field label="Höchstarbeitszeit pro Tag (h)" hint="Gesetz: 10 h"><input inputMode="decimal" value={md ?? s.data?.max_daily_hours ?? "10.0"} onChange={(e) => setMd(e.target.value)} /></Field></div>
          <div className="grow"><Field label="Höchstarbeitszeit pro Woche (h)" hint="Gesetz: 48 h"><input inputMode="decimal" value={mwk ?? s.data?.max_weekly_hours ?? "48.0"} onChange={(e) => setMwk(e.target.value)} /></Field></div>
        </div>
        <label className="inline-check"><input type="checkbox" checked={blk ?? (s.data?.block_clock_over_limit === "1")} onChange={(e) => setBlk(e.target.checked)} />
          <span>Einstempeln sperren, wenn Höchstarbeitszeit oder Ruhezeit verletzt würde (sonst nur Protokolleintrag)</span></label>
        <h3>Zuschläge (in Prozent vom Stundensatz)</h3>
        <p className="muted small">Nach Vertrag/Tarif eintragen; 0 = kein Zuschlag. Nacht = 23–6 Uhr (wird zusätzlich gezahlt). Sonntag und Feiertag: es gilt der höhere Satz.</p>
        <div className="row">
          <div className="grow"><Field label="Nacht"><input inputMode="decimal" value={sn ?? s.data?.surcharge_night_pct ?? "0.0"} onChange={(e) => setSn(e.target.value)} /></Field></div>
          <div className="grow"><Field label="Sonntag"><input inputMode="decimal" value={ss ?? s.data?.surcharge_sunday_pct ?? "0.0"} onChange={(e) => setSs(e.target.value)} /></Field></div>
          <div className="grow"><Field label="Feiertag"><input inputMode="decimal" value={sh ?? s.data?.surcharge_holiday_pct ?? "0.0"} onChange={(e) => setSh(e.target.value)} /></Field></div>
        </div>
        <Field label="Minijob-Monatsgrenze (€)" hint="Standard 603 € (Stand 2026). Ändert sich mit dem Mindestlohn – bitte prüfen."><input inputMode="decimal" value={mj ?? s.data?.minijob_limit ?? "603.0"} onChange={(e) => setMj(e.target.value)} /></Field>
        <Btn kind="primary" onClick={save}>Speichern</Btn>
      </div>
    </Card>
  );
}

// ---------- System ----------
function SystemTab() {
  const sys = useLoad(() => get<SystemInfo>("/admin/system"), []);
  if (sys.loading && !sys.data) return <Spinner />;
  if (!sys.data) return <ErrorBox error={sys.error} onRetry={sys.reload} />;
  const d = sys.data;
  const st = d.stats;
  const up = Math.floor(d.uptime_seconds / 3600);
  return (
    <>
      <Card title="Auswertung">
        <div className="kpis">
          <div className="kpi"><b>{st.users_active}</b>aktive Benutzer</div>
          <div className="kpi"><b>{st.shifts_next_7_days}</b>Schichten (7 Tage)</div>
          <div className="kpi"><b>{st.open_shifts}</b>offene Schichten</div>
          <div className="kpi"><b>{st.leave_pending}</b>Urlaubsanträge offen</div>
          <div className="kpi"><b>{st.swaps_waiting_approval}</b>Tausch zur Freigabe</div>
          <div className="kpi"><b>{st.clocked_in_now}</b>aktuell eingestempelt</div>
        </div>
      </Card>
      <Card title="System">
        <table><tbody>
          <tr><td>Version</td><td>{d.version}</td></tr><tr><td>Umgebung</td><td>{d.environment}</td></tr>
          <tr><td>Datenbank</td><td>{d.database}</td></tr><tr><td>Laufzeit</td><td>{up} Std.</td></tr>
          <tr><td>Freier Speicher</td><td>{d.disk_free_gb} GB</td></tr><tr><td>Backups</td><td>{d.backups}</td></tr>
        </tbody></table>
      </Card>
    </>
  );
}

// ---------- Protokolle ----------
function AuditTab() {
  const [filter, setFilter] = useState("");
  const a = useLoad(() => get<AuditEntry[]>(`/admin/audit?limit=200${filter ? `&action=${encodeURIComponent(filter)}` : ""}`), [filter]);
  return (
    <Card title="Aktionsprotokoll" actions={
      <select style={{ width: "auto" }} value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Filter">
        <option value="">Alle</option><option value="auth">Anmeldungen</option><option value="user">Benutzer</option>
        <option value="shift">Schichten</option><option value="leave">Urlaub</option><option value="time">Zeiten</option>
        <option value="role">Rollen</option><option value="backup">Backups</option>
      </select>}>
      <ErrorBox error={a.error} onRetry={a.reload} />
      {(a.data ?? []).length === 0 && !a.loading && <Empty>Keine Einträge.</Empty>}
      <div className="table-wrap"><table>
        <thead><tr><th>Zeit</th><th>Aktion</th><th>Details</th><th>IP</th></tr></thead>
        <tbody>{(a.data ?? []).map((r) => <tr key={r.id}><td>{fmtDateTime(r.created_at)}</td><td>{r.action}</td><td className="wrap">{r.detail}</td><td>{r.ip}</td></tr>)}</tbody>
      </table></div>
    </Card>
  );
}

function LogsTab() {
  const l = useLoad(() => get<{ lines: string[] }>("/admin/logs?lines=300"), []);
  return (
    <Card title="Fehlerprotokoll (Server)" actions={<Btn onClick={l.reload}>Aktualisieren</Btn>}>
      <ErrorBox error={l.error} onRetry={l.reload} />
      <pre style={{ overflow: "auto", maxHeight: "60vh", fontSize: ".78rem", whiteSpace: "pre-wrap" }}>{(l.data?.lines ?? []).join("\n") || "Keine Einträge."}</pre>
    </Card>
  );
}

// ---------- Backups ----------
function Backups() {
  const toast = useToast();
  const b = useLoad(() => get<BackupInfo[]>("/admin/backups"), []);
  const create = async () => { try { await post("/admin/backups"); toast("Backup erstellt"); b.reload(); } catch (e) { toast((e as Error).message, "error"); } };
  return (
    <Card title="Backups" actions={<Btn kind="primary" onClick={create}>Backup jetzt erstellen</Btn>}>
      <p className="muted small">Automatische Backups laufen täglich auf dem Server. Wiederherstellen erfolgt bewusst per Skript auf dem Server (siehe Wartungsanleitung), damit nicht versehentlich Daten überschrieben werden.</p>
      <ErrorBox error={b.error} onRetry={b.reload} />
      {(b.data ?? []).length === 0 && !b.loading && <Empty>Noch keine Backups.</Empty>}
      {(b.data ?? []).map((x) => (
        <div className="list-item" key={x.name}>
          <span>{x.name}<br /><span className="muted small">{fmtDateTime(x.created_at)} · {(x.size_bytes / 1e6).toFixed(2)} MB</span></span>
          <a className="btn small" href={`/api/admin/backups/${encodeURIComponent(x.name)}`}>Herunterladen</a>
        </div>
      ))}
    </Card>
  );
}
