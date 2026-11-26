import { useMemo, useState } from "react";
import { ApiError, del, downloadFile, get, mutateOrQueue, patch, post, put } from "../api";
import { useAuth, useToast } from "../context";
import { useLoad } from "../hooks";
import { useLive } from "../live";
import { addDays, fmtDateTime, fromInput, toInput, ymd } from "../dates";
import { PRIORITY_LABEL, WEEKDAYS, type Dept, type Task, type TaskStats, type TaskTemplate, type User } from "../types";
import { Badge, Btn, Card, Empty, ErrorBox, Field, Modal, Spinner } from "../ui";

type Tab = "mine" | "all" | "templates" | "stats";
const pct = (x: number | null) => (x == null ? "–" : `${Math.round(x * 100)} %`);

export default function Tasks() {
  const { can } = useAuth();
  const manage = can("tasks.manage");
  const tabs: { id: Tab; label: string; show: boolean }[] = [
    { id: "mine", label: "Meine Aufgaben", show: true },
    { id: "all", label: "Alle Aufgaben", show: manage },
    { id: "templates", label: "Wiederkehrend", show: manage },
    { id: "stats", label: "Statistik", show: can("tasks.stats") || can("tasks.stats_people") },
  ];
  const visible = tabs.filter((t) => t.show);
  const [tab, setTab] = useState<Tab>("mine");
  return (
    <>
      <h1>Aufgaben</h1>
      {visible.length > 1 && (
        <div className="tabs" role="tablist">
          {visible.map((t) => (
            <button key={t.id} role="tab" aria-selected={tab === t.id} className={`btn ${tab === t.id ? "active" : ""}`} onClick={() => setTab(t.id)}>{t.label}</button>
          ))}
        </div>
      )}
      {(tab === "mine" || tab === "all") && <TaskList scope={tab} />}
      {tab === "templates" && <Templates />}
      {tab === "stats" && <Stats />}
    </>
  );
}

// ---------- Liste ----------
function TaskList({ scope }: { scope: "mine" | "all" }) {
  const { me, can } = useAuth();
  const toast = useToast();
  const [status, setStatus] = useState<"open" | "done">("open");
  const [edit, setEdit] = useState<Task | "new" | null>(null);
  const res = useLoad(() => get<Task[]>(`/tasks?scope=${scope}&status=${status}`), [scope, status]);
  useLive(["tasks.changed"], () => res.reload());
  const rows = res.data ?? [];
  const canCreate = can("tasks.create") || can("tasks.manage");

  const replace = (t: Task) => res.setData((res.data ?? []).map((x) => (x.id === t.id ? t : x)));
  const act = async (label: string, path: string, body: unknown, optimistic?: (t: Task) => Task, t?: Task) => {
    try {
      const r = await mutateOrQueue<Task>(label, path, "POST", body);
      if (r.queued) {
        toast("Gemerkt – wird gesendet, sobald Sie online sind");
        if (t && optimistic) replace(optimistic(t));
      } else if (r.data) replace(r.data);
      if (!r.queued) res.reload();
    } catch (e) { toast((e as Error).message, "error"); }
  };

  return (
    <>
      <div className="row" style={{ marginBottom: ".75rem" }}>
        <select aria-label="Anzeige" style={{ width: "auto" }} value={status} onChange={(e) => setStatus(e.target.value as "open" | "done")}>
          <option value="open">Offen</option>
          <option value="done">Erledigt (letzte 14 Tage)</option>
        </select>
        {canCreate && <Btn kind="primary" onClick={() => setEdit("new")}>+ Aufgabe</Btn>}
      </div>
      <ErrorBox error={res.error} onRetry={res.reload} />
      {res.loading && !res.data && <Spinner />}
      {res.data && rows.length === 0 && <Card><Empty>{status === "open" ? "Keine offenen Aufgaben. 🎉" : "Keine erledigten Aufgaben im Zeitraum."}</Empty></Card>}
      {rows.map((t) => (
        <TaskCard key={t.id} t={t} meId={me!.id} canManage={can("tasks.manage")}
          onToggle={(i, done) => act(`Punkt „${t.items[i].text}“`, `/tasks/${t.id}/items/${i}`, { done },
            (x) => ({ ...x, items: x.items.map((it, j) => (j === i ? { ...it, done } : it)) }), t)}
          onComplete={(comment) => act(`Aufgabe „${t.title}“ abhaken`, `/tasks/${t.id}/complete`, { comment },
            (x) => ({ ...x, status: "done", completed_by_name: me!.name, completion_comment: comment }), t)}
          onReopen={() => act(`Aufgabe „${t.title}“ öffnen`, `/tasks/${t.id}/reopen`, {})}
          onEdit={() => setEdit(t)}
          onDelete={async () => {
            if (!window.confirm(`Aufgabe „${t.title}“ löschen?`)) return;
            try { await del(`/tasks/${t.id}`); toast("Aufgabe gelöscht"); res.reload(); } catch (e) { toast((e as Error).message, "error"); }
          }} />
      ))}
      {edit && <TaskModal task={edit === "new" ? null : edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); res.reload(); }} />}
    </>
  );
}

