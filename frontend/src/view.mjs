const DEFAULT_VIEW = 'settings';
const CARD_VIEWS = new Set([DEFAULT_VIEW, 'plan', 'history']);

export function normalizeView(view) {
  if (typeof view !== 'string') return DEFAULT_VIEW;

  const normalized = view.trim().toLowerCase();
  return CARD_VIEWS.has(normalized) ? normalized : DEFAULT_VIEW;
}
