# 05 — Widget Accessibility Specification

First-class requirement, built in from build-step 2. Shadow DOM = we own all
semantics. Streaming text and async interrupts are the hard, widget-specific problems.

## 1. Target

- **WCAG 2.1 Level AA.** Confirm & cite local mandate (EN 301 549 / Section 508 /
  PSBAR — substance identical).
- **Out of scope:** none by omission. (The OpenAI surface was cut; there is one surface, and it is fully in scope.)
- Standalone page has extra page-level obligations (§9).

## 2. DOM & ARIA structure (inside Shadow root)

Key requirements (full skeleton in build):
- Root: `<div role="region" aria-label="…chat">`.
- Transcript: `role="log"`, `tabindex="0"`, **not** `aria-live` (announce via
  dedicated regions below).
- **Two separate live regions:**
  - `#cb-status-announcer` — `aria-live="polite"` `aria-atomic="true"` (status).
  - `#cb-message-announcer` — `aria-live="polite"` `aria-atomic="false"` (messages).
- Each bubble prefixed with visually-hidden "You said:" / "Assistant said:".
- Assistant message may be followed by a **sources footer**:
  `<div class="cb-sources" role="group" aria-label="Sources">` containing a list of
  links. It is part of the message region, rendered after the bubble.
- Quick-replies: `role="group"` + `aria-label`; real `<button>`s.
- Composer: labelled `<textarea>`, hint via `aria-describedby`, real send `<button>`.
- All interactive elements are native controls, never `<div>` + click.
- `.cb-sr-only` utility class for visually-hidden text.

## 3. Streaming announcement (hard problem #1)

Decouple rendering from announcing:
- **Visual:** append `text` deltas live.
- **Screen reader:** do NOT announce per-token. Buffer deltas; flush a completed
  chunk to `#cb-message-announcer` on sentence/clause boundary OR ~1s debounce. On
  `done`, flush only the UNANNOUNCED tail — never re-read the whole message (the
  earlier chunks were already spoken; re-announcing the full text double-reads it).
- Status → status announcer (atomic), never clobbers messages.
- `prefers-reduced-motion` → skip streaming animation, render on `done`.

```js
function onTextDelta(delta){ appendVisually(delta); buffer+=delta;
  const b=lastSentenceBoundary(buffer);
  if(b>0){ announce(buffer.slice(0,b)); buffer=buffer.slice(b); }
  resetDebounce(1000, ()=>{ announce(buffer); buffer=""; }); }
function onDone(){ clearDebounce(); announce(buffer); buffer=""; } // tail only
function onStatus(label){ setStatusAnnouncer(label); }
```

### Sources announcement
When a `sources` event arrives, render the footer and announce it via the message
announcer AFTER the message body — e.g. "2 sources: CS101 Course Catalog; Enrollment
deadlines 2025." Do not interleave source links into the streamed text. Links are
keyboard-focusable and part of the tab order.

## 4. Interrupt announcement & focus (hard problem #2)

- **Quick-replies appear:** render group; announce "Choose an option: …" (from
  labels); **move focus to first choice**. If `allow_free_text:false`, disable
  composer AND announce why (§6).
- **Form appears:** announce title; move focus to first field. On validation error:
  populate `role="alert"` span, `aria-invalid=true`, move focus to first invalid field.
- **Resolved:** remove/hide interrupt UI, re-enable composer, return focus to composer.

## 5. Focus management

| Mode | Behavior |
|---|---|
| `launcher` (default) | Floating bubble → overlay panel (`role="dialog"`). On open: focus into panel + **trap**. On close: return focus to launcher. Esc closes. <480px: full-bleed (inset 0, no radius), launcher hidden while open, tap targets ≥ 44px. |
| `inline` | Fills its container/iframe; always open; no launcher; **no trap** (natural flow). `role="region"`, not dialog. |
| `standalone` | Full page; like `inline` + page-level a11y (§9: `<title>`, `<h1>`, `<main>`, skip link, `lang`). |

