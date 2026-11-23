import { useEffect, useState } from "react";
import { get, put } from "../api";
import { useToast } from "../context";
import { useLoad } from "../hooks";
import { WEEKDAYS, type AvailabilityItem } from "../types";
import { Btn, Card, ErrorBox } from "../ui";

/** „Wann kann ich nicht arbeiten?“ – wiederkehrend je Wochentag. Planer sehen beim Einplanen einen Hinweis. */
export function AvailabilityCard() {
  const toast = useToast();
  const res = useLoad(() => get<AvailabilityItem[]>("/availability"), []);
  const [items, setItems] = useState<AvailabilityItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { if (res.data) setItems(res.data.map(({ weekday, start_time, end_time, note }) => ({ weekday, start_time, end_time, note }))); }, [res.data]);

  const set = (i: number, patch: Partial<AvailabilityItem>) => setItems((l) => l.map((x, j) => (j === i ? { ...x, ...patch } : x)));
  const save = async () => {
    setError(null);
    try { await put("/availability", { items }); toast("Verfügbarkeit gespeichert"); res.reload(); }
    catch (e) { setError((e as Error).message); }
  };
  return (
    <Card title="Meine Verfügbarkeit">
      <p className="muted small">Tragen Sie ein, wann Sie regelmäßig nicht arbeiten können (z. B. montags bis 12 Uhr). Die Planung erhält dann einen Hinweis – es ist eine Bitte, keine Garantie.</p>
      <ErrorBox error={res.error} onRetry={res.reload} />
      <div className="stack">
        {items.map((it, i) => (
          <div className="row" key={i} style={{ flexWrap: "wrap", alignItems: "end" }}>
            <select aria-label="Wochentag" value={it.weekday} onChange={(e) => set(i, { weekday: Number(e.target.value) })}>
              {WEEKDAYS.map((d, n) => <option key={d} value={n}>{d}</option>)}
            </select>
            <input aria-label="Von" type="time" value={it.start_time} onChange={(e) => set(i, { start_time: e.target.value })} />
            <input aria-label="Bis" type="time" value={it.end_time} onChange={(e) => set(i, { end_time: e.target.value })} />
            <input aria-label="Grund (optional)" className="grow" placeholder="Grund (optional)" maxLength={200} value={it.note} onChange={(e) => set(i, { note: e.target.value })} />
            <button className="link" onClick={() => setItems((l) => l.filter((_, j) => j !== i))}>Entfernen</button>
          </div>
        ))}
        <ErrorBox error={error} />
        <div className="row">
          <Btn onClick={() => setItems((l) => [...l, { weekday: 0, start_time: "00:00", end_time: "23:59", note: "" }])}>+ Zeitraum</Btn>
          <Btn kind="primary" onClick={save}>Speichern</Btn>
        </div>
      </div>
    </Card>
  );
}
