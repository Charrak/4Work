import { useEffect, useRef, useState } from "react";
import { get, mutateOrQueue } from "../api";
import { useAuth, useToast } from "../context";
import { useLoad } from "../hooks";
import { useLive } from "../live";
import { fmtDate, fmtTime } from "../dates";
import type { Message } from "../types";
import { Btn, Card, ErrorBox } from "../ui";

export default function Chat() {
  const { me } = useAuth();
  const toast = useToast();
  const msgs = useLoad(() => get<Message[]>("/messages?limit=100"), []);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useLive(["chat.message"], msgs.reload);
  useEffect(() => { box.current?.scrollTo({ top: box.current.scrollHeight }); }, [msgs.data?.length]);

  const send = async () => {
    const t = text.trim();
    if (!t || sending) return;
    setSending(true);
    try {
      const r = await mutateOrQueue("Chat-Nachricht", "/messages", "POST", { text: t });
      if (r.queued) toast("Offline: Nachricht wird später gesendet", "info");
      setText(""); msgs.reload();
    } catch (e) { toast((e as Error).message, "error"); }
    finally { setSending(false); }
  };

  return (
    <>
      <h1>Team-Chat</h1>
      <Card>
        <ErrorBox error={msgs.error} onRetry={msgs.reload} />
        <div className="chat" ref={box}>
          {(msgs.data ?? []).map((m) => (
            <div key={m.id} className={`msg ${m.user_id === me!.id ? "mine" : ""}`}>
              <small>{m.user_name} · {fmtDate(m.created_at)} {fmtTime(m.created_at)}</small>
              {m.text}
            </div>
          ))}
          {msgs.data?.length === 0 && <p className="muted center">Noch keine Nachrichten.</p>}
        </div>
        <div className="row" style={{ marginTop: ".75rem" }}>
          <input className="grow" value={text} maxLength={2000} placeholder="Nachricht schreiben…" aria-label="Nachricht"
            onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send(); } }} />
          <Btn kind="primary" onClick={send}>Senden</Btn>
        </div>
      </Card>
    </>
  );
}