function TaskCard({ t, meId, canManage, onToggle, onComplete, onReopen, onEdit, onDelete }: {
  t: Task; meId: number; canManage: boolean; onToggle: (i: number, done: boolean) => void; onComplete: (comment: string) => void;
  onReopen: () => void; onEdit: () => void; onDelete: () => void;
}) {
  const [comment, setComment] = useState("");
  const done = t.status === "done";
  const openItems = t.items.filter((i) => !i.done).length;
  const canDelete = canManage || t.can_edit;
  return (
    <Card>
      <div className="spread">
        <h3 style={{ margin: 0, textDecoration: done ? "line-through" : "none" }}>{t.title}</h3>
        <span className="row">
          {t.priority === 2 && !done && <Badge kind="bad">hoch</Badge>}
          {t.overdue && <Badge kind="bad">überfällig</Badge>}
          {done && <Badge kind="ok">erledigt</Badge>}
        </span>
      </div>
      <p className="muted small" style={{ margin: ".25rem 0" }}>
        {t.due_at ? `Fällig: ${fmtDateTime(t.due_at)}` : "Ohne Fälligkeit"}
        {" · "}{t.assignee_name ?? t.department_name ?? "Alle"}
        {t.created_by_name && ` · von ${t.created_by_name}`}
        {t.template_id && " · wiederkehrend"}
      </p>
      {t.description && <p style={{ whiteSpace: "pre-wrap" }}>{t.description}</p>}
      {t.items.length > 0 && (
        <div className="stack" style={{ margin: ".5rem 0" }}>
          {t.items.map((it, i) => (
            <label key={i} className="row" style={{ cursor: t.can_complete && !done ? "pointer" : "default" }}>
              <input type="checkbox" checked={it.done} disabled={!t.can_complete || done} onChange={(e) => onToggle(i, e.target.checked)} />
              <span style={{ textDecoration: it.done ? "line-through" : "none" }}>{it.text}</span>
              {it.done && it.by_name && <span className="muted small">({it.by_name})</span>}
            </label>
          ))}
        </div>
      )}
      {done ? (
        <p className="muted small">
          Erledigt von {t.completed_by_name ?? "?"}{t.completed_at && ` am ${fmtDateTime(t.completed_at)}`}
          {t.completion_comment && ` – „${t.completion_comment}“`}
        </p>
      ) : t.can_complete && (
        <div className="row" style={{ marginTop: ".5rem", alignItems: "end" }}>
          {(t.require_comment || comment) && (
            <input className="grow" aria-label="Kommentar" maxLength={500} placeholder={t.require_comment ? "Kommentar (erforderlich)" : "Kommentar (optional)"} value={comment} onChange={(e) => setComment(e.target.value)} />
          )}
          {!t.require_comment && !comment && <button className="link" onClick={() => setComment(" ")}>Kommentar</button>}
          <Btn kind="primary" disabled={openItems > 0 || (t.require_comment && !comment.trim())} onClick={() => onComplete(comment.trim())}>
            {openItems > 0 ? `Noch ${openItems} offen` : "Erledigt ✓"}
          </Btn>
        </div>
      )}
      <div className="row" style={{ marginTop: ".5rem" }}>
        {done && (canManage || t.completed_by === meId) && <button className="link" onClick={onReopen}>Wieder öffnen</button>}
        {t.can_edit && <button className="link" onClick={onEdit}>Bearbeiten</button>}
        {canDelete && !done && <button className="link" onClick={onDelete}>Löschen</button>}
        {canManage && done && <button className="link" onClick={onDelete}>Löschen</button>}
      </div>
    </Card>
  );
}

