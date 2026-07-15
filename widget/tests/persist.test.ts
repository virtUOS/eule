import { afterEach, describe, expect, it, vi } from "vitest";

import {
  clearConversation,
  loadConversation,
  type PersistedConversation,
  saveConversation,
} from "../src/persist";

const BOT = "echo";
const KEY = `cb:conv:v1:${BOT}`;

function conv(overrides: Partial<PersistedConversation> = {}): PersistedConversation {
  return {
    v: 1,
    sessionId: "sess-1",
    expiresAt: Date.now() + 60_000,
    entries: [
      { role: "user", text: "hello" },
      {
        role: "bot",
        text: "hi there",
        sources: [{ title: "VPN", source: "rz.uni.example", url: "https://rz.uni.example/vpn" }],
      },
    ],
    pending: null,
    ...overrides,
  };
}

afterEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe("persist roundtrip", () => {
  it("saves and loads a conversation", () => {
    saveConversation(BOT, conv());
    const loaded = loadConversation(BOT);
    expect(loaded).not.toBeNull();
    expect(loaded?.sessionId).toBe("sess-1");
    expect(loaded?.entries).toHaveLength(2);
    expect(loaded?.entries[1].sources?.[0].title).toBe("VPN");
  });

  it("keys storage per bot id", () => {
    saveConversation(BOT, conv());
    expect(loadConversation("other-bot")).toBeNull();
    expect(loadConversation(BOT)).not.toBeNull();
  });

  it("clearConversation removes the slot", () => {
    saveConversation(BOT, conv());
    clearConversation(BOT);
    expect(loadConversation(BOT)).toBeNull();
  });

  it("persists a pending interrupt", () => {
    saveConversation(
      BOT,
      conv({
        pending: {
          replyTo: "evt_1",
          prompt: "What next?",
          options: [{ id: "a", label: "Option A" }],
          allowFreeText: false,
        },
      }),
    );
    expect(loadConversation(BOT)?.pending?.replyTo).toBe("evt_1");
  });
});

describe("expiry (client-side mirror of the server session TTL)", () => {
  it("returns null and clears the slot once expired", () => {
    saveConversation(BOT, conv({ expiresAt: Date.now() - 1 }));
    expect(loadConversation(BOT)).toBeNull();
    expect(localStorage.getItem(KEY)).toBeNull(); // stale blob must not linger
  });

  it("honors an explicit `now`", () => {
    const c = conv({ expiresAt: 1000 });
    saveConversation(BOT, c);
    expect(loadConversation(BOT, 999)).not.toBeNull();
    saveConversation(BOT, c);
    expect(loadConversation(BOT, 1000)).toBeNull(); // expiresAt <= now
  });
});

describe("hostile / stale storage never resurrects UI state", () => {
  it("rejects malformed JSON and clears the slot", () => {
    localStorage.setItem(KEY, "{not json");
    expect(loadConversation(BOT)).toBeNull();
    expect(localStorage.getItem(KEY)).toBeNull();
  });

  it("rejects a foreign-shaped object", () => {
    localStorage.setItem(KEY, JSON.stringify({ v: 1, sessionId: 42, entries: "nope" }));
    expect(loadConversation(BOT)).toBeNull();
  });

  it("rejects a wrong version", () => {
    localStorage.setItem(KEY, JSON.stringify(conv({ v: 2 as unknown as 1 })));
    expect(loadConversation(BOT)).toBeNull();
  });

  it("rejects entries with an unknown role", () => {
    const c = conv();
    (c.entries[0] as { role: string }).role = "system";
    localStorage.setItem(KEY, JSON.stringify(c));
    expect(loadConversation(BOT)).toBeNull();
  });

  it("rejects an empty session id", () => {
    localStorage.setItem(KEY, JSON.stringify(conv({ sessionId: "" })));
    expect(loadConversation(BOT)).toBeNull();
  });
});

describe("storage unavailability degrades silently", () => {
  it("save/load are no-ops when localStorage throws", () => {
    const spy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("QuotaExceededError");
    });
    expect(() => saveConversation(BOT, conv())).not.toThrow();
    spy.mockRestore();
    expect(loadConversation(BOT)).toBeNull();
  });
});
