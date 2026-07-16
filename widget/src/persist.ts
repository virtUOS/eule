// Survive-reload persistence (BUILD_PLAN step 7). The widget stores the session_id
// plus the RENDERED transcript in localStorage so a page reload rehydrates the UI
// and continues the same server session (the checkpoint lives server-side; this is
// presentation state only, never conversation authority — docs/01: server owns state).
//
// Privacy: transcripts may contain personal data. Entries are TTL-bound to the
// server session (`expires_in` from the protocol), cleared on expiry, on "new chat",
// and on `session_not_found`. Nothing here is trusted input on the way back in:
// rehydrated text is rendered via textContent (render.ts), never innerHTML.

import type { QuickReplyOption, SourceItem } from "./protocol";

export interface PersistedEntry {
  role: "user" | "bot";
  text: string;
  sources?: SourceItem[];
}

// A pending interrupt survives server-side (session.pending_reply_to); persist its
// presentation so the chips re-render after reload and the choice can still be sent.
export interface PersistedInterrupt {
  replyTo: string;
  prompt: string;
  options: QuickReplyOption[];
  allowFreeText: boolean;
}

export interface PersistedConversation {
  v: 1;
  sessionId: string;
  expiresAt: number; // epoch ms; client-side mirror of the server TTL
  entries: PersistedEntry[];
  pending: PersistedInterrupt | null;
}

const VERSION = 1;

// Per-bot key. localStorage is already scoped to the HOST PAGE's origin, so two
// deployments on different sites never collide; two bots on one site get one key each.
function storageKey(botId: string): string {
  return `cb:conv:v${VERSION}:${botId}`;
}

// localStorage can throw (sandboxed iframe, private mode, quota). Persistence is an
// enhancement: on any storage failure the widget degrades to session-only behavior.
function storage(): Storage | null {
  try {
    const s = window.localStorage;
    // Safari private-mode historically threw on write, not on read.
    const probe = "cb:probe";
    s.setItem(probe, "1");
    s.removeItem(probe);
    return s;
  } catch {
    return null;
  }
}

export function saveConversation(botId: string, conv: PersistedConversation): void {
  const s = storage();
  if (!s) return;
  try {
    s.setItem(storageKey(botId), JSON.stringify(conv));
  } catch {
    // quota etc. — degrade silently
  }
}

export function clearConversation(botId: string): void {
  try {
    window.localStorage.removeItem(storageKey(botId));
  } catch {
    // nothing to clear / no storage
  }
}

// Returns the stored conversation if it is well-formed and unexpired; otherwise
// clears the slot and returns null (a stale or foreign-shaped blob must never
// resurrect UI state).
export function loadConversation(botId: string, now: number = Date.now()): PersistedConversation | null {
  const s = storage();
  if (!s) return null;
  let raw: string | null;
  try {
    raw = s.getItem(storageKey(botId));
  } catch {
    return null;
  }
  if (!raw) return null;

  let conv: PersistedConversation;
  try {
    conv = JSON.parse(raw) as PersistedConversation;
  } catch {
    clearConversation(botId);
    return null;
  }
  if (!isValid(conv) || conv.expiresAt <= now) {
    clearConversation(botId);
    return null;
  }
  return conv;
}

// Element shapes are validated too — an array containing e.g. `null` would pass a
// bare Array.isArray check and then throw during rehydration rendering, which (if
// unhandled) would brick init on every load until localStorage is cleared manually.
function isSource(s: unknown): boolean {
  if (typeof s !== "object" || s === null) return false;
  const src = s as Record<string, unknown>;
  return (
    typeof src.title === "string" &&
    typeof src.source === "string" &&
    (src.url === undefined || typeof src.url === "string")
  );
}

function isOption(o: unknown): boolean {
  if (typeof o !== "object" || o === null) return false;
  const opt = o as Record<string, unknown>;
  return typeof opt.id === "string" && typeof opt.label === "string";
}

function isEntry(e: unknown): boolean {
  if (typeof e !== "object" || e === null) return false;
  const entry = e as Record<string, unknown>;
  return (
    (entry.role === "user" || entry.role === "bot") &&
    typeof entry.text === "string" &&
    (entry.sources === undefined ||
      (Array.isArray(entry.sources) && entry.sources.every(isSource)))
  );
}

function isValid(conv: PersistedConversation): boolean {
  return (
    typeof conv === "object" &&
    conv !== null &&
    conv.v === VERSION &&
    typeof conv.sessionId === "string" &&
    conv.sessionId.length > 0 &&
    typeof conv.expiresAt === "number" &&
    Array.isArray(conv.entries) &&
    conv.entries.every(isEntry) &&
    (conv.pending === null ||
      (typeof conv.pending === "object" &&
        conv.pending !== null &&
        typeof conv.pending.replyTo === "string" &&
        typeof conv.pending.prompt === "string" &&
        Array.isArray(conv.pending.options) &&
        conv.pending.options.every(isOption) &&
        typeof conv.pending.allowFreeText === "boolean"))
  );
}
