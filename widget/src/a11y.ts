// Accessibility helpers (docs/05 §§3–5): two decoupled live regions and focus mgmt.
// Rendering is decoupled from announcing — screen readers never hear per-token updates.

// Index just past the last sentence/clause boundary in `text`, else 0.
export function lastSentenceBoundary(text: string): number {
  let idx = 0;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (c === "\n") {
      idx = i + 1;
    } else if (".!?;:".includes(c)) {
      // boundary only if followed by whitespace/end (avoid "3.5", "e.g")
      const next = text[i + 1];
      if (next === undefined || next === " " || next === "\n") idx = i + 1;
    }
  }
  return idx;
}

export interface AnnouncerRegions {
  status: HTMLElement; // aria-live polite, aria-atomic true
  message: HTMLElement; // aria-live polite, aria-atomic false
}

export class Announcer {
  private buffer = "";
  private timer: ReturnType<typeof setTimeout> | null = null;
  private readonly debounceMs: number;

  constructor(
    private regions: AnnouncerRegions,
    debounceMs = 1000,
  ) {
    this.debounceMs = debounceMs;
  }

  // Ephemeral status → status announcer (atomic; replaces, never clobbers messages).
  status(label: string): void {
    this.regions.status.textContent = label;
  }

  clearStatus(): void {
    this.regions.status.textContent = "";
  }

  // Buffer streamed deltas; flush a completed chunk on sentence boundary or debounce.
  delta(text: string): void {
    this.buffer += text;
    const b = lastSentenceBoundary(this.buffer);
    if (b > 0) {
      this.flush(this.buffer.slice(0, b));
      this.buffer = this.buffer.slice(b);
    }
    this.resetDebounce();
  }

  // On `done`: cancel pending debounce and announce only the still-unflushed tail, so
  // the full message is heard exactly once, in order (deltas already flushed the
  // completed sentences). Re-announcing the whole message here would double-read it.
  finalize(): void {
    this.cancelDebounce();
    if (this.buffer) {
      this.flush(this.buffer);
      this.buffer = "";
    }
  }

  // A labelled list announced AFTER the message body (docs/05 §3 Sources).
  announceSources(text: string): void {
    this.flush(text);
  }

  private flush(text: string): void {
    const trimmed = text.trim();
    if (!trimmed) return;
    // Append a node so a non-atomic region re-reads only the new content.
    const span = document.createElement("div");
    span.textContent = trimmed;
    this.regions.message.appendChild(span);
    // keep the region from growing unbounded
    while (this.regions.message.childElementCount > 12) {
      this.regions.message.firstElementChild?.remove();
    }
  }

  private resetDebounce(): void {
    this.cancelDebounce();
    this.timer = setTimeout(() => {
      if (this.buffer) {
        this.flush(this.buffer);
        this.buffer = "";
      }
    }, this.debounceMs);
  }

  private cancelDebounce(): void {
    if (this.timer !== null) {
      clearTimeout(this.timer);
      this.timer = null;
    }
  }

  dispose(): void {
    this.cancelDebounce();
  }
}

// --- focus management ------------------------------------------------------

const FOCUSABLE =
  'a[href],button:not([disabled]),textarea:not([disabled]),input:not([disabled]),select:not([disabled]),[tabindex]:not([tabindex="-1"])';

export function focusable(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
    (el) => el.offsetParent !== null || el === document.activeElement,
  );
}

// Trap Tab focus inside `container` (launcher/dialog only — docs/05 §5). Returns a
// release fn. Caller handles Esc separately.
export function createFocusTrap(container: HTMLElement): () => void {
  const onKeydown = (e: KeyboardEvent): void => {
    if (e.key !== "Tab") return;
    const items = focusable(container);
    if (items.length === 0) return;
    const first = items[0];
    const last = items[items.length - 1];
    const active = (container.getRootNode() as ShadowRoot | Document)
      .activeElement as HTMLElement | null;
    if (e.shiftKey && active === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && active === last) {
      e.preventDefault();
      first.focus();
    }
  };
  container.addEventListener("keydown", onKeydown);
  return () => container.removeEventListener("keydown", onKeydown);
}
