import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, clearQueue, flushQueue, mutateOrQueue, queueLength, setQueueUser } from "./api";

const json = (status: number, body: unknown) =>
  Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));

beforeEach(() => { localStorage.clear(); document.cookie = "csrf_token=abc123"; });
afterEach(() => { vi.unstubAllGlobals(); });

describe("api", () => {
  it("sends the CSRF header on writes but not on reads", async () => {
    const fetchMock = vi.fn(() => json(200, { ok: true }));
    vi.stubGlobal("fetch", fetchMock);
    await api("/x");
    await api("/x", { method: "POST", body: { a: 1 } });
    const [, getInit] = fetchMock.mock.calls[0] as any;
    const [, postInit] = fetchMock.mock.calls[1] as any;
    expect(getInit.headers["X-CSRF-Token"]).toBeUndefined();
    expect(postInit.headers["X-CSRF-Token"]).toBe("abc123");
  });

  it("turns server errors into German messages and keeps details", async () => {
    vi.stubGlobal("fetch", vi.fn(() => json(422, { detail: { message: "Planungshinweis: Ruhezeit", warnings: ["Ruhezeit"] } })));
    await expect(api("/shifts", { method: "POST", body: {} })).rejects.toMatchObject({
      status: 422, message: "Planungshinweis: Ruhezeit", detail: { warnings: ["Ruhezeit"] },
    });
  });

  it("flags conflicts (409)", async () => {
    vi.stubGlobal("fetch", vi.fn(() => json(409, { detail: { message: "geändert", current_version: 3 } })));
    const err = await api("/x", { method: "PATCH", body: {} }).catch((e) => e as ApiError);
    expect(err.isConflict).toBe(true);
  });
});

describe("offline queue", () => {
  it("queues a mutation when the network is down and sends it later in order", async () => {
    setQueueUser(1);
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new TypeError("offline"))));
    const r = await mutateOrQueue("Urlaub", "/leave", "POST", { a: 1 });
    expect(r.queued).toBe(true);
    expect(queueLength()).toBe(1);

    const ok = vi.fn(() => json(201, { id: 1 }));
    vi.stubGlobal("fetch", ok);
    await flushQueue(1);
    expect(ok).toHaveBeenCalledTimes(1);
    expect(queueLength()).toBe(0);
  });

  it("does not queue validation errors", async () => {
    vi.stubGlobal("fetch", vi.fn(() => json(422, { detail: "Ungültig" })));
    await expect(mutateOrQueue("Urlaub", "/leave", "POST", {})).rejects.toThrow("Ungültig");
    expect(queueLength()).toBe(0);
  });

  it("never sends another user's queued actions after a user change", async () => {
    setQueueUser(1);
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new TypeError("offline"))));
    await mutateOrQueue("Urlaub A", "/leave", "POST", { a: 1 });
    expect(queueLength()).toBe(1);

    const spy = vi.fn(() => json(201, { id: 1 }));
    vi.stubGlobal("fetch", spy);
    const notes = await flushQueue(2);            // Benutzer 2 meldet sich an
    expect(spy).not.toHaveBeenCalled();
    expect(queueLength()).toBe(0);
    expect(notes[0]).toMatch(/Verworfen/);
  });

  it("clearQueue removes everything and reports the count", async () => {
    setQueueUser(1);
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new TypeError("offline"))));
    await mutateOrQueue("x", "/leave", "POST", {});
    expect(clearQueue()).toBe(1);
    expect(queueLength()).toBe(0);
  });
});
