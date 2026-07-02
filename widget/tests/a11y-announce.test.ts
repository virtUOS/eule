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

  it("announces the full message once on finalize and cancels the debounce", () => {
    a.delta("Partial without end ");
    a.finalize("Partial without end and the rest.");
    expect(message.textContent).toContain("and the rest.");
    const childrenAfterFinalize = message.childElementCount;
    vi.advanceTimersByTime(2000); // debounce must NOT fire again
    expect(message.childElementCount).toBe(childrenAfterFinalize);
  });

  it("routes status to the status region (atomic), never the message region", () => {
    a.status("Checking course catalog…");
    expect(status.textContent).toBe("Checking course catalog…");
    expect(message.childElementCount).toBe(0);
  });
});
