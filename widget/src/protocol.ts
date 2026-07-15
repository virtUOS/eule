// Wire protocol types (docs/01). Forward-compatible: unknown event types/fields are
// ignored, never fatal.

export interface SessionEvent {
  type: "session";
  seq: number;
  session_id: string;
  protocol_version: string;
  bot_id: string;
  expires_in: number;
}

export type StatusState = "thinking" | "tool_call" | "done_thinking";

export interface StatusEvent {
  type: "status";
  seq: number;
  state: StatusState;
  label: string;
  detail?: string | null;
}

export interface TextEvent {
  type: "text";
  seq: number;
  message_id: string;
  delta: string;
}

export interface SourceItem {
  title: string;
  source: string; // host / subtitle shown under the title on the citation card
  url?: string;
}

export interface SourcesEvent {
  type: "sources";
  seq: number;
  message_id: string;
  sources: SourceItem[];
}

export interface QuickReplyOption {
  id: string;
  label: string;
}

export interface QuickRepliesEvent {
  type: "quick_replies";
  seq: number;
  reply_to: string;
  prompt: string;
  options: QuickReplyOption[];
  allow_free_text: boolean;
}

export interface ErrorEvent {
  type: "error";
  seq: number;
  code: string;
  message: string;
  recoverable?: boolean;
  retry_after?: number;
}

export type DoneStatus = "complete" | "awaiting_input" | "error";

export interface DoneEvent {
  type: "done";
  seq: number;
  status: DoneStatus;
  session_id: string;
  expires_in?: number;
}

export type ServerEvent =
  | SessionEvent
  | StatusEvent
  | TextEvent
  | SourcesEvent
  | QuickRepliesEvent
  | ErrorEvent
  | DoneEvent;

// --- request ---------------------------------------------------------------

// Host-page passthrough (docs/01 §Context). Non-sensitive situational hints only;
// the gateway enforces a strict key allowlist + size caps and treats it as untrusted.
export interface PageContext {
  page?: string; // URL/identifier of the host page (≤ 2000 chars)
  topic?: string; // routing/topic hint (≤ 200 chars)
  locale?: string; // display-language hint (≤ 35 chars); client.locale stays authoritative
}

export interface ChatRequest {
  session_id?: string;
  message?: string;
  choice?: { id?: string | null; text?: string | null };
  reply_to?: string;
  greeting?: boolean;
  client?: { locale?: string; widget_version?: string; embed_origin?: string };
  context?: PageContext;
}

// --- bootstrap config (GET /config) ----------------------------------------

export interface ThemeConfig {
  light: Record<string, string>;
  dark: Record<string, string>;
  dark_mode: "auto" | "light" | "dark";
  radius: Record<string, string>;
}

export interface StarterReply {
  label: string;
  query: string;
}

export interface BootstrapConfig {
  name: string;
  theme: ThemeConfig;
  starter_replies: StarterReply[];
  greeting: { mode: "client_initiated" | "bot_greeting" };
}