// ---------- Aufgabe anlegen/bearbeiten ----------
function useTargets() {
  const { can } = useAuth();
  const depts = useLoad(() => get<Dept[]>("/departments"), []);
  const users = useLoad(() => (can("users.view") ? get<User[]>("/users") : Promise.resolve([] as User[])), []);
  return { depts: depts.data ?? [], users: (users.data ?? []).filter((u) => u.is_active), canPickUser: can("users.view") };
}

function TaskModal({ task, onClose, onSaved }: { task: Task | null; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const { depts, users, canPickUser } = useTargets();
  const [f, setF] = useState({
    title: task?.title ?? "", description: task?.description ?? "", department_id: task?.department_id ?? ("" as number | ""),
    assignee_id: task?.assignee_id ?? ("" as number | ""), due: task?.due_at ? toInput(task.due_at) : "", priority: task?.priority ?? 1,
    items: (task?.items ?? []).map((i) => i.text).join("\n"), require_comment: task?.require_comment ?? false,
  });
  const [error, setError] = useState<string | null>(null);
  const save = async () => {
    setError(null);
    const body = {
      title: f.title, description: f.description, department_id: f.department_id === "" ? null : f.department_id,
      assignee_id: f.assignee_id === "" ? null : f.assignee_id, due_at: f.due ? fromInput(f.due) : null, priority: f.priority,
      items: f.items.split("\n").map((x) => x.trim()).filter(Boolean), require_comment: f.require_comment,
    };
    try {
      if (task) await patch(`/tasks/${task.id}`, { ...body, version: task.version }); else await post("/tasks", body);
      toast("Aufgabe gespeichert"); onSaved();
    } catch (e) { setError(e instanceof ApiError && e.status === 409 ? "Die Aufgabe wurde zwischenzeitlich geändert. Bitte schließen und neu öffnen." : (e as Error).message); }
  };
  return (
    <Modal title={task ? "Aufgabe bearbeiten" : "Neue Aufgabe"} onClose={onClose}>
      <div className="stack">
        <Field label="Titel"><input value={f.title} maxLength={200} onChange={(e) => setF({ ...f, title: e.target.value })} autoFocus /></Field>
        <Field label="Beschreibung (optional)"><textarea rows={3} maxLength={2000} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
        <Field label="Zuweisen an Abteilung" hint="Alle Personen dieser Abteilung sehen die Aufgabe; wer zuerst abhakt, erledigt sie. Leer = alle.">
          <select value={f.department_id} onChange={(e) => setF({ ...f, department_id: e.target.value ? Number(e.target.value) : "" })}>
            <option value="">— alle —</option>
            {depts.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select>
        </Field>
        {canPickUser
          ? <Field label="…oder an eine bestimmte Person" hint="Eine Person hat Vorrang vor der Abteilung.">
              <select value={f.assignee_id} onChange={(e) => setF({ ...f, assignee_id: e.target.value ? Number(e.target.value) : "" })}>
                <option value="">— niemand Bestimmtes —</option>
                {users.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
              </select>
            </Field>
          : <p className="muted small">Zuweisung an einzelne Personen braucht das Recht „Benutzerliste ansehen“.</p>}
        <div className="row" style={{ alignItems: "end" }}>
          <Field label="Fällig bis (optional)"><input type="datetime-local" value={f.due} onChange={(e) => setF({ ...f, due: e.target.value })} /></Field>
          <Field label="Priorität">
            <select value={f.priority} onChange={(e) => setF({ ...f, priority: Number(e.target.value) })}>
              {PRIORITY_LABEL.map((l, i) => <option key={l} value={i}>{l}</option>)}
            </select>
          </Field>
        </div>
        <Field label="Checkliste (ein Punkt pro Zeile, optional)"><textarea rows={4} value={f.items} onChange={(e) => setF({ ...f, items: e.target.value })} /></Field>
        <label className="row"><input type="checkbox" checked={f.require_comment} onChange={(e) => setF({ ...f, require_comment: e.target.checked })} /> Beim Abhaken ist ein Kommentar Pflicht</label>
        <ErrorBox error={error} />
        <div className="row"><Btn kind="primary" onClick={save}>Speichern</Btn><Btn onClick={onClose}>Abbrechen</Btn></div>
      </div>
    </Modal>
  );
}

// ---------- Wiederkehrende Aufgaben (Checklisten-Vorlagen) ----------
function Templates() {
  const toast = useToast();
  const res = useLoad(() => get<TaskTemplate[]>("/task-templates"), []);
  const { depts } = useTargets();
  const [edit, setEdit] = useState<TaskTemplate | "new" | null>(null);
  const days = (wd: string) => (wd.length === 7 ? "täglich" : [...wd].map((c) => WEEKDAYS[Number(c)].slice(0, 2)).join(", "));
  return (
    <>
      <p className="muted small">Aus diesen Vorlagen entstehen die Aufgaben automatisch an den gewählten Wochentagen – zum Beispiel „Studio öffnen“ oder „Liegen desinfizieren“.</p>
      <div className="row" style={{ marginBottom: ".75rem" }}><Btn kind="primary" onClick={() => setEdit("new")}>+ Wiederkehrende Aufgabe</Btn></div>
      <ErrorBox error={res.error} onRetry={res.reload} />
      <Card>
        {res.data && res.data.length === 0 && <Empty>Noch keine wiederkehrenden Aufgaben.</Empty>}
        {(res.data ?? []).map((t) => (
          <div className="list-item" key={t.id}>
            <span>
              <b>{t.title}</b> {!t.active && <Badge kind="muted">pausiert</Badge>}<br />
              <span className="muted small">{days(t.weekdays)} bis {t.due_time} Uhr · {depts.find((d) => d.id === t.department_id)?.name ?? "alle"}{t.items.length ? ` · ${t.items.length} Punkte` : ""}</span>
            </span>
            <span className="row">
              <button className="link" onClick={() => setEdit(t)}>Bearbeiten</button>
              <button className="link" onClick={async () => {
                if (!window.confirm(`„${t.title}“ löschen? Bereits erzeugte Aufgaben bleiben erhalten.`)) return;
                try { await del(`/task-templates/${t.id}`); toast("Gelöscht"); res.reload(); } catch (e) { toast((e as Error).message, "error"); }
              }}>Löschen</button>
            </span>
          </div>
        ))}
      </Card>
      {edit && <TemplateModal tpl={edit === "new" ? null : edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); res.reload(); }} />}
    </>
  );
}

function TemplateModal({ tpl, onClose, onSaved }: { tpl: TaskTemplate | null; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const { depts, users, canPickUser } = useTargets();
  const [f, setF] = useState({
    title: tpl?.title ?? "", description: tpl?.description ?? "", department_id: tpl?.department_id ?? ("" as number | ""),
    assignee_id: tpl?.assignee_id ?? ("" as number | ""), weekdays: tpl?.weekdays ?? "01234", due_time: tpl?.due_time ?? "18:00",
    items: (tpl?.items ?? []).join("\n"), require_comment: tpl?.require_comment ?? false, priority: tpl?.priority ?? 1, active: tpl?.active ?? true,
  });
  const [error, setError] = useState<string | null>(null);
  const toggleDay = (n: number) => {
    const s = new Set([...f.weekdays]);
    if (s.has(String(n))) s.delete(String(n)); else s.add(String(n));
    setF({ ...f, weekdays: [...s].sort().join("") });
  };
  const save = async () => {
    setError(null);
    if (!f.weekdays) { setError("Mindestens einen Wochentag wählen"); return; }
    const body = { ...f, department_id: f.department_id === "" ? null : f.department_id, assignee_id: f.assignee_id === "" ? null : f.assignee_id,
      items: f.items.split("\n").map((x) => x.trim()).filter(Boolean) };
    try { if (tpl) await put(`/task-templates/${tpl.id}`, body); else await post("/task-templates", body); toast("Gespeichert"); onSaved(); }
    catch (e) { setError((e as Error).message); }
  };
  return (
    <Modal title={tpl ? "Wiederkehrende Aufgabe bearbeiten" : "Neue wiederkehrende Aufgabe"} onClose={onClose}>
      <div className="stack">
        <Field label="Titel"><input value={f.title} maxLength={200} onChange={(e) => setF({ ...f, title: e.target.value })} autoFocus /></Field>
        <Field label="Beschreibung (optional)"><textarea rows={2} maxLength={2000} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
        <Field label="An welchen Tagen?">
          <div className="row">
            {WEEKDAYS.map((d, n) => (
              <label key={d} className="row" style={{ gap: ".25rem" }}><input type="checkbox" checked={f.weekdays.includes(String(n))} onChange={() => toggleDay(n)} />{d.slice(0, 2)}</label>
            ))}
          </div>
        </Field>
        <Field label="Erledigt bis (Uhrzeit)"><input type="time" value={f.due_time} onChange={(e) => setF({ ...f, due_time: e.target.value })} /></Field>
        <Field label="Abteilung">
          <select value={f.department_id} onChange={(e) => setF({ ...f, department_id: e.target.value ? Number(e.target.value) : "" })}>
            <option value="">— alle —</option>
            {depts.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select>
        </Field>
        {canPickUser && (
          <Field label="Feste Person (optional)">
            <select value={f.assignee_id} onChange={(e) => setF({ ...f, assignee_id: e.target.value ? Number(e.target.value) : "" })}>
              <option value="">— niemand Bestimmtes —</option>
              {users.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
            </select>
          </Field>
        )}
        <Field label="Checkliste (ein Punkt pro Zeile)"><textarea rows={4} value={f.items} onChange={(e) => setF({ ...f, items: e.target.value })} /></Field>
        <Field label="Priorität">
          <select value={f.priority} onChange={(e) => setF({ ...f, priority: Number(e.target.value) })}>
            {PRIORITY_LABEL.map((l, i) => <option key={l} value={i}>{l}</option>)}
          </select>
        </Field>
        <label className="row"><input type="checkbox" checked={f.require_comment} onChange={(e) => setF({ ...f, require_comment: e.target.checked })} /> Kommentar beim Abhaken ist Pflicht</label>
        <label className="row"><input type="checkbox" checked={f.active} onChange={(e) => setF({ ...f, active: e.target.checked })} /> Aktiv (erzeugt Aufgaben)</label>
        <ErrorBox error={error} />
        <div className="row"><Btn kind="primary" onClick={save}>Speichern</Btn><Btn onClick={onClose}>Abbrechen</Btn></div>
      </div>
    </Modal>
  );
}

// ---------- Statistik ----------
function Stats() {
  const { can } = useAuth();
  const toast = useToast();
  const today = new Date();
  const [start, setStart] = useState(ymd(addDays(today, -29)));
  const [end, setEnd] = useState(ymd(today));
  const [group, setGroup] = useState<"department" | "task" | "person">(can("tasks.stats") ? "department" : "person");
  const q = `start=${start}&end=${end}&group_by=${group}`;
  const res = useLoad(() => get<TaskStats>(`/tasks/stats?${q}`), [q]);
  useLive(["tasks.changed"], () => res.reload());
  const s = res.data;
  const maxDay = useMemo(() => Math.max(1, ...(s?.days ?? []).map((d) => d.total)), [s]);
  const label = group === "department" ? "Abteilung" : group === "task" ? "Aufgabe" : "Person";
  return (
    <>
      <Card>
        <div className="row" style={{ alignItems: "end" }}>
          <Field label="Von"><input type="date" value={start} max={end} onChange={(e) => setStart(e.target.value)} /></Field>
          <Field label="Bis"><input type="date" value={end} min={start} onChange={(e) => setEnd(e.target.value)} /></Field>
          <Field label="Gruppieren nach">
            <select value={group} onChange={(e) => setGroup(e.target.value as typeof group)}>
              {can("tasks.stats") && <option value="department">Abteilung</option>}
              {can("tasks.stats") && <option value="task">Aufgabe</option>}
              {can("tasks.stats_people") && <option value="person">Person</option>}
            </select>
          </Field>
          <Btn onClick={async () => { try { await downloadFile(`/tasks/stats.csv?${q}`, "aufgaben-statistik.csv"); } catch (e) { toast((e as Error).message, "error"); } }}>CSV</Btn>
        </div>
        {group === "person" && <p className="muted small" style={{ marginTop: ".5rem" }}>Auswertung pro Person ist eine Leistungs- und Verhaltenskontrolle. Der Abruf wird protokolliert; die Beschäftigten sind darüber zu informieren.</p>}
      </Card>
      <ErrorBox error={res.error} onRetry={res.reload} />
      {res.loading && !s && <Spinner />}
      {s && (
        <>
          <div className="kpis" style={{ marginBottom: "1rem" }}>
            <div className="kpi"><b>{s.totals.total}</b>Aufgaben</div>
            <div className="kpi"><b>{pct(s.totals.done_rate)}</b>erledigt</div>
            <div className="kpi"><b>{pct(s.totals.on_time_rate)}</b>davon pünktlich</div>
            <div className="kpi"><b>{s.totals.overdue}</b>überfällig offen</div>
          </div>
          <Card title={`Nach ${label}`}>
            {s.groups.length === 0 ? <Empty>Keine Aufgaben im Zeitraum.</Empty> : (
              <div className="table-wrap">
                <table>
                  <thead><tr><th>{label}</th><th>Aufgaben</th><th>Erledigt</th><th>Pünktlich</th><th>Verspätet</th><th>Überfällig</th><th>Offen</th><th>Ø Verspätung</th></tr></thead>
                  <tbody>
                    {s.groups.map((g) => (
                      <tr key={g.key}>
                        <td>{g.key}</td><td>{g.total}</td><td>{g.done} ({pct(g.done_rate)})</td><td>{g.on_time}</td><td>{g.late}</td>
                        <td>{g.overdue > 0 ? <Badge kind="bad">{g.overdue}</Badge> : 0}</td><td>{g.open}</td><td>{g.late ? `${g.avg_delay_min} Min.` : "–"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
          {s.days.length > 0 && (
            <Card title="Verlauf pro Tag (erledigt / gesamt)">
              <div role="img" aria-label="Aufgaben pro Tag" style={{ display: "flex", alignItems: "flex-end", gap: 2, height: 110, overflowX: "auto" }}>
                {s.days.map((d) => (
                  <div key={d.date} title={`${d.date}: ${d.done} von ${d.total} erledigt`} style={{ flex: "1 0 8px", minWidth: 8, height: `${(d.total / maxDay) * 100}%`, background: "var(--border)", borderRadius: 3, position: "relative" }}>
                    <div style={{ position: "absolute", bottom: 0, left: 0, right: 0, height: `${d.total ? (d.done / d.total) * 100 : 0}%`, background: "var(--primary)", borderRadius: 3 }} />
                  </div>
                ))}
              </div>
              <p className="muted small">Dunkel = erledigt, hell = offen. Zeitraum {s.start} bis {s.end}.</p>
            </Card>
          )}
        </>
      )}
    </>
  );
}
