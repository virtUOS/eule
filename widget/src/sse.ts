// SSE client over fetch + ReadableStream (NOT EventSource — docs/01 §Transport: POST
// with an auth header). Parses the SSE framing into typed protocol events.

import type { ChatRequest, ServerEvent } from "./protocol";

export interface PreStreamError {
  type: "error";
  code: string;
  message: string;
  recoverable?: boolean;
}

export interface StreamHandlers {
  onEvent: (event: ServerEvent) => void;
  // Called when the stream ends WITHOUT a terminal `done` (transport drop). The turn
  // failed; the widget surfaces a retry affordance (docs/01 §Reconnection).
  onTransportDrop: () => void;
  // Pre-stream HTTP error (400/401/403/404/429) carrying the same error shape.
  onPreStreamError: (status: number, error: PreStreamError) => void;
}

const decoder = new TextDecoder();

// Parse one SSE frame block ("event: X\ndata: {...}") into a protocol event.
function parseFrame(block: string): ServerEvent | null {
  let dataLine = "";
  for (const raw of block.split("\n")) {
    const line = raw.replace(/\r$/, "");
    if (line.startsWith(":")) continue; // comment / heartbeat
    if (line.startsWith("data:")) {
      dataLine += line.slice(5).trimStart();
    }
    // `event:` field is advisory; the payload carries its own `type`.
  }
  if (!dataLine) return null;
  try {
    return JSON.parse(dataLine) as ServerEvent;
  } catch {
    return null; // unparseable → ignore, never fatal
  }
}

// Split a raw SSE text buffer into complete frames (terminated by a blank line),
// returning the leftover partial tail.
export function splitFrames(buffer: string): { frames: string[]; rest: string } {
  const frames: string[] = [];
  let rest = buffer;
  // Frames are separated by a blank line: \n\n (tolerate \r\n\r\n).
  const sep = /\r?\n\r?\n/;
  let m = sep.exec(rest);
  while (m) {
    frames.push(rest.slice(0, m.index));
    rest = rest.slice(m.index + m[0].length);
    m = sep.exec(rest);
  }
  return { frames, rest };
}

export async function streamChat(
  url: string,
  body: ChatRequest,
  headers: Record<string, string>,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  let resp: Response;
  try {
    resp = await fetch(url, {
      method: "POST",
      headers: { "content-type": "application/json", ...headers },
      body: JSON.stringify(body),
      signal,
    });
  } catch {
    handlers.onTransportDrop();
    return;
  }

  if (!resp.ok) {
    let err: PreStreamError = {
      type: "error",
      code: "internal_error",
      message: "Request failed.",
    };
    try {
      err = (await resp.json()) as PreStreamError;
    } catch {
      /* keep default */
    }
    handlers.onPreStreamError(resp.status, err);
    return;
  }

  if (!resp.body) {
    handlers.onTransportDrop();
    return;
  }

  const reader = resp.body.getReader();
  let buffer = "";
  let sawDone = false;

  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const { frames, rest } = splitFrames(buffer);
      buffer = rest;
      for (const block of frames) {
        const event = parseFrame(block);
        if (!event) continue;
        if (event.type === "done") sawDone = true;
        handlers.onEvent(event);
      }
    }
    // flush any trailing frame with no terminating blank line
    const tail = parseFrame(buffer);
    if (tail) {
      if (tail.type === "done") sawDone = true;
      handlers.onEvent(tail);
    }
  } catch {
    // read error mid-stream
  }

  if (!sawDone) handlers.onTransportDrop();
}
