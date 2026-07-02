import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Announcer, lastSentenceBoundary } from "../src/a11y";

describe("lastSentenceBoundary", () => {
  it("returns 0 when there is no boundary", () => {
    expect(lastSentenceBoundary("Hello world")).toBe(0);
  });
  it("finds a sentence end followed by whitespace", () => {
    expect(lastSentenceBoundary("Hi there. Rest")).toBe(9);
  });
  it("ignores punctuation not followed by whitespace (e.g. 3.5)", () => {
    expect(lastSentenceBoundary("3.5 credits")).toBe(0);
  });
  it("treats a newline as a boundary", () => {
    expect(lastSentenceBoundary("Line1\nLine2")).toBe(6);
  });
});

describe("Announcer", () => {
  let status: HTMLElement;
  let message: HTMLElement;
  let a: Announcer;

  beforeEach(() => {
    vi.useFakeTimers();
    status = document.createElement("div");
    message = document.createElement("div");
    a = new Announcer({ status, message }, 1000);
  });
  afterEach(() => {
    a.dispose();
    vi.useRealTimers();
  });

  it("buffers deltas without a boundary until the debounce fires", () => {
    a.delta("Hello ");
    expect(message.childElementCount).toBe(0); // not announced per-token
    vi.advanceTimersByTime(1000);
    expect(message.textContent).toContain("Hello");
  });

  it("flushes a completed sentence immediately", () => {
    a.delta("VPN is set up. ");
    expect(message.childElementCount).toBe(1);
    expect(message.textContent).toContain("VPN is set up.");
  });

  it("on finalize announces only the unflushed tail — never re-reads the whole message", () => {
    a.delta("VPN is set up. "); // sentence boundary → flushed now (child 1)
    a.delta("Then reconnect"); // no boundary → buffered
    a.finalize(); // flush the tail only (child 2)
    const chunks = Array.from(message.children).map((c) => c.textContent);
    expect(chunks).toEqual(["VPN is set up.", "Then reconnect"]);
    // the full text is present exactly once across the chunks, not duplicated
    expect(chunks.join(" ")).toBe("VPN is set up. Then reconnect");
  });

  it("finalize cancels the pending debounce (no late duplicate flush)", () => {
    a.delta("no boundary here");
    a.finalize(); // flushes the tail (child 1) and clears the timer
    const count = message.childElementCount;
    vi.advanceTimersByTime(2000);
    expect(message.childElementCount).toBe(count);
  });

  it("routes status to the status region (atomic), never the message region", () => {
    a.status("Checking course catalog…");
    expect(status.textContent).toBe("Checking course catalog…");
    expect(message.childElementCount).toBe(0);
  });
});
