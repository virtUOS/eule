// Inline stroke SVGs (2px, currentColor) ported from design/. No external assets.
// aria-hidden — every control has a text/aria-label; icons are decorative.

const wrap = (inner: string, opts: { w: number; fill?: boolean; sw?: number }): string => {
  const stroke = opts.fill
    ? `fill="currentColor"`
    : `fill="none" stroke="currentColor" stroke-width="${opts.sw ?? 2}" stroke-linecap="round" stroke-linejoin="round"`;
  return `<svg viewBox="0 0 24 24" width="${opts.w}" height="${opts.w}" ${stroke} aria-hidden="true" focusable="false">${inner}</svg>`;
};

export const cloud = (w: number): string =>
  wrap(`<path d="M6.5 19a4.5 4.5 0 0 1-.5-8.97A6 6 0 0 1 17.7 8.5 4 4 0 0 1 17.5 19h-11z"/>`, { w, fill: true });

export const bota = (w: number): string =>
  wrap(`<path fill-rule="evenodd" d="M5 4h14a3 3 0 0 1 3 3v6.5a3 3 0 0 1-3 3h-7.2L7 20.6v-4.1H5a3 3 0 0 1-3-3V7a3 3 0 0 1 3-3Z M8 9.25a1.25 1.25 0 1 0 0 2.5 1.25 1.25 0 0 0 0-2.5Z M12 9.25a1.25 1.25 0 1 0 0 2.5 1.25 1.25 0 0 0 0-2.5Z M16 9.25a1.25 1.25 0 1 0 0 2.5 1.25 1.25 0 0 0 0-2.5Z"/>`, { w, fill: true });

export const close = (w = 18, sw = 2): string =>
  wrap(`<path d="M6 6l12 12M18 6L6 18"/>`, { w, sw });

export const newChat = (w = 18): string =>
  wrap(`<path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L8 18l-4 1 1-4z"/>`, { w });

export const send = (w = 19): string =>
  wrap(`<path d="M12 19V6M6 12l6-6 6 6"/>`, { w, sw: 2.2 });

export const externalLink = (w = 16): string =>
  wrap(`<path d="M10 6H6a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-4M14 4h6v6M20 4l-9 9"/>`, { w });

export const chevron = (w = 16): string => wrap(`<path d="M9 6l6 6-6 6"/>`, { w });

export const phone = (w = 16): string =>
  wrap(
    `<path d="M6.6 10.8a13 13 0 0 0 6.6 6.6l2.2-2.2a1 1 0 0 1 1-.24 11 11 0 0 0 3.5.56 1 1 0 0 1 1 1V20a1 1 0 0 1-1 1A17 17 0 0 1 3 4a1 1 0 0 1 1-1h3.5a1 1 0 0 1 1 1 11 11 0 0 0 .56 3.5 1 1 0 0 1-.24 1z"/>`,
    { w },
  );

export const mail = (w = 16): string =>
  wrap(`<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M4 7l8 6 8-6"/>`, { w });
