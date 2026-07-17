import type { Plugin, Connect } from "vite";
import type { ServerResponse } from "node:http";

// Dev-only stubbed gateway so `npm run dev` shows a working widget offline (the real
// gateway is a separate service). NOT part of the production build. Mirrors the
// protocol (docs/01) and the theme defaults (docs/03).

const CONFIG = {
  name: "eule",
  theme: {
    dark_mode: "auto",
    light: {
      "--bg": "#ffffff", "--surface": "#f4f4f5", "--surface-2": "#ececee",
      "--border": "#e2e2e5", "--text": "#18181b", "--text-muted": "#6b6b70",
      "--primary": "#a6093d", "--primary-hover": "#8a0732", "--accent": "#f2c879",
      "--on-primary": "#ffffff",
    },
    dark: {
      "--bg": "#161618", "--surface": "#1e1e21", "--surface-2": "#27272b",
      "--border": "#34343a", "--text": "#f4f4f5", "--text-muted": "#9a9aa1",
      "--primary": "#d95c7d", "--primary-hover": "#c2355c", "--accent": "#f2c879",
      "--on-primary": "#ffffff",
    },
    radius: {
      "--radius-panel": "22px", "--radius-card": "12px", "--radius-bubble": "14px",
      "--radius-input": "12px", "--radius-send": "14px",
    },
  },
  starter_replies: [
    { label: "VPN einrichten", query: "Wie richte ich den VPN ein?" },
    { label: "eduroam / WLAN", query: "Wie verbinde ich mich mit eduroam?" },
    { label: "Passwort ändern", query: "Wie ändere ich mein Passwort?" },
    { label: "Bibliothek", query: "Wann hat die Bibliothek geöffnet?" },
  ],
  greeting: { mode: "client_initiated" },
};

const SID = "dev-session";

function frame(e: Record<string, unknown>): string {
  return `event: ${e.type}\ndata: ${JSON.stringify(e)}\n\n`;
}

function turnFrames(body: { message?: string; choice?: { id?: string } }): string {
  const session = { type: "session", seq: 0, session_id: SID, protocol_version: "1.0", bot_id: "echo", expires_in: 1800 };
  const done = (status: string, seq: number) => ({ type: "done", seq, status, session_id: SID, expires_in: 1800 });
  const msg = (body.message ?? "").toLowerCase();

  if (body.choice) {
    return [session,
      { type: "text", seq: 1, message_id: "m1", delta: "Alles klar — " },
      { type: "text", seq: 2, message_id: "m1", delta: "hier ist die Antwort dazu." },
      done("complete", 3)].map(frame).join("");
  }
  if (msg.includes("menu")) {
    return [session,
      { type: "quick_replies", seq: 1, reply_to: "evt_1", prompt: "Was möchtest du wissen?",
        options: [{ id: "credits", label: "Credits prüfen" }, { id: "deadlines", label: "Fristen" }],
        allow_free_text: true },
      done("awaiting_input", 2)].map(frame).join("");
  }
  return [session,
    { type: "status", seq: 1, state: "tool_call", label: "Suche in der Wissensdatenbank…", detail: "kb.search" },
    { type: "text", seq: 2, message_id: "m1", delta: "Du hast gefragt: " },
    { type: "text", seq: 3, message_id: "m1", delta: `„${body.message ?? ""}“. ` },
    { type: "text", seq: 4, message_id: "m1", delta: "Das ist eine Demo-Antwort des Dev-Stubs." },
    { type: "sources", seq: 5, message_id: "m1",
      sources: [
        { title: "VPN-Einrichtung — Rechenzentrum", source: "rz.uni-osnabrueck.de", url: "https://rz.uni-osnabrueck.de/vpn" },
        { title: "eduroam / WLAN", source: "rz.uni-osnabrueck.de", url: "https://rz.uni-osnabrueck.de/wlan" },
      ] },
    done("complete", 6)].map(frame).join("");
}

function readBody(req: Connect.IncomingMessage): Promise<string> {
  return new Promise((res) => {
    let data = "";
    req.on("data", (c) => (data += c));
    req.on("end", () => res(data));
  });
}

export function devBackendStub(): Plugin {
  return {
    name: "eule-dev-backend-stub",
    apply: "serve",
    configureServer(server) {
      server.middlewares.use(async (req: Connect.IncomingMessage, res: ServerResponse, next) => {
        const url = req.url ?? "";
        if (!url.startsWith("/api/v1/bots/")) return next();

        if (url.includes("/config")) {
          res.setHeader("content-type", "application/json");
          res.end(JSON.stringify(CONFIG));
          return;
        }
        if (url.includes("/chat") && req.method === "POST") {
          const raw = await readBody(req);
          const body = raw ? JSON.parse(raw) : {};
          res.setHeader("content-type", "text/event-stream");
          res.setHeader("cache-control", "no-cache");
          res.end(turnFrames(body));
          return;
        }
        return next();
      });
    },
  };
}
