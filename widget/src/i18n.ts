// UI chrome + a11y scaffolding strings, bundled in the widget (de/en), NOT served
// (docs/01 §Widget bootstrap). Screen-reader-only labels are localized (docs/05 §10).

export type Lang = "de" | "en";

export interface Strings {
  ask: string;
  close: string;
  newChat: string;
  send: string;
  placeholder: string;
  region: string;
  youSaid: string;
  assistantSaid: string;
  sourcesLabel: string;
  actionsLabel: string;
  chooseOption: string;
  composerDisabledHint: string;
  sourcesAnnounce: (n: number, titles: string) => string;
  actionsAnnounce: (labels: string) => string;
  errorRetry: string;
  connectionLost: string;
}

const de: Strings = {
  ask: "Fragen? wolke hilft",
  close: "Schließen",
  newChat: "Neues Gespräch",
  send: "Senden",
  placeholder: "Nachricht an wolke…",
  region: "wolke Chat",
  youSaid: "Du:",
  assistantSaid: "Assistent:",
  sourcesLabel: "Quellen",
  actionsLabel: "Kontakt",
  chooseOption: "Bitte wähle eine Option:",
  composerDisabledHint: "Bitte wähle eine der Optionen oben.",
  sourcesAnnounce: (n, titles) => `${n} ${n === 1 ? "Quelle" : "Quellen"}: ${titles}.`,
  actionsAnnounce: (labels) => `Kontaktmöglichkeiten: ${labels}.`,
  errorRetry: "Erneut versuchen",
  connectionLost: "Verbindung unterbrochen. Bitte erneut versuchen.",
};

const en: Strings = {
  ask: "Ask wolke",
  close: "Close",
  newChat: "New chat",
  send: "Send",
  placeholder: "Message wolke…",
  region: "wolke chat",
  youSaid: "You said:",
  assistantSaid: "Assistant said:",
  sourcesLabel: "Sources",
  actionsLabel: "Contact",
  chooseOption: "Choose an option:",
  composerDisabledHint: "Please choose one of the options above.",
  sourcesAnnounce: (n, titles) => `${n} ${n === 1 ? "source" : "sources"}: ${titles}.`,
  actionsAnnounce: (labels) => `Contact options: ${labels}.`,
  errorRetry: "Try again",
  connectionLost: "The connection was lost. Please try again.",
};

export function strings(lang: Lang): Strings {
  return lang === "en" ? en : de;
}
