// Message-element builders. Bot text is UNTRUSTED (indirect prompt injection surface):
// always set via textContent, never innerHTML.

import * as icons from "./icons";
import type { Strings } from "./i18n";
import type { SourceItem } from "./protocol";

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
}

export function botMessage(s: Strings, botName: string): BotMessage {
  const msg = document.createElement("div");
  msg.className = "cb-msg";
  const inner = document.createElement("div");

  const eyebrow = document.createElement("div");
  eyebrow.className = "cb-eyebrow";
  const glyph = document.createElement("span");
  glyph.className = "cb-eyebrow-glyph";
  glyph.innerHTML = icons.cloud(14);
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
  };
}
