import { useEffect, useState } from "react";
import { get, put } from "../api";
import { useAuth, useToast } from "../context";
import { useLoad } from "../hooks";
import { ymd } from "../dates";
import { WEEKDAYS, type AvailabilityItem, type User } from "../types";
import { Btn, Card, ErrorBox, Field, Spinner } from "../ui";

const blank = (): AvailabilityItem => ({ weekday: 0, on_date: null, start_time: "00:00", end_time: "23:59", note: "" });

/**
 * „Wann kann ich nicht arbeiten?“ – wöchentlich wiederkehrend oder nur an einem einzelnen Tag.
 * Ohne userId: eigene Angaben. Mit userId (nur Planer/Administratoren): Angaben dieser Person.
 * Planer erhalten beim Einplanen einen Hinweis (keine Sperre).
 */
export function AvailabilityCard({ userId, title }: { userId?: number; title?: string }) {
  const toast = useToast();
  const q = userId ? `?user_id=${userId}` : "";
  const res = useLoad(() => get<AvailabilityItem[]>(`/availability${q}`), [userId]);
  const [items, setItems] = useState<AvailabilityItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const today = ymd(new Date());
  useEffect(() => {
    if (!res.data) return;
    // Vergangene Einzeltage werden nicht mehr angezeigt und beim nächsten Speichern entfernt
    setItems(res.data.filter((x) => !x.on_date || x.on_date >= today)
      .map(({ weekday, on_date, start_time, end_time, note }) => ({ weekday, on_date, start_time, end_time, note })));
  }, [res.data]);

  const set = (i: number, patch: Partial<AvailabilityItem>) => setItems((l) => l.map((x, j) => (j === i ? { ...x, ...patch } : x)));
  const save = async () => {
    setError(null);
    try {
      await put(`/availability${q}`, { items: items.map((x) => (x.on_date ? { ...x, weekday: null } : { ...x, on_date: null })) });
      toast("Verfügbarkeit gespeichert"); res.reload();
    } catch (e) { setError((e as Error).message); }
  };
  const own = !userId;
  return (
    <Card title={title ?? (own ? "Meine Verfügbarkeit" : "Verfügbarkeit")}>
      <p className="muted small">
        {own ? "Tragen Sie ein, wann Sie nicht arbeiten können – jede Woche (z. B. montags bis 12 Uhr) oder nur an einem einzelnen Tag. "
          : "Zeiten, in denen diese Person nicht eingeplant werden kann. Änderungen werden protokolliert. "}
        Die Planung erhält einen Hinweis – es ist eine Bitte, keine Sperre.
      </p>
      <ErrorBox error={res.error} onRetry={res.reload} />
      {res.loading && !res.data && <Spinner />}
      <div className="stack">
        {items.map((it, i) => (
          <div className="row" key={i} style={{ flexWrap: "wrap", alignItems: "end" }}>
            <select aria-label="Art" style={{ width: "auto" }} value={it.on_date ? "day" : "week"}
              onChange={(e) => set(i, e.target.value === "day" ? { on_date: today, weekday: null } : { on_date: null, weekday: 0 })}>
              <option value="week">Jede Woche</option>
              <option value="day">Einzelner Tag</option>
            </select>
            {it.on_date
              ? <input aria-label="Datum" type="date" min={today} value={it.on_date} onChange={(e) => set(i, { on_date: e.target.value })} />
              : <select aria-label="Wochentag" value={it.weekday ?? 0} onChange={(e) => set(i, { weekday: Number(e.target.value) })}>
                  {WEEKDAYS.map((d, n) => <option key={d} value={n}>{d}</option>)}
                </select>}
            <input aria-label="Von" type="time" value={it.start_time} onChange={(e) => set(i, { start_time: e.target.value })} />
            <input aria-label="Bis" type="time" value={it.end_time} onChange={(e) => set(i, { end_time: e.target.value })} />
            <input aria-label="Grund (optional)" className="grow" placeholder="Grund (optional)" maxLength={200} value={it.note} onChange={(e) => set(i, { note: e.target.value })} />
            <button className="link" onClick={() => setItems((l) => l.filter((_, j) => j !== i))}>Entfernen</button>
          </div>
        ))}
        <ErrorBox error={error} />
        <div className="row">
          <Btn onClick={() => setItems((l) => [...l, blank()])}>+ Zeitraum</Btn>
          <Btn kind="primary" onClick={save}>Speichern</Btn>
        </div>
      </div>
    </Card>
  );
}

/** Seite für Planer/Administratoren: Verfügbarkeit einer ausgewählten Person pflegen. */
export default function AvailabilityManage() {
  const { can } = useAuth();
  const users = useLoad(() => (can("users.view") ? get<User[]>("/users") : Promise.resolve([] as User[])), []);
  const [uid, setUid] = useState<number | "">("");
  const list = (users.data ?? []).filter((u) => u.is_active);
  return (
    <>
      <h1>Verfügbarkeiten</h1>
      <Card>
        <Field label="Person">
          <select value={uid} onChange={(e) => setUid(e.target.value ? Number(e.target.value) : "")}>
            <option value="">— Person wählen —</option>
            {list.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
          </select>
        </Field>
        <ErrorBox error={users.error} onRetry={users.reload} />
        {!users.loading && list.length === 0 && <p className="muted small">Keine Personen sichtbar. Für diese Seite wird zusätzlich das Recht „Benutzerliste ansehen“ benötigt.</p>}
      </Card>
      {uid !== "" && <AvailabilityCard key={uid} userId={uid} title={`Verfügbarkeit: ${list.find((u) => u.id === uid)?.name ?? ""}`} />}
    </>
  );
}
