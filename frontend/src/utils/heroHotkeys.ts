/**
 * Single-letter triage shortcuts ("Hotkeys for Heroes").
 * Ignore when the user is typing or when a modal/dialog has focus.
 */
export function isHeroHotkeyEventIgnored(e: KeyboardEvent): boolean {
  if (e.defaultPrevented) return true;
  if (e.ctrlKey || e.metaKey || e.altKey) return true;
  const t = e.target;
  if (!t || t === document.body) return false;
  const el = t as HTMLElement;
  if (el.isContentEditable) return true;
  const tag = el.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
  if (el.closest('[role="dialog"]')) return true;
  if (el.closest("[data-hotkeys-ignore]")) return true;
  return false;
}
