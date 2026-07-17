import type { Page } from "@playwright/test";

// Deterministic bootstrap config (light theme forced so axe contrast is stable).
export const CONFIG = {
  name: "Echo Bot",
  theme: {
    dark_mode: "light",
    light: {
      "--bg": "#ffffff",
      "--surface": "#f4f4f5",
      "--surface-2": "#ececee",
      "--border": "#e2e2e5",
      "--text": "#18181b",
      "--text-muted": "#6b6b70",
      "--primary": "#a6093d",
      "--primary-hover": "#8a0732",
      "--accent": "#f2c879",
      "--on-primary": "#ffffff",
    },
    dark: {
      "--bg": "#161618",
      "--surface": "#1e1e21",
      "--surface-2": "#27272b",
      "--border": "#34343a",
      "--text": "#f4f4f5",
      "--text-muted": "#9a9aa1",
      "--primary": "#d95c7d",
      "--primary-hover": "#c2355c",
      "--accent": "#f2c879",
      "--on-primary": "#ffffff",
    },
    radius: { "--radius-panel": "22px" },
  },
  starter_replies: [
    { label: "Set up VPN", query: "How do I set up the VPN?" },
    { label: "Library", query: "Library hours?" },
  ],
  greeting: { mode: "client_initiated" },
};

function frame(event: Record<string, unknown>): string {
  return `event: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`;
}

function sse(events: Record<string, unknown>[]): string {
  return events.map(frame).join("");
}

const SID = "sess-e2e";

export async function stubBackend(page: Page): Promise<void> {
  await page.route("**/api/v1/bots/*/config*", (route) =>
    route.fulfill({ contentType: "application/json", body: JSON.stringify(CONFIG) }),
  );

  await page.route("**/api/v1/bots/*/chat", async (route) => {
    const body = (route.request().postDataJSON() ?? {}) as {
      message?: string;
      choice?: { id?: string };
    };
    const msg = (body.message ?? "").toLowerCase();
    const session = { type: "session", seq: 0, session_id: SID, protocol_version: "1.0", bot_id: "echo", expires_in: 1800 };
    const done = (status: string, seq: number) => ({ type: "done", seq, status, session_id: SID, expires_in: 1800 });

    let events: Record<string, unknown>[];
    if (body.choice) {
      events = [
        session,
        { type: "text", seq: 1, message_id: "m1", delta: "You picked an option. " },
        { type: "text", seq: 2, message_id: "m1", delta: "Here is the answer." },
        done("complete", 3),
      ];
    } else if (msg.includes("xss")) {
      // a poisoned tool result: one dangerous javascript: url, one safe https url
      events = [
        session,
        { type: "text", seq: 1, message_id: "m1", delta: "Answer with sources." },
        {
          type: "sources", seq: 2, message_id: "m1",
          sources: [
            { title: "Malicious", source: "evil", url: "javascript:alert(document.cookie)" },
            { title: "Legit", source: "good.example", url: "https://good.example/page" },
          ],
        },
        done("complete", 3),
      ];
    } else if (msg.includes("two")) {
      // a turn with TWO assistant messages (distinct message_ids); sources on the first
      events = [
        session,
        { type: "text", seq: 1, message_id: "m1", delta: "First answer." },
        {
          type: "sources", seq: 2, message_id: "m1",
          sources: [{ title: "Source One", source: "one.uni.edu", url: "https://one.uni.edu" }],
        },
        { type: "text", seq: 3, message_id: "m2", delta: "Second answer." },
        done("complete", 4),
      ];
    } else if (msg.includes("contact")) {
      // an `actions` event: one safe tel + one safe url + one UNSAFE url (must be dropped)
      events = [
        session,
        { type: "text", seq: 1, message_id: "m1", delta: "Reach us here." },
        {
          type: "actions", seq: 2, message_id: "m1",
          actions: [
            { kind: "tel", label: "IT-Service-Desk", value: "+49 541 969 0000" },
            { kind: "url", label: "Serviceportal", value: "https://good.example/portal" },
            { kind: "url", label: "Evil", value: "javascript:alert(1)" },
          ],
        },
        done("complete", 3),
      ];
    } else if (msg.includes("menu")) {
      events = [
        session,
        {
          type: "quick_replies", seq: 1, reply_to: "evt_1", prompt: "What next?",
          options: [{ id: "credits", label: "Check credits" }, { id: "deadlines", label: "Deadlines" }],
          allow_free_text: true,
        },
        done("awaiting_input", 2),
      ];
    } else if (msg.includes("locked")) {
      events = [
        session,
        {
          type: "quick_replies", seq: 1, reply_to: "evt_2", prompt: "Choose one:",
          options: [{ id: "a", label: "Option A" }, { id: "b", label: "Option B" }],
          allow_free_text: false,
        },
        done("awaiting_input", 2),
      ];
    } else {
      events = [
        session,
        { type: "status", seq: 1, state: "tool_call", label: "Checking course catalog…", detail: "x" },
        { type: "text", seq: 2, message_id: "m1", delta: "You said: " },
        { type: "text", seq: 3, message_id: "m1", delta: msg + ". Here is a short answer." },
        {
          type: "sources", seq: 4, message_id: "m1",
          sources: [
            { title: "VPN-Einrichtung — Rechenzentrum", source: "rz.uni-osnabrueck.de", url: "https://rz.uni-osnabrueck.de/vpn" },
            { title: "eduroam / WLAN", source: "rz.uni-osnabrueck.de", url: "https://rz.uni-osnabrueck.de/wlan" },
          ],
        },
        done("complete", 5),
      ];
    }
    await route.fulfill({ contentType: "text/event-stream", body: sse(events) });
  });
}

export async function waitReady(page: Page): Promise<void> {
  await page.waitForFunction(() => document.body.dataset.ready === "1");
}
