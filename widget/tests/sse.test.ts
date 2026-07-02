import { describe, expect, it, vi } from "vitest";

import type { ServerEvent } from "../src/protocol";
import { splitFrames, streamChat } from "../src/sse";

function streamResponse(chunks: string[], status = 200): Response {
  const enc = new TextEncoder();
  let i = 0;
  const body = new ReadableStream<Uint8Array>({
    pull(c) {
      if (i < chunks.length) c.enqueue(enc.encode(chunks[i++]));
      else c.close();
    },
  });
  return {
    ok: status >= 200 && status < 300,
    status,
    body,
    json: async () => JSON.parse(chunks.join("")),
  } as unknown as Response;
}

function collect() {
  const events: ServerEvent[] = [];
  let dropped = false;
  let preErr: { status: number; code: string } | null = null;
  return {
    events,
    handlers: {
      onEvent: (e: ServerEvent) => events.push(e),
      onTransportDrop: () => {
        dropped = true;
      },
      onPreStreamError: (status: number, err: { code: string }) => {
        preErr = { status, code: err.code };
      },
    },
    get dropped() {
      return dropped;
    },
    get preErr() {
      return preErr;
    },
  };
}

describe("splitFrames", () => {
  it("splits complete frames and keeps the partial tail", () => {
    const { frames, rest } = splitFrames("event: a\ndata: 1\n\nevent: b\ndata: 2\n\nevent: c\ndata:");
    expect(frames).toHaveLength(2);
    expect(rest).toBe("event: c\ndata:");
  });
});

describe("streamChat", () => {
  it("parses a full stream, ignoring heartbeat comments", async () => {
    const c = collect();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        streamResponse([
          'event: session\ndata: {"type":"session","seq":0,"session_id":"s1"}\n\n',
          'event: text\ndata: {"type":"text","seq":1,"message_id":"m1","delta":"Hi "}\n\n',
          ": ping\n\n",
          'event: text\ndata: {"type":"text","seq":2,"message_id":"m1","delta":"there"}\n\n',
          'event: done\ndata: {"type":"done","seq":3,"status":"complete","session_id":"s1"}\n\n',
        ]),
      ),
    );
    await streamChat("/chat", { message: "x" }, {}, c.handlers);
    expect(c.events.map((e) => e.type)).toEqual(["session", "text", "text", "done"]);
    expect(c.dropped).toBe(false);
  });

  it("reassembles a frame split across chunk boundaries", async () => {
    const c = collect();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        streamResponse([
          'event: text\ndata: {"type":"text","seq":0,"mess',
          'age_id":"m1","delta":"ok"}\n\n',
          'event: done\ndata: {"type":"done","seq":1,"status":"complete","session_id":"s"}\n\n',
        ]),
      ),
    );
    await streamChat("/chat", { message: "x" }, {}, c.handlers);
    expect(c.events.map((e) => e.type)).toEqual(["text", "done"]);
    const text = c.events[0] as Extract<ServerEvent, { type: "text" }>;
    expect(text.delta).toBe("ok");
  });

  it("reports a pre-stream HTTP error", async () => {
    const c = collect();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        streamResponse(['{"type":"error","code":"invalid_request","message":"nope"}'], 400),
      ),
    );
    await streamChat("/chat", { message: "x", choice: { id: "y" } }, {}, c.handlers);
    expect(c.preErr).toEqual({ status: 400, code: "invalid_request" });
    expect(c.events).toHaveLength(0);
  });

  it("flags a transport drop when the stream ends without done", async () => {
    const c = collect();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        streamResponse([
          'event: text\ndata: {"type":"text","seq":0,"message_id":"m1","delta":"partial"}\n\n',
        ]),
      ),
    );
    await streamChat("/chat", { message: "x" }, {}, c.handlers);
    expect(c.dropped).toBe(true);
  });
});
