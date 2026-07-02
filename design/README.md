> ADOPT: the wolke design tokens (light+dark) as the sanctioned theme, the editorial
> visual, citation cards, launcher, three form factors, typing indicator, Web
> Component/Shadow DOM target. DROP (contract wins): localStorage transcript
> persistence; the `/api/wolke/message` {reply,citations} contract (real = SSE event
> protocol + bootstrap endpoint); runtime `/api/branding` fetch (theme comes from our
> config); always-visible free-text quick-replies (those are *starter suggestions*;
> protocol quick_replies are interrupt-driven); the single `aria-live` region (use the
> two-region model). On appearance/tokens the mockup leads; on behavior/semantics the specs win.

# Handoff: wolke Chat Widget (UX reference — direction **2a**, "Editorial")

## Overview
`wolke` is an embeddable university assistant chat widget for Universität Osnabrück.
It answers student/staff questions about IT services, studies, library, campus, etc.,
returns short answers with **source links**, and appears as a **floating launcher bubble**
(bottom-right) that expands into a chat panel.

It must work in three form factors from the **same** component:
1. **Floating launcher** overlaid on any host page (default).
2. **Embedded `<iframe>`** panel that fills its container.
3. **Standalone full page** (e.g. a dedicated `/assistent` route).

This bundle documents the **chosen** direction: **2a "Editorial"** — a calm, text-forward
panel (no chat-bubble tails on the bot side) with the round brand-red launcher.

## About the design files
The files here are **design references built in HTML** — a working prototype of the intended
look and behaviour, **not production code to copy**. Recreate this UI in the host project's
existing environment (React/Vue/Web Component/etc.) using its established patterns, then wire it
to the real backend. If no frontend environment exists yet, a **self-contained Web Component**
(Shadow DOM + Custom Element) is the recommended target because it must embed cleanly into many
different host UIs without CSS collisions.

**Files:**
- `wolke-widget.standalone.html` — open this in a browser to see/click the real behaviour offline (self-contained).
- `wolke-widget.dc.html` — readable source of the same widget (template + logic). Use it to read exact markup, styles, and the scripted bot logic.
- `preview.png` — screenshot of the expanded panel over a mock host page.

> The prototype's bot answers are **scripted** (keyword → canned reply) purely to demo the UX.
> Production replaces this with the real AI backend (see **Backend contract**). The message list,
> citations, quick-replies, typing indicator, persistence and theming are all real and should be reproduced.

## Fidelity
**High-fidelity.** Colours, type, spacing, radii, and interactions are final. Reproduce pixel-close,
but source every colour from the **wolke design tokens** (CSS variables) — never hardcode hex — so the
widget re-skins from the host's branding automatically.

---

## Views

