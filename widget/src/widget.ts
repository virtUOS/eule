// WolkeWidget — orchestration. Wires the SSE turn stream to rendering + the two
// accessibility announcers, focus management, and the three form factors.

import { Announcer, createFocusTrap, focusable } from "./a11y";
import { buildDom, type Mode, type WidgetDom } from "./dom";
import { strings, type Lang, type Strings } from "./i18n";
import type {
  BootstrapConfig,
  ChatRequest,
  QuickRepliesEvent,
  ServerEvent,
  SourceItem,
} from "./protocol";
import { botMessage, type BotMessage, userMessage } from "./render";
import { streamChat } from "./sse";
import { applyTheme, resolveScheme, watchScheme, type Scheme } from "./theme";

const WIDGET_VERSION = "0.1.0";

export interface WidgetOptions {
  botId: string;
  baseUrl?: string; // gateway origin; default same-origin
  mode?: Mode;
  lang?: Lang;
  scheme?: Scheme; // force light/dark; omit to follow the config's dark_mode (auto)
  getToken?: () => string | null | undefined | Promise<string | null | undefined>;
  mount?: HTMLElement; // for inline/standalone; defaults to a body-appended host
}

interface PendingInterrupt {
  replyTo: string;
  allowFreeText: boolean;
}

export class WolkeWidget {
  private readonly opts: Required<Pick<WidgetOptions, "botId" | "mode" | "lang">> & WidgetOptions;
  private readonly baseUrl: string;
  private s!: Strings;
  private dom!: WidgetDom;
  private announcer!: Announcer;
  private config!: BootstrapConfig;
  private hostEl!: HTMLElement;

  private sessionId: string | null = null;
  private pending: PendingInterrupt | null = null;
  // One assistant bubble per message_id within a turn (a turn may emit several).
  private bots = new Map<string, BotMessage>();
  private pendingSources: string | null = null; // announced AFTER the body, on done
  private typingEl: HTMLElement | null = null;
  private lastRequest: ChatRequest | null = null;
  private releaseTrap: (() => void) | null = null;
  private unwatchScheme: (() => void) | null = null;
  private open = false;
  private started = false;

  constructor(options: WidgetOptions) {
    this.opts = {
      ...options,
      botId: options.botId,
      mode: options.mode ?? "launcher",
      lang: options.lang ?? (document.documentElement.lang === "en" ? "en" : "de"),
    };
    this.baseUrl = (options.baseUrl ?? "").replace(/\/$/, "");
  }

  async init(): Promise<void> {
    this.s = strings(this.opts.lang);
    this.config = await this.fetchBootstrap();

    this.hostEl = this.opts.mount ?? document.createElement("div");
    if (!this.opts.mount) document.body.appendChild(this.hostEl);
    const root = this.hostEl.attachShadow({ mode: "open" });

    this.dom = buildDom(root, this.opts.mode, this.config.name, this.s);
    this.hostEl.setAttribute("lang", this.opts.lang);
    // drives the :host layout rules (launcher = display:contents; inline/standalone = fill container)
    this.hostEl.setAttribute("data-cb-mode", this.opts.mode);

    const scheme = this.opts.scheme ?? resolveScheme(this.config.theme.dark_mode);
    applyTheme(this.hostEl, this.config.theme, scheme);
    // Follow OS scheme changes only when the host hasn't forced a scheme.
    this.unwatchScheme = this.opts.scheme
      ? null
      : watchScheme(this.config.theme.dark_mode, (sc) =>
          applyTheme(this.hostEl, this.config.theme, sc),
        );

    this.announcer = new Announcer({
      status: this.dom.statusRegion,
      message: this.dom.messageRegion,
    });

    this.wireEvents();
    this.renderStarters();

    if (this.opts.mode === "launcher") {
      this.setOpen(false);
    } else {
      this.open = true;
      if (this.config.greeting.mode === "bot_greeting") void this.startGreeting();
    }
  }

  // --- bootstrap ---
  private async fetchBootstrap(): Promise<BootstrapConfig> {
    const url = `${this.baseUrl}/api/v1/bots/${this.opts.botId}/config?lang=${this.opts.lang}`;
    const resp = await fetch(url, { headers: { accept: "application/json" } });
    if (!resp.ok) throw new Error(`bootstrap failed: ${resp.status}`);
    return (await resp.json()) as BootstrapConfig;
  }

