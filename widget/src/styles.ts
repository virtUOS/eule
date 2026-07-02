// Widget CSS, injected into the Shadow root. Ported from design/wolke-widget.dc.html
// (values pixel-close) but tokenized (var(--*)) and extended per docs/05:
// :focus-visible rings, prefers-reduced-motion, full-bleed <480px, form-factor variants.
// Theme token values are set on :host at runtime by theme.ts.

export const CSS = /* css */ `
:host {
  --radius-panel: 22px;
  --radius-card: 12px;
  --radius-bubble: 14px;
  --radius-input: 12px;
  --radius-send: 14px;
  all: initial;
}
/* Launcher: the host element must NOT affect host-page layout (panel+launcher are
   position:fixed). Inline/standalone: the host element fills its container so the
   panel can be height-bounded and scroll internally. */
:host([data-cb-mode="launcher"]) { display: contents; }
:host([data-cb-mode="inline"]),
:host([data-cb-mode="standalone"]) { display: block; height: 100%; min-height: 0; }
*, *::before, *::after { box-sizing: border-box; }
.cb-root {
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  -webkit-font-smoothing: antialiased;
  color: var(--text);
}
.cb-mode-inline, .cb-mode-standalone { height: 100%; min-height: 0; }
.cb-sr-only {
  position: absolute !important;
  width: 1px; height: 1px;
  padding: 0; margin: -1px;
  overflow: hidden; clip: rect(0 0 0 0); clip-path: inset(50%);
  white-space: nowrap; border: 0;
}

/* --- launcher (View A) --- */
.cb-launcher {
  position: fixed; right: 20px; bottom: 20px;
  width: 58px; height: 58px; border-radius: 50%;
  border: none; background: var(--primary); color: var(--on-primary);
  box-shadow: 0 10px 26px rgba(166, 9, 61, .42);
  cursor: pointer; display: flex; align-items: center; justify-content: center;
  z-index: 2147483000;
}
.cb-launcher:hover { background: var(--primary-hover); }

/* --- panel (View B) --- */
.cb-panel {
  background: var(--bg);
  border: 1px solid var(--border);
  display: flex; flex-direction: column; overflow: hidden;
}
.cb-mode-launcher .cb-panel {
  position: fixed; right: 20px; bottom: 92px;
  width: 376px; max-width: calc(100vw - 32px);
  height: min(560px, calc(100vh - 120px));
  border-radius: var(--radius-panel);
  box-shadow: 0 18px 50px rgba(0, 0, 0, .18);
  animation: cb-pop .3s ease;
  z-index: 2147483000;
}
.cb-mode-inline .cb-panel, .cb-mode-standalone .cb-panel {
  position: relative; width: 100%; height: 100%; min-height: 0;
  border-radius: 0; border: none;
}
.cb-mode-standalone .cb-panel { border: 1px solid var(--border); border-radius: var(--radius-panel); }

/* --- header --- */
.cb-header {
  display: flex; align-items: center; gap: 10px;
  padding: 15px 14px 14px 16px; border-bottom: 1px solid var(--border);
}
.cb-avatar {
  flex: none; width: 30px; height: 30px; border-radius: 50%;
  background: var(--surface-2); color: var(--primary);
  display: flex; align-items: center; justify-content: center;
}
.cb-title { flex: 1; font-weight: 700; font-size: 16px; letter-spacing: -.02em; color: var(--text); margin: 0; }
.cb-icon-btn {
  flex: none; width: 34px; height: 34px; border-radius: 8px;
  border: none; background: none; color: var(--text-muted);
  cursor: pointer; display: flex; align-items: center; justify-content: center;
}
.cb-icon-btn:hover { background: var(--surface); color: var(--text); }

/* --- message list --- */
.cb-log {
  flex: 1; min-height: 0; /* critical: let this flex child scroll instead of growing its parent */
  overflow-y: auto; padding: 18px 18px 6px; background: var(--bg);
  scrollbar-width: thin;
}
.cb-log::-webkit-scrollbar { width: 6px; }
.cb-log::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
.cb-msg { margin-bottom: 20px; }

.cb-user-row { display: flex; justify-content: flex-end; }
.cb-user-bubble {
  max-width: 82%; background: var(--surface-2); color: var(--text);
  border-radius: var(--radius-bubble); padding: 9px 13px; font-size: 14px; line-height: 1.5;
}

.cb-eyebrow { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; }
.cb-eyebrow-glyph { color: var(--accent); display: inline-flex; }
.cb-eyebrow-label {
  font-size: 10.5px; font-weight: 700; letter-spacing: .09em;
  text-transform: uppercase; color: var(--text-muted);
}
.cb-bot-body { font-size: 14.5px; line-height: 1.62; color: var(--text); white-space: pre-wrap; }

/* --- sources / citation cards --- */
.cb-sources { display: flex; flex-direction: column; gap: 7px; margin-top: 11px; }
.cb-cite {
  display: flex; align-items: center; gap: 10px; text-decoration: none;
  color: var(--text); border: 1px solid var(--border);
  border-radius: var(--radius-card); padding: 9px 12px; background: var(--surface);
}
.cb-cite:hover { border-color: var(--primary); }
.cb-cite-icon { flex: none; color: var(--primary); display: inline-flex; }
.cb-cite-text { flex: 1; min-width: 0; }
.cb-cite-title { display: block; font-size: 13px; font-weight: 600; }
.cb-cite-host { display: block; font-size: 12px; color: var(--text-muted); }
.cb-cite-chevron { flex: none; color: var(--text-muted); display: inline-flex; }

/* --- typing indicator --- */
.cb-typing { display: flex; align-items: center; gap: 6px; margin-bottom: 20px; }
.cb-dot {
  width: 6px; height: 6px; border-radius: 50%; background: var(--text-muted);
  display: inline-block; animation: cb-dot 1.2s infinite;
}
.cb-dot:nth-child(3) { animation-delay: .18s; }
.cb-dot:nth-child(4) { animation-delay: .36s; }

/* --- quick replies (interrupt) + starter chips --- */
.cb-chips {
  display: flex; flex-wrap: wrap; gap: 14px;
  padding: 10px 18px; border-top: 1px solid var(--border);
}
.cb-chips[hidden] { display: none; }
.cb-chip {
  background: none; border: none; padding: 2px 0; font-size: 13px;
  color: var(--primary); cursor: pointer; font-weight: 600; font-family: inherit;
  text-decoration: underline; text-underline-offset: 3px;
}
.cb-chip:hover { color: var(--primary-hover); }
.cb-qr-prompt { width: 100%; font-size: 12px; color: var(--text-muted); margin: 0 0 2px; }

/* --- composer --- */
.cb-composer {
  display: flex; gap: 10px; align-items: center;
  padding: 12px 16px; border-top: 1px solid var(--border);
}
.cb-input {
  flex: 1; border: none; border-radius: var(--radius-input);
  padding: 11px 14px; font-size: 14px; background: var(--surface);
  color: var(--text); outline: none; font-family: inherit; resize: none;
  max-height: 96px; line-height: 1.4;
}
.cb-input::placeholder { color: var(--text-muted); }
.cb-input:disabled { opacity: .55; cursor: not-allowed; }
.cb-send {
  width: 42px; height: 42px; padding: 0; border: none; border-radius: var(--radius-send);
  background: var(--primary); color: var(--on-primary); cursor: pointer;
  display: flex; align-items: center; justify-content: center; flex: none;
}
.cb-send:hover { background: var(--primary-hover); }
.cb-send:disabled { opacity: .55; cursor: not-allowed; }

/* --- error banner --- */
.cb-error {
  margin: 0 18px 12px; padding: 9px 12px; border-radius: var(--radius-card);
  background: var(--surface); border: 1px solid var(--border);
  color: var(--text); font-size: 13px; display: flex; gap: 10px; align-items: center;
}
.cb-error[hidden] { display: none; }
.cb-error button {
  border: none; background: var(--primary); color: var(--on-primary);
  border-radius: 8px; padding: 5px 10px; cursor: pointer; font: inherit; font-size: 12px;
}

/* --- status line --- */
.cb-status { padding: 0 18px 8px; font-size: 12px; color: var(--text-muted); min-height: 0; }
.cb-status[hidden] { display: none; }

/* --- focus visibility (docs/05 §5,§8: ≥3:1, never outline:none without replacement) --- */
:host *:focus-visible {
  outline: 2px solid var(--primary);
  outline-offset: 2px;
  border-radius: 4px;
}

/* --- responsive: full-bleed under ~480px (launcher mode) --- */
@media (max-width: 480px) {
  .cb-mode-launcher .cb-panel {
    inset: 0; right: 0; bottom: 0; width: 100vw; max-width: 100vw;
    height: 100vh; height: 100dvh; border-radius: 0; border: none;
  }
  .cb-mode-launcher.cb-open .cb-launcher { display: none; }
  .cb-icon-btn, .cb-send, .cb-chip { min-width: 44px; min-height: 44px; }
}

@keyframes cb-dot { 0%,60%,100% { transform: translateY(0); opacity: .35; } 30% { transform: translateY(-4px); opacity: 1; } }
@keyframes cb-pop { from { opacity: 0; transform: translateY(14px) scale(.98); } to { opacity: 1; transform: none; } }

@media (prefers-reduced-motion: reduce) {
  .cb-panel { animation: none !important; }
  .cb-dot { animation: none !important; }
}
`;
