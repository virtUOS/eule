// Builds the Shadow-DOM skeleton (docs/05 §2): region/dialog roles, two live regions,
// semantic native controls only, .cb-sr-only scaffolding. No untrusted HTML: bot text
// is set via textContent; only static trusted icon SVGs use innerHTML.

import * as icons from "./icons";
import type { Strings } from "./i18n";
import { CSS } from "./styles";

export type Mode = "launcher" | "inline" | "standalone";

export interface WidgetDom {
  container: HTMLDivElement;
  panel: HTMLDivElement;
  launcher: HTMLButtonElement | null;
  newChatBtn: HTMLButtonElement;
  closeBtn: HTMLButtonElement | null;
  log: HTMLDivElement;
  statusLine: HTMLDivElement;
  chips: HTMLDivElement;
  composer: HTMLFormElement;
  input: HTMLTextAreaElement;
  sendBtn: HTMLButtonElement;
  errorBanner: HTMLDivElement;
  errorText: HTMLSpanElement;
  retryBtn: HTMLButtonElement;
  statusRegion: HTMLDivElement;
  messageRegion: HTMLDivElement;
}

function iconBtn(label: string, svg: string, cls = "cb-icon-btn"): HTMLButtonElement {
  const b = document.createElement("button");
  b.type = "button";
  b.className = cls;
  b.setAttribute("aria-label", label);
  b.innerHTML = svg;
  return b;
}

export function buildDom(root: ShadowRoot, mode: Mode, name: string, s: Strings): WidgetDom {
  const style = document.createElement("style");
  style.textContent = CSS;
  root.appendChild(style);

  const container = document.createElement("div");
  container.className = `cb-root cb-mode-${mode}`;

  // --- live regions (decoupled announcers, docs/05 §2/§3) ---
  const statusRegion = document.createElement("div");
  statusRegion.id = "cb-status-announcer";
  statusRegion.className = "cb-sr-only";
  statusRegion.setAttribute("aria-live", "polite");
  statusRegion.setAttribute("aria-atomic", "true");

  const messageRegion = document.createElement("div");
  messageRegion.id = "cb-message-announcer";
  messageRegion.className = "cb-sr-only";
  messageRegion.setAttribute("aria-live", "polite");
  messageRegion.setAttribute("aria-atomic", "false");

  // --- panel ---
  const panel = document.createElement("div");
  panel.className = "cb-panel";
  panel.setAttribute("role", mode === "launcher" ? "dialog" : "region");
  panel.setAttribute("aria-label", `${name} — ${s.region}`);
  if (mode === "launcher") panel.setAttribute("aria-modal", "true");

  // header
  const header = document.createElement("div");
  header.className = "cb-header";
  const avatar = document.createElement("div");
  avatar.className = "cb-avatar";
  avatar.innerHTML = icons.cloud(18);
  const title = document.createElement("h2");
  title.className = "cb-title";
  title.textContent = name;
  const newChatBtn = iconBtn(s.newChat, icons.newChat(18));
  header.append(avatar, title, newChatBtn);
  let closeBtn: HTMLButtonElement | null = null;
  if (mode === "launcher") {
    closeBtn = iconBtn(s.close, icons.close(18));
    header.append(closeBtn);
  }

  // status line (visible, ephemeral)
  const statusLine = document.createElement("div");
  statusLine.className = "cb-status";
  statusLine.hidden = true;

  // transcript (role=log, NOT aria-live — announced via regions)
  const log = document.createElement("div");
  log.className = "cb-log";
  log.setAttribute("role", "log");
  log.setAttribute("tabindex", "0");
  log.setAttribute("aria-label", name);

  // error banner
  const errorBanner = document.createElement("div");
  errorBanner.className = "cb-error";
  errorBanner.setAttribute("role", "status");
  errorBanner.hidden = true;
  const errorText = document.createElement("span");
  const retryBtn = document.createElement("button");
  retryBtn.type = "button";
  retryBtn.textContent = s.errorRetry;
  errorBanner.append(errorText, retryBtn);

  // chips row (starter suggestions OR interrupt quick-replies)
  const chips = document.createElement("div");
  chips.className = "cb-chips";
  chips.hidden = true;

  // composer
  const composer = document.createElement("form");
  composer.className = "cb-composer";
  const input = document.createElement("textarea");
  input.className = "cb-input";
  input.rows = 1;
  input.setAttribute("aria-label", s.placeholder);
  input.placeholder = s.placeholder;
  const sendBtn = iconBtn(s.send, icons.send(19), "cb-send");
  sendBtn.type = "submit";
  composer.append(input, sendBtn);

  panel.append(header, statusLine, log, errorBanner, chips, composer);

  // launcher button
  let launcher: HTMLButtonElement | null = null;
  if (mode === "launcher") {
    launcher = document.createElement("button");
    launcher.type = "button";
    launcher.className = "cb-launcher";
    launcher.setAttribute("aria-label", s.ask);
    launcher.setAttribute("aria-expanded", "false");
    launcher.innerHTML = icons.cloud(28);
  }

  container.append(statusRegion, messageRegion, panel);
  if (launcher) container.append(launcher);
  root.appendChild(container);

  return {
    container, panel, launcher, newChatBtn, closeBtn, log, statusLine, chips,
    composer, input, sendBtn, errorBanner, errorText, retryBtn, statusRegion, messageRegion,
  };
}