`embedding.mode` governs the trap: `launcher` traps focus inside the open dialog;
`inline` and `standalone` do NOT trap (natural document flow). Visible focus rings
≥ 3:1 contrast; never `outline:none` without a `:focus-visible` replacement.

The widget learns its form factor from the host embed (the `data-mode` attribute on the
`<script>`, default `launcher`), NOT from the bootstrap payload — `GET /config`
intentionally omits `mode` (it is a per-page embedding choice, like `data-bot-id`).
The registry `embedding.mode` documents the intended default for a bot.

## 6. Disabled input

When `allow_free_text:false`: set `disabled`/`aria-disabled`, add
`aria-describedby` hint ("Please choose one of the options above."), announce the
change, indicate with more than color.

## 7. Keyboard

Send=Enter (Shift+Enter=newline); Tab through quick-replies/form (Enter/Space
activate); transcript scroll via arrows/PageUp; Esc closes overlay. Logical tab
order; no traps except escapable overlay trap.

## 8. Visual / color / motion

- Contrast: text ≥ 4.5:1; UI + focus ≥ 3:1.
- **Theme tokens & contrast:** theming is a fixed token set (`docs/03-registry.md`),
  with deployment defaults (the design system) and per-bot/per-deployment overrides.
  The contrast guardrail (registry check 9) runs against the **resolved** tokens: for
  every text-on-color pair the widget uses, ensure ≥ 4.5:1, auto-selecting
  `--on-primary` black/white by luminance when set to `"auto"`. Never accept
  arbitrary CSS — only token values, so contrast is always checkable.
- `prefers-reduced-motion` disables animations.
- Usable at 200% zoom; reflow at 320px width; no fixed-height traps.
- Targets ≥ 24×24 CSS px (aim 44×44 touch).

## 9. Standalone page

`<title>`, one `<h1>`, `<main>` landmark, skip link, `lang` on `<html>`, widget in
inline mode (no trap).

## 10. Language / i18n for AT

Widget root `lang` matches bot locale. All `.cb-sr-only` scaffolding text localized.

## 11. Test plan (T10 — replaces the 4-line placeholder)

**T10-A Automated (CI, axe-core/Playwright):** zero violations in each state
(idle/streaming/quick-replies/disabled/sources-shown); accessible names; contrast;
no `outline:none` without `:focus-visible`; Shadow DOM isolation both directions.

**T10-B Keyboard (Playwright, no mouse):** full turn keyboard-only; tab order matches
visual; Esc closes overlay + focus returns; trap in overlay/absent inline; focus
moves to first choice on interrupt, returns to composer on resolve; focus NOT stolen during streaming; sources links are reachable and operable by keyboard.

**T10-C Live region:** streaming does not update message announcer per-token; final
message announced once on `done`; status → status announcer only; interrupt appearance
announced; disabled-composer change announced; sources announced after message body, not interleaved.

**T10-D Visual/motion/zoom:** usable at 200%/320px; reduced-motion disables animation;
targets ≥ 24px.

**T10-E Manual SR audit (pre-launch GATE, required before first public bot):**
NVDA+Firefox and VoiceOver+Safari full scripts; verify speaker identity, coherent
streamed answer, full answer heard, interrupts announced, disabled input explained,
errors announced. Publish an **accessibility conformance statement** (legal requirement).

## 12. Build integration

- Build-step 2: implement §2 DOM, two announcers (§3), semantic controls, keyboard
  from first commit; add T10-A + T10-B to CI.
- Registry: contrast check 10 + `embedding.mode`.
- Before first public bot (step 4): run T10-E, publish conformance statement.

## 13. Existing mockup — accessibility reconciliation

A design mockup exists at `design/`. Before adopting its markup,
audit it against §§2–8 and fix gaps. Mockups commonly miss: live regions,
semantic buttons vs. clickable divs, focus management, focus-visible styles,
and contrast of the chosen accent color. The mockup defines *appearance*; this
spec defines *behavior/semantics* and takes precedence on conflict.
