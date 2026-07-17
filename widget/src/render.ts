// Message-element builders. Bot text is UNTRUSTED (indirect prompt injection surface):
// always set via textContent, never innerHTML.

import * as icons from "./icons";
import type { Strings } from "./i18n";
import type { ActionItem, SourceItem } from "./protocol";

// Citation URLs come from tool/retrieval output — UNTRUSTED (docs/04 §7). Only http(s)
// may become a real link; a `javascript:`/`data:` URL would execute in the host page's
// origin on click (Shadow DOM does not isolate script). Anything else → render unlinked.
function safeHttpUrl(raw: string): string | null {
  try {
    const u = new URL(raw);
    return u.protocol === "https:" || u.protocol === "http:" ? u.href : null;
  } catch {
    return null;
  }
}

// `actions` values are re-sanitized here (defense in depth — the gateway also only
// emits trusted config values). Each builder returns a safe href or null (→ dropped).
function telHref(raw: string): string | null {
  // tel: allows an optional leading + then digits/spaces/-/()/. ; strip to +digits.
  if (!/^\+?[0-9 ()./-]{3,}$/.test(raw)) return null;
  const compact = raw.replace(/[^0-9+]/g, "");
  return compact.length >= 3 ? `tel:${compact}` : null;
}
function mailtoHref(raw: string): string | null {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(raw) ? `mailto:${raw}` : null;
}
function actionHref(item: ActionItem): string | null {
  if (item.kind === "tel") return telHref(item.value);
  if (item.kind === "mailto") return mailtoHref(item.value);
  if (item.kind === "url") return safeHttpUrl(item.value);
  return null; // unknown kind → dropped (forward-compatible)
}

function srOnly(text: string): HTMLSpanElement {
  const s = document.createElement("span");
  s.className = "cb-sr-only";
  s.textContent = text;
  return s;
}

export function userMessage(text: string, s: Strings): HTMLElement {
  const msg = document.createElement("div");
  msg.className = "cb-msg";
  const row = document.createElement("div");
  row.className = "cb-user-row";
  const bubble = document.createElement("div");
  bubble.className = "cb-user-bubble";
  bubble.append(srOnly(s.youSaid + " "));
  bubble.appendChild(document.createTextNode(text));
  row.appendChild(bubble);
  msg.appendChild(row);
  return msg;
}

export interface BotMessage {
  el: HTMLElement;
  appendText: (delta: string) => void;
  fullText: () => string;
  attachSources: (sources: SourceItem[], s: Strings) => void;
  // Returns the labels of the actions actually rendered (invalid ones are dropped),
  // so the caller can announce them after the body (docs/05).
  attachActions: (actions: ActionItem[], s: Strings) => string[];
}

export function botMessage(s: Strings, botName: string): BotMessage {
  const msg = document.createElement("div");
  msg.className = "cb-msg";
  const inner = document.createElement("div");

  const eyebrow = document.createElement("div");
  eyebrow.className = "cb-eyebrow";
  const glyph = document.createElement("span");
  glyph.className = "cb-eyebrow-glyph";
  glyph.innerHTML = icons.bota(14);
  const label = document.createElement("span");
  label.className = "cb-eyebrow-label";
  label.textContent = botName;
  eyebrow.append(glyph, label, srOnly(s.assistantSaid));

  const body = document.createElement("div");
  body.className = "cb-bot-body";

  inner.append(eyebrow, body);
  msg.appendChild(inner);

  return {
    el: msg,
    appendText(delta: string): void {
      body.appendChild(document.createTextNode(delta));
    },
    fullText(): string {
      return body.textContent ?? "";
    },
    attachSources(sources: SourceItem[], strings: Strings): void {
      if (sources.length === 0) return;
      const group = document.createElement("div");
      group.className = "cb-sources";
      group.setAttribute("role", "group");
      group.setAttribute("aria-label", strings.sourcesLabel);
      for (const src of sources) {
        const href = src.url ? safeHttpUrl(src.url) : null;
        const card = href ? document.createElement("a") : document.createElement("div");
        card.className = "cb-cite";
        if (href && card instanceof HTMLAnchorElement) {
          card.href = href;
          card.target = "_blank";
          card.rel = "noopener noreferrer";
        }
        const iconEl = document.createElement("span");
        iconEl.className = "cb-cite-icon";
        iconEl.innerHTML = icons.externalLink(16);
        const textWrap = document.createElement("span");
        textWrap.className = "cb-cite-text";
        const title = document.createElement("span");
        title.className = "cb-cite-title";
        title.textContent = src.title;
        const host = document.createElement("span");
        host.className = "cb-cite-host";
        host.textContent = src.source;
        textWrap.append(title, host);
        const chev = document.createElement("span");
        chev.className = "cb-cite-chevron";
        chev.innerHTML = icons.chevron(16);
        card.append(iconEl, textWrap, chev);
        group.appendChild(card);
      }
      inner.appendChild(group);
    },
    attachActions(actions: ActionItem[], strings: Strings): string[] {
      const rendered: string[] = [];
      const group = document.createElement("div");
      group.className = "cb-actions";
      group.setAttribute("role", "group");
      group.setAttribute("aria-label", strings.actionsLabel);
      for (const item of actions) {
        const href = actionHref(item);
        if (href === null) continue; // unsafe / unknown kind → dropped
        const link = document.createElement("a");
        link.className = "cb-action";
        link.href = href;
        if (item.kind === "url") {
          link.target = "_blank";
          link.rel = "noopener noreferrer";
        }
        const iconEl = document.createElement("span");
        iconEl.className = "cb-action-icon";
        iconEl.innerHTML =
          item.kind === "tel" ? icons.phone(16) : item.kind === "mailto" ? icons.mail(16) : icons.externalLink(16);
        const textWrap = document.createElement("span");
        textWrap.className = "cb-action-text";
        const label = document.createElement("span");
        label.className = "cb-action-label";
        label.textContent = item.label;
        textWrap.appendChild(label);
        // Desktop can't dial — show the number/address itself so it's readable/copyable.
        if (item.kind === "tel" || item.kind === "mailto") {
          const value = document.createElement("span");
          value.className = "cb-action-value";
          value.textContent = item.value;
          textWrap.appendChild(value);
        }
        link.append(iconEl, textWrap);
        group.appendChild(link);
        rendered.push(item.label);
      }
      if (rendered.length > 0) inner.appendChild(group);
      return rendered;
    },
  };
}
