// Bootstrap entry. Auto-inits from the embedding <script>'s data-* attributes and also
// exposes a programmatic API (window.EuleWidget.mount).
//
//   <script src="/widget.js" data-bot-id="echo" data-mode="launcher"
//           data-base-url="https://gateway.uni.edu" data-lang="de"
//           data-get-token="myTokenFn"
//           data-context-page="auto" data-context-topic="admissions"></script>
//
// data-context-* forwards host-page context on every turn (docs/01 §Context).
// data-context-page="auto" sends the current page URL.

import { EuleWidget, type WidgetOptions } from "./widget";
import type { Mode } from "./dom";
import type { Lang } from "./i18n";

function readScriptOptions(script: HTMLScriptElement): WidgetOptions | null {
  const botId = script.dataset.botId;
  if (!botId) return null;
  const win = window as unknown as Record<string, (() => string | null) | undefined>;
  const tokenFnName = script.dataset.getToken;
  const options: WidgetOptions = { botId };
  // Only accept a known mode; an unknown value would render with no matching layout
  // rules (silently broken). Fall back to the default launcher.
  if (script.dataset.mode && (["launcher", "inline", "standalone"] as const).includes(script.dataset.mode as Mode)) {
    options.mode = script.dataset.mode as Mode;
  }
  if (script.dataset.baseUrl) options.baseUrl = script.dataset.baseUrl;
  if (script.dataset.lang) options.lang = script.dataset.lang as Lang;
  if (script.dataset.scheme === "light" || script.dataset.scheme === "dark") {
    options.scheme = script.dataset.scheme;
  }
  if (tokenFnName) options.getToken = () => win[tokenFnName]?.();
  if (script.dataset.mount) {
    const el = document.querySelector<HTMLElement>(script.dataset.mount);
    if (el) options.mount = el;
  }
  const context: Record<string, string> = {};
  if (script.dataset.contextPage) {
    // "auto" sends origin + pathname ONLY — host-page query strings can carry tokens
    // or personal data (step 11 privacy). Sites wanting more pass an explicit value.
    context.page =
      script.dataset.contextPage === "auto"
        ? location.origin + location.pathname
        : script.dataset.contextPage;
  }
  if (script.dataset.contextTopic) context.topic = script.dataset.contextTopic;
  if (script.dataset.contextLocale) context.locale = script.dataset.contextLocale;
  if (Object.keys(context).length > 0) options.context = context;
  return options;
}

export function mount(options: WidgetOptions): Promise<EuleWidget> {
  const widget = new EuleWidget(options);
  return widget.init().then(() => widget);
}

function autoInit(): void {
  const script =
    (document.currentScript as HTMLScriptElement | null) ??
    document.querySelector<HTMLScriptElement>("script[data-bot-id]");
  if (!script) return;
  const options = readScriptOptions(script);
  if (!options) return;
  mount(options).catch((err) => console.error("[eule-widget]", err));
}

// currentScript is only valid during synchronous script evaluation.
autoInit();

export { EuleWidget };
export type { WidgetOptions };
