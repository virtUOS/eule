// Bootstrap entry. Auto-inits from the embedding <script>'s data-* attributes and also
// exposes a programmatic API (window.WolkeWidget.mount).
//
//   <script src="/widget.js" data-bot-id="echo" data-mode="launcher"
//           data-base-url="https://gateway.uni.edu" data-lang="de"
//           data-get-token="myTokenFn"></script>

import { WolkeWidget, type WidgetOptions } from "./widget";
import type { Mode } from "./dom";
import type { Lang } from "./i18n";

function readScriptOptions(script: HTMLScriptElement): WidgetOptions | null {
  const botId = script.dataset.botId;
  if (!botId) return null;
  const win = window as unknown as Record<string, (() => string | null) | undefined>;
  const tokenFnName = script.dataset.getToken;
  const options: WidgetOptions = { botId };
  if (script.dataset.mode) options.mode = script.dataset.mode as Mode;
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
  return options;
}

export function mount(options: WidgetOptions): Promise<WolkeWidget> {
  const widget = new WolkeWidget(options);
  return widget.init().then(() => widget);
}

function autoInit(): void {
  const script =
    (document.currentScript as HTMLScriptElement | null) ??
    document.querySelector<HTMLScriptElement>("script[data-bot-id]");
  if (!script) return;
  const options = readScriptOptions(script);
  if (!options) return;
  mount(options).catch((err) => console.error("[wolke-widget]", err));
}

// currentScript is only valid during synchronous script evaluation.
autoInit();

export { WolkeWidget };
export type { WidgetOptions };