  // --- event wiring ---
  private wireEvents(): void {
    const { launcher, closeBtn, newChatBtn, composer, input, retryBtn } = this.dom;

    launcher?.addEventListener("click", () => this.setOpen(!this.open));
    closeBtn?.addEventListener("click", () => this.setOpen(false));
    newChatBtn.addEventListener("click", () => this.resetConversation());

    composer.addEventListener("submit", (e) => {
      e.preventDefault();
      this.submitDraft();
    });
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        this.submitDraft();
      } else if (e.key === "Escape" && this.opts.mode === "launcher") {
        this.setOpen(false);
      }
    });
    // grow textarea a little with content
    input.addEventListener("input", () => {
      input.style.height = "auto";
      input.style.height = `${Math.min(input.scrollHeight, 96)}px`;
    });
    retryBtn.addEventListener("click", () => this.retry());

    // Esc anywhere in the panel closes an overlay (launcher).
    if (this.opts.mode === "launcher") {
      this.dom.panel.addEventListener("keydown", (e) => {
        if (e.key === "Escape") this.setOpen(false);
      });
    }
  }

  // --- open/close + focus (launcher only) ---
  private setOpen(next: boolean): void {
    if (this.opts.mode !== "launcher") return;
    this.open = next;
    this.dom.panel.style.display = next ? "flex" : "none";
    this.dom.container.classList.toggle("cb-open", next);
    this.dom.launcher?.setAttribute("aria-expanded", String(next));
    if (next) {
      this.releaseTrap = createFocusTrap(this.dom.panel);
      const first = focusable(this.dom.panel)[0];
      (first ?? this.dom.input).focus();
      if (!this.started && this.config.greeting.mode === "bot_greeting") void this.startGreeting();
    } else {
      this.releaseTrap?.();
      this.releaseTrap = null;
      this.dom.launcher?.focus();
    }
  }

  // --- conversation control ---
  private resetConversation(): void {
    this.sessionId = null;
    this.pending = null;
    this.bots.clear();
    this.pendingSources = null;
    this.started = false;
    this.dom.log.replaceChildren();
    this.clearTyping();
    this.hideError();
    this.enableComposer();
    this.announcer.clearStatus();
    this.dom.statusLine.hidden = true;
    this.renderStarters();
    this.dom.input.focus();
  }

  private submitDraft(): void {
    const text = this.dom.input.value.trim();
    if (!text) return;
    this.dom.input.value = "";
    this.dom.input.style.height = "auto";
    if (this.pending && this.pending.allowFreeText) {
      // typed reply to a pending interrupt (docs/04 §5: id=None, text set)
      const replyTo = this.pending.replyTo;
      this.appendUser(text);
      this.clearInterrupt();
      void this.runTurn({ session_id: this.sessionId ?? undefined, choice: { id: null, text }, reply_to: replyTo });
    } else {
      this.sendMessage(text);
    }
  }

  private sendMessage(text: string): void {
    this.hideStarters();
    this.appendUser(text);
    void this.runTurn({ session_id: this.sessionId ?? undefined, message: text });
  }

  private sendChoice(id: string): void {
    if (!this.pending) return;
    const replyTo = this.pending.replyTo;
    this.clearInterrupt();
    void this.runTurn({ session_id: this.sessionId ?? undefined, choice: { id }, reply_to: replyTo });
  }

  private startGreeting(): void {
    this.started = true;
    this.hideStarters();
    void this.runTurn({ greeting: true });
  }

  // --- the SSE turn ---
  private async runTurn(partial: ChatRequest, authRetry = false): Promise<void> {
    this.started = true;
    this.hideError();
    this.bots.clear();
    this.pendingSources = null;
    // A resume turn consumes its interrupt server-side; if the stream drops it CANNOT
    // be safely retried (the reply_to no longer matches) — so it is not recoverable.
    const isResume = partial.choice !== undefined || partial.reply_to !== undefined;
    const body: ChatRequest = {
      ...partial,
      client: { locale: this.opts.lang, widget_version: WIDGET_VERSION, embed_origin: location.origin },
    };
    this.lastRequest = body;
    this.showTyping();
    this.disableSendWhileStreaming(true);

    const headers: Record<string, string> = {};
    const token = this.opts.getToken ? await this.opts.getToken() : null;
    if (token) headers["authorization"] = `Bearer ${token}`;

    const url = `${this.baseUrl}/api/v1/bots/${this.opts.botId}/chat`;
    await streamChat(url, body, headers, {
      onEvent: (ev) => this.handleEvent(ev),
      onTransportDrop: () => {
        this.clearTyping();
        this.showError(this.s.connectionLost, !isResume);
        this.disableSendWhileStreaming(false);
      },
      onPreStreamError: (_status, err) => {
        this.clearTyping();
        this.disableSendWhileStreaming(false);
        // token_expired: ask the host for a fresh token (getToken is re-invoked) and
        // retry the SAME turn once (docs/01: recoverable, "host should refresh + retry").
        if (err.code === "token_expired" && this.opts.getToken && !authRetry) {
          void this.runTurn(partial, true);
          return;
        }
        this.showError(err.message || this.s.connectionLost, err.recoverable ?? false);
      },
    });
  }

  private handleEvent(ev: ServerEvent): void {
    switch (ev.type) {
      case "session":
        this.sessionId = ev.session_id;
        break;
      case "status":
        this.dom.statusLine.hidden = false;
        this.dom.statusLine.textContent = ev.label;
        this.announcer.status(ev.label);
        break;
      case "text":
        this.clearTyping();
        this.ensureBotMessage(ev.message_id).appendText(ev.delta);
        this.announcer.delta(ev.delta);
        this.autoscroll();
        break;
      case "sources":
        // Render the footer now, but announce it AFTER the body (on done), per docs/05 §3.
        this.ensureBotMessage(ev.message_id).attachSources(ev.sources, this.s);
        this.pendingSources = this.sourcesAnnouncement(ev.sources);
        this.autoscroll();
        break;
      case "quick_replies":
        this.clearTyping();
        this.renderInterrupt(ev);
        break;
      case "error":
        this.clearTyping();
        this.showError(ev.message, ev.recoverable ?? false);
        break;
      case "done":
        this.onDone(ev.status);
        break;
      default:
        break; // forward-compatible: ignore unknown events
    }
  }

  private onDone(status: "complete" | "awaiting_input" | "error"): void {
    this.dom.statusLine.hidden = true;
    // flush the unannounced tail of the body first, THEN the sources — so a screen
    // reader hears the answer before its citations (docs/05 §3).
    this.announcer.finalize();
    if (this.pendingSources) {
      this.announcer.announceSources(this.pendingSources);
      this.pendingSources = null;
    }
    if (status === "awaiting_input") {
      // interrupt UI + its announcement were set by quick_replies; keep them and the
      // composer state (per allow_free_text). Do NOT clear the status announcer here.
      return;
    }
    this.announcer.clearStatus();
    this.disableSendWhileStreaming(false);
    this.enableComposer();
    if (status === "complete") {
      this.focusComposer();
    }
  }

  // --- rendering helpers ---
  private appendUser(text: string): void {
    this.dom.log.appendChild(userMessage(text, this.s));
    this.autoscroll();
  }

  // Get-or-create the bubble for a message_id, so a turn with several assistant
  // messages renders as several bubbles and sources bind to the right one (docs/01).
  private ensureBotMessage(messageId: string): BotMessage {
    let bot = this.bots.get(messageId);
    if (!bot) {
      bot = botMessage(this.s, this.config.name);
      this.bots.set(messageId, bot);
      this.dom.log.appendChild(bot.el);
    }
    return bot;
  }

  private showTyping(): void {
    this.clearTyping();
    const t = document.createElement("div");
    t.className = "cb-typing";
    t.setAttribute("aria-hidden", "true");
    t.innerHTML =
      '<span class="cb-eyebrow-glyph"></span><span class="cb-dot"></span><span class="cb-dot"></span><span class="cb-dot"></span>';
    this.dom.log.appendChild(t);
    this.typingEl = t;
    this.autoscroll();
  }

  private clearTyping(): void {
    this.typingEl?.remove();
    this.typingEl = null;
  }

  private autoscroll(): void {
    this.dom.log.scrollTop = this.dom.log.scrollHeight;
  }

  // --- starter chips (send `message`) ---
  private renderStarters(): void {
    const chips = this.dom.chips;
    chips.replaceChildren();
    chips.removeAttribute("role");
    chips.removeAttribute("aria-label");
    const starters = this.config.starter_replies ?? [];
    if (starters.length === 0) {
      chips.hidden = true;
      return;
    }
    for (const st of starters) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "cb-chip";
      b.textContent = st.label;
      b.addEventListener("click", () => this.sendMessage(st.query));
      chips.appendChild(b);
    }
    chips.hidden = false;
  }

  private hideStarters(): void {
    if (!this.dom.chips.hasAttribute("role")) {
      this.dom.chips.hidden = true;
      this.dom.chips.replaceChildren();
    }
  }

  // --- interrupt quick_replies (send `choice`) ---
  private renderInterrupt(ev: QuickRepliesEvent): void {
    this.pending = { replyTo: ev.reply_to, allowFreeText: ev.allow_free_text };
    const chips = this.dom.chips;
    chips.replaceChildren();
    chips.hidden = false;
    chips.setAttribute("role", "group");
    const labels = ev.options.map((o) => o.label).join(", ");
    chips.setAttribute("aria-label", `${this.s.chooseOption} ${labels}`);

    if (ev.prompt) {
      const p = document.createElement("p");
      p.className = "cb-qr-prompt";
      p.textContent = ev.prompt;
      chips.appendChild(p);
    }
    for (const opt of ev.options) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "cb-chip";
      b.textContent = opt.label;
      b.addEventListener("click", () => this.sendChoice(opt.id));
      chips.appendChild(b);
    }

    // announce + move focus to first choice (docs/05 §4)
    this.announcer.status(`${this.s.chooseOption} ${labels}`);
    if (!ev.allow_free_text) this.disableComposer();
    else this.enableComposer();
    const firstBtn = chips.querySelector<HTMLButtonElement>("button");
    firstBtn?.focus();
  }

  private clearInterrupt(): void {
    this.pending = null;
    this.dom.chips.replaceChildren();
    this.dom.chips.hidden = true;
    this.dom.chips.removeAttribute("role");
    this.dom.chips.removeAttribute("aria-label");
    this.enableComposer();
  }

  // --- composer enable/disable (docs/05 §6) ---
  private disableComposer(): void {
    this.dom.input.disabled = true;
    this.dom.input.setAttribute("aria-disabled", "true");
    this.dom.input.setAttribute("aria-describedby", "cb-status-announcer");
    this.dom.sendBtn.disabled = true;
    this.announcer.status(this.s.composerDisabledHint);
  }

  private enableComposer(): void {
    this.dom.input.disabled = false;
    this.dom.input.removeAttribute("aria-disabled");
    this.dom.input.removeAttribute("aria-describedby");
    this.dom.sendBtn.disabled = false;
  }

  private disableSendWhileStreaming(streaming: boolean): void {
    // keep input editable, but block a second submit mid-turn
    this.dom.sendBtn.disabled = streaming || this.dom.input.disabled;
  }

  private focusComposer(): void {
    if (!this.dom.input.disabled) this.dom.input.focus();
  }

  // --- sources announcement text (spoken after the body, on done — docs/05 §3) ---
  private sourcesAnnouncement(sources: SourceItem[]): string | null {
    if (sources.length === 0) return null;
    const titles = sources.map((s) => s.title).join("; ");
    return this.s.sourcesAnnounce(sources.length, titles);
  }

  // --- errors + retry ---
  private showError(message: string, recoverable: boolean): void {
    this.dom.errorText.textContent = message;
    this.dom.retryBtn.hidden = !recoverable;
    this.dom.errorBanner.hidden = false;
    this.announcer.status(message);
    this.disableSendWhileStreaming(false);
  }

  private hideError(): void {
    this.dom.errorBanner.hidden = true;
  }

  private retry(): void {
    if (!this.lastRequest) return;
    this.hideError();
    void this.runTurn(this.lastRequest);
  }

  dispose(): void {
    this.announcer.dispose();
    this.releaseTrap?.();
    this.unwatchScheme?.();
  }
}