### View A — Collapsed launcher
- **Purpose:** entry point; always visible, floats above host content.
- **Layout:** `position: fixed; right: 20px; bottom: 20px;` circular button **58×58 px**, `border-radius: 50%`.
- **Style:** `background: var(--primary)` (#a6093d), white cloud glyph (28px), shadow `0 10px 26px rgba(166,9,61,.42)`.
  Hover → `background: var(--primary-hover)` (#8a0732).
- **z-index:** `2147483000` (must sit above host UI).
- **Icon:** cloud (the wolke mark). When the panel is open, the same button shows a **close "✕"** icon (2.4px stroke).
- **A11y:** `aria-label` = "Fragen? wolke hilft" / "Ask wolke", `aria-expanded` reflects open state.

### View B — Expanded chat panel
- **Purpose:** the conversation surface.
- **Container:** `position: fixed; right: 20px; bottom: 92px;` (i.e. 20px gap above the launcher).
  Width **376px**, `max-width: calc(100vw - 32px)`; height `min(560px, calc(100vh - 120px))`.
  `background: var(--bg)`, `border: 1px solid var(--border)`, `border-radius: 22px`,
  `box-shadow: 0 18px 50px rgba(0,0,0,.18)`, `display:flex; flex-direction:column; overflow:hidden`.
  Entrance animation `wk-pop` (see Animations). `role="dialog"`, `aria-label="wolke"`.
- **On mobile / narrow iframe:** because of `max-width` and the `min(...)` height it collapses to a near-full-width,
  near-full-height sheet. In production, below ~480px width the panel should go **full-bleed** (inset 0, no radius) — see Responsive.

Panel is a vertical stack of 4 regions:

**B1 — Header** (`padding: 15px 14px 14px 16px; border-bottom: 1px solid var(--border)`), flex row, `gap:10px`:
- Avatar: 30×30 circle, `background: var(--surface-2)`, cloud glyph in `color: var(--primary)`.
- Title: "wolke", `font-weight:700; font-size:16px; letter-spacing:-.02em; color:var(--text)` (flex:1).
- **New-chat** icon button (pencil/compose icon) → clears the conversation. `aria-label` = "Neues Gespräch"/"New chat".
- **Close** icon button ("✕") → collapses to launcher. `aria-label` = "Schließen"/"Close".
- Both use the design system `IconButton` (`variant="plain"`), 34×34.
- **No language switcher** — language is injected by the host (see Internationalisation).

**B2 — Message list** (`flex:1; overflow-y:auto; padding: 18px 18px 6px; background: var(--bg)`), custom thin scrollbar.
Each message has `margin-bottom: 20px`.
- **Bot message** (editorial, no bubble):
  - Eyebrow row: gold cloud glyph (`color: var(--accent)` #f2c879, 14px) + label "WOLKE"
    (`font-size:10.5px; font-weight:700; letter-spacing:.09em; text-transform:uppercase; color:var(--text-muted)`), 6px gap, 6px bottom margin.
  - Body: `font-size:14.5px; line-height:1.62; color:var(--text)` — plain text, full width.
  - **Citations** (if any), 11px below, vertical stack `gap:7px`. Each is a link card:
    `display:flex; align-items:center; gap:10px; border:1px solid var(--border); border-radius:12px; padding:9px 12px; background:var(--surface)`.
    Left: external-link icon `color:var(--primary)` (16px). Middle (flex:1): title
    `font-size:13px; font-weight:600` over host `font-size:12px; color:var(--text-muted)`. Right: chevron `color:var(--text-muted)`.
    Hover → `border-color: var(--primary)`.
- **User message:** right-aligned, `max-width:82%`, `background:var(--surface-2); color:var(--text); border-radius:14px; padding:9px 13px; font-size:14px; line-height:1.5`.
- **Typing indicator:** gold cloud glyph + three 6px dots (`background:var(--text-muted)`) animating `wk-dot` with 0 / .18s / .36s delays.

**B3 — Quick replies** (`padding:10px 18px; border-top:1px solid var(--border)`), flex wrap, `gap:14px`.
Each is a **text link** button: `background:none; border:none; font-size:13px; font-weight:600; color:var(--primary); text-decoration:underline; text-underline-offset:3px`. Hover → `color:var(--primary-hover)`.
Clicking sends a natural-language question (the label is short, the sent text is a full question — see Interactions).
Default set (DE): "VPN einrichten", "eduroam / WLAN", "Passwort ändern", "Bibliothek".

**B4 — Composer** (`padding:12px 16px; border-top:1px solid var(--border)`), flex row, `gap:10px`, align center:
- Text input (flex:1): borderless, `background:var(--surface); border-radius:12px; padding:11px 14px; font-size:14px; color:var(--text)`.
  Placeholder "Nachricht an wolke…" / "Message wolke…". `aria-label` mirrors placeholder.
- **Send** button: design system `Button`, 42×42, `border-radius:14px`, up-arrow icon (white via currentColor).
  Enter (without Shift) also sends.

---

## Interactions & behaviour
- **Toggle:** launcher click toggles panel open/closed. Header "✕" closes. (Optional: `Esc` closes when panel focused.)
- **Send:** on submit → append **user** message immediately, clear input, show **typing indicator**, then append the **bot** reply.
  Prototype delays ~850ms; production shows typing until the backend responds (ideally stream tokens).
- **Quick replies:** send a full question as the user's message (label is a short chip; e.g. label "VPN einrichten" sends "Wie richte ich den VPN ein?"). Keep the quick set visible above the composer at all times.
- **New chat:** clears history back to a fresh greeting + persists.
- **Autoscroll:** the message list scrolls to the bottom whenever content changes (set `scrollTop = scrollHeight`; do **not** use `scrollIntoView`).
- **Empty input** does nothing.

## State management
Per widget instance:
| State | Type | Notes |
|---|---|---|
| `open` | boolean | panel open/closed. Default open in the demo; production default **closed**. |
| `chat` | `Message[]` | ordered conversation. |
| `typing` | boolean | true while awaiting a bot reply. |
| `draft` | string | composer input value (controlled). |
| `lang` | `'de' \| 'en'` | injected by host; also persisted. |
| `theme` | `'light' \| 'dark'` | injected by host (see Theming). |

`Message = { id: string; role: 'user' | 'bot'; text: string; time: 'HH:MM'; cites?: Citation[] }`
`Citation = { label: string; host: string; url?: string }` (prototype omits `url`; production should include it and make cards real links.)

### Persistence
The prototype persists to `localStorage` under key **`wolke-widget`** as `{ chat, lang }`, and rehydrates on load.
Production should keep this (or a server-side conversation id) so history survives reload. Namespace the key per tenant if embedded on multiple sites.

## Backend contract (replaces the scripted `reply()`)
Replace the local keyword matcher with a call to the assistant service. Suggested shape:

```
POST /api/wolke/message
Request:  { conversationId: string, message: string, lang: 'de' | 'en' }
Response: { reply: string, citations: { label: string, host: string, url: string }[] }
```
- Stream the reply if possible; keep the typing indicator visible until the first token / full response.
- Map `citations[]` directly onto the citation link cards (title = `label`, subtitle = `host`, `href` = `url`).
- The greeting and the default quick-reply set are client-provided (localised); everything else comes from the backend.
- The scripted topics in `wolke-widget.dc.html` (`topics()`) are only demo fixtures — **do not port them**.

## Internationalisation
- UI strings and the greeting exist in **DE** and **EN** (see `renderVals().ui` and `greeting()` for exact copy).
- **Language is injected by the host**, not chosen in-widget (there is intentionally no language picker).
  Expose it as a prop/attribute (`lang="de|en"`) or read the host `<html lang>`. Pass `lang` to the backend on every request.

## Theming — injected from the host
The widget carries **no colours of its own**; it renders entirely from CSS custom properties. The host controls the skin:
- **Light/Dark:** a `.dark` class on an ancestor swaps every token. In the widget, `theme='dark'` adds class `dark` to the root
  container; production can instead just inherit the host's `.dark`. Support "auto" by following `prefers-color-scheme`.
- **Branding:** because everything is `var(--*)`, overriding the token values (e.g. from the university's `/api/branding`) re-skins the whole widget with no code change.
- **If embedded via `<iframe>` or Shadow DOM**, the tokens must be defined inside that boundary — pass them in as attributes/CSS vars or fetch branding within the widget.

## Design tokens (wolke design system)
Reference these variables, not raw hex. Values shown for documentation only.

**Colour — light (`:root`)**
| Token | Value | Use |
|---|---|---|
| `--bg` | `#ffffff` | panel & app canvas |
| `--surface` | `#f4f4f5` | inputs, citation card, avatar bg |
| `--surface-2` | `#ececee` | user bubble, host-mock blocks |
| `--border` | `#e2e2e5` | dividers, borders |
| `--text` | `#18181b` | primary text |
| `--text-muted` | `#6b6b70` | labels, host, chevrons |
| `--primary` | `#a6093d` | launcher, send, links, active/brand |
| `--primary-hover` | `#8a0732` | hover of the above |
| `--accent` | `#f2c879` | the "wolke" eyebrow cloud only |
| `--info` / `--warning` / `--success` / `--danger` | `#2563eb` / `#b45309` / `#15803d` / `#b91c1c` | status only |

**Colour — dark (`.dark`)**
`--bg #161618` · `--surface #1e1e21` · `--surface-2 #27272b` · `--border #34343a` · `--text #f4f4f5` ·
`--text-muted #9a9aa1` · `--primary #c2355c` · `--primary-hover #a6093d` · `--accent #f2c879`.

**Radius:** `--radius-sm .25rem` · `--radius-md .375rem` · `--radius-lg .5rem`.
Widget-specific radii: panel **22px**, citation card **12px**, user bubble **14px**, input **12px**, send button **14px**, launcher **50%**.

**Typography:** system UI stack (`system-ui, -apple-system, "Segoe UI", sans-serif`) in the prototype — use the host app's font.
Sizes: title 16/700, bot body 14.5/1.62, user & input 14, citation title 13/600, host + quick 12–13, eyebrow/labels 10.5/700 uppercase +.09em.

**Spacing:** launcher offset 20px; panel-to-launcher gap 92px−58px; header pad `15/14/14/16`; list pad `18 18 6`; message gap 20px; composer pad `12 16`; quick-reply gap 14px.

**Shadows:** launcher `0 10px 26px rgba(166,9,61,.42)`; panel `0 18px 50px rgba(0,0,0,.18)`.

**Animations (keyframes):**
- `wk-pop` — panel entrance: `from{opacity:0; transform:translateY(14px) scale(.98)} to{opacity:1; transform:none}` · `.3s ease`.
- `wk-dot` — typing dot: `0%,60%,100%{translateY(0); opacity:.35} 30%{translateY(-4px); opacity:1}` · `1.2s infinite`, dots offset 0/.18/.36s.

## Responsive behaviour
- Panel width `min(376px, 100vw − 32px)`, height `min(560px, 100vh − 120px)`.
- **< ~480px viewport (mobile):** go full-bleed — panel `inset: 0`, `border-radius: 0`, header shows the close button; launcher hidden while open. Ensure tap targets ≥ 44px.
- **Iframe form factor:** the same panel filling the iframe (no launcher; `open` forced true, `position` relative/100%).

## Accessibility
- `role="dialog"` + `aria-label` on the panel; launcher `aria-label` + `aria-expanded`.
- Every icon button has an `aria-label`. Input has an `aria-label`.
- Design system components ship a visible focus ring (`focus-visible: ring 2px var(--primary)`) — keep it.
- Announce new bot messages via an `aria-live="polite"` region (add in production).
- Trap focus within the panel while open; return focus to the launcher on close.

## Components used (wolke design system)
Loaded from `_ds/.../\_ds_bundle.js` (`window.Wolke.*`):
- `Button` — send action (primary).
- `IconButton` (`variant="plain"`) — header new-chat & close.
- Tokens/classes from `styles.css` for all colours/spacing.
Message bubbles, citation cards, quick-reply links and the launcher are plain elements styled with the tokens
(the design system has no chat-specific primitives). Reproduce them with the host app's equivalents.

## Assets
- **wolke mark:** inline SVG cloud (no external file). Path: `M6.5 19a4.5 4.5 0 0 1-.5-8.97A6 6 0 0 1 17.7 8.5 4 4 0 0 1 17.5 19h-11z`. Recreate or swap for the official logo.
- Icons (inline stroke SVGs, 2px, `currentColor`): compose/pencil (new chat), ✕ (close), up-arrow (send), external-link + chevron (citations).
- No raster images, fonts, or third-party assets.
