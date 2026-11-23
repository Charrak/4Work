/** WebSocket-Verbindung zum Server: meldet Änderungen anderer Geräte in Echtzeit. */
import { useEffect, useRef } from "react";

export const live = new EventTarget();
let socket: WebSocket | null = null;
let timer: number | undefined;
let pingTimer: number | undefined;
let wanted = false;
let attempts = 0;

function connect() {
  if (!wanted || socket) return;
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(`${proto}//${location.host}/api/ws`);
  socket = ws;
  ws.onopen = () => {
    attempts = 0;
    window.clearInterval(pingTimer);
    pingTimer = window.setInterval(() => { if (ws.readyState === 1) ws.send("ping"); }, 25000);
    live.dispatchEvent(new CustomEvent("connected"));
  };
  ws.onmessage = (m) => {
    if (m.data === "pong") return;
    try {
      const msg = JSON.parse(m.data);
      live.dispatchEvent(new CustomEvent(msg.event, { detail: msg.data }));
    } catch { /* ignorieren */ }
  };
  ws.onclose = (ev) => {
    window.clearInterval(pingTimer);
    socket = null;
    if (!wanted || ev.code === 4401) return;
    attempts += 1;
    timer = window.setTimeout(connect, Math.min(30000, 1000 * 2 ** Math.min(attempts, 5)));
  };
  ws.onerror = () => ws.close();
}

export function startLive() { wanted = true; connect(); }
export function stopLive() {
  wanted = false;
  window.clearTimeout(timer);
  window.clearInterval(pingTimer);
  socket?.close();
  socket = null;
}
window.addEventListener("online", () => { if (wanted) connect(); });

/** Ruft cb auf, wenn eines der Ereignisse eintrifft (oder die Verbindung wiederhergestellt wurde). */
export function useLive(events: string[], cb: () => void) {
  const ref = useRef(cb);
  ref.current = cb;
  useEffect(() => {
    const handler = () => ref.current();
    const all = [...events, "connected"];
    all.forEach((e) => live.addEventListener(e, handler));
    return () => all.forEach((e) => live.removeEventListener(e, handler));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [events.join(",")]);
}
