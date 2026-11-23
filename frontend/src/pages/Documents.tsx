import { useRef, useState } from "react";
import { del, downloadFile, get, uploadFile } from "../api";
import { useAuth, useToast } from "../context";
import { useLoad } from "../hooks";
import { fmtDate } from "../dates";
import { DOC_CATEGORY, type DocItem, type User } from "../types";
import { Btn, Card, Empty, ErrorBox, Field } from "../ui";

const size = (b: number) => (b > 1048576 ? `${(b / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1024))} KB`);

export default function Documents() {
  const { can } = useAuth();
  const toast = useToast();
  const manage = can("documents.manage");
  const docs = useLoad(() => get<DocItem[]>("/documents"), []);
  const users = useLoad(() => (manage ? get<User[]>("/users") : Promise.resolve([] as User[])), [manage]);
  const fileRef = useRef<HTMLInputElement>(null);
  const [category, setCategory] = useState(manage ? "vertrag" : "attest");
  const [target, setTarget] = useState<number | "">("");
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const cats = manage ? Object.keys(DOC_CATEGORY) : ["attest", "sonstiges"];

  const upload = async () => {
    const f = fileRef.current?.files?.[0];
    if (!f) { setError("Bitte zuerst eine Datei auswählen."); return; }
    setBusy(true); setError(null);
    try {
      const q = new URLSearchParams({ filename: f.name, title: title.trim(), category });
      if (manage && target !== "") q.set("user_id", String(target));
      await uploadFile(`/documents?${q.toString()}`, f);
      toast("Dokument hochgeladen");
      setTitle(""); if (fileRef.current) fileRef.current.value = "";
      docs.reload();
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };

  const own = (docs.data ?? []).filter((d) => d.user_id !== null);
  const company = (docs.data ?? []).filter((d) => d.user_id === null);

  const row = (d: DocItem) => (
    <div className="list-item" key={d.id}>
      <span><b>{d.title || d.filename}</b><br />
        <span className="muted small">{DOC_CATEGORY[d.category] ?? d.category}{manage && d.user_name ? ` · ${d.user_name}` : ""} · {size(d.size)} · {fmtDate(d.created_at)}</span></span>
      <span className="row">
        <button className="link" onClick={() => downloadFile(`/documents/${d.id}/download`, d.filename).catch((e) => toast((e as Error).message, "error"))}>Herunterladen</button>
        {manage && <button className="link" onClick={async () => {
          if (!window.confirm("Dokument wirklich löschen? Das kann nicht rückgängig gemacht werden.")) return;
          try { await del(`/documents/${d.id}`); toast("Gelöscht"); docs.reload(); } catch (e) { toast((e as Error).message, "error"); }
        }}>Löschen</button>}
      </span>
    </div>
  );

  return (
    <>
      <h1>Dokumente</h1>
      <ErrorBox error={docs.error} onRetry={docs.reload} />
      <Card title="Hochladen">
        <div className="stack">
          {!manage && <p className="muted small">Hier können Sie z. B. Krankschreibungen (AU) hochladen. Nur Sie und die Leitung sehen diese Dokumente.</p>}
          <Field label="Datei" hint="PDF, JPG, PNG, DOCX oder XLSX, max. 10 MB"><input ref={fileRef} type="file" accept=".pdf,.jpg,.jpeg,.png,.docx,.xlsx" /></Field>
          <Field label="Titel (optional)"><input value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} /></Field>
          <div className="row">
            <div className="grow"><Field label="Art"><select value={category} onChange={(e) => setCategory(e.target.value)}>
              {cats.map((c) => <option key={c} value={c}>{DOC_CATEGORY[c]}</option>)}
            </select></Field></div>
            {manage && <div className="grow"><Field label="Für Person" hint="Leer = Firmendokument für alle"><select value={target} onChange={(e) => setTarget(e.target.value ? Number(e.target.value) : "")}>
              <option value="">— Firmendokument —</option>
              {(users.data ?? []).filter((u) => u.is_active).map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
            </select></Field></div>}
          </div>
          <ErrorBox error={error} />
          <Btn kind="primary" onClick={upload} disabled={busy}>{busy ? "Lädt hoch …" : "Hochladen"}</Btn>
        </div>
      </Card>
      <Card title="Firmendokumente">
        {company.length === 0 && !docs.loading && <Empty>Keine Firmendokumente.</Empty>}
        {company.map(row)}
      </Card>
      <Card title={manage ? "Dokumente der Mitarbeiter" : "Meine Dokumente"}>
        {own.length === 0 && !docs.loading && <Empty>Keine Dokumente vorhanden.</Empty>}
        {own.map(row)}
      </Card>
    </>
  );
}
