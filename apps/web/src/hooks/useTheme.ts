import { useSyncExternalStore } from 'react';

export type Theme = 'light' | 'dark';

const STORAGE_KEY = 'theme';
const listeners = new Set<() => void>();
let initialized = false;

function getInitialTheme(): Theme {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === 'light' || stored === 'dark') return stored;
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  } catch {
    // localStorage/matchMedia can throw in some privacy modes.
    return 'light';
  }
}

// index.html's inline script already sets the class before React mounts
// (avoids a flash of the wrong theme) — this just makes sure it's applied
// in case this module loads before that script ever ran (e.g. in tests).
function ensureInitialized() {
  if (initialized) return;
  initialized = true;
  document.documentElement.classList.toggle('dark', getInitialTheme() === 'dark');
}

function getSnapshot(): Theme {
  ensureInitialized();
  return document.documentElement.classList.contains('dark') ? 'dark' : 'light';
}

function subscribe(callback: () => void) {
  listeners.add(callback);
  return () => listeners.delete(callback);
}

function applyTheme(theme: Theme) {
  document.documentElement.classList.toggle('dark', theme === 'dark');
  try {
    localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    // Persistence is a nice-to-have — don't let it block the toggle itself.
  }
  listeners.forEach((listener) => listener());
}

/** Module-level store (not component-local state) so every ThemeToggle
 * instance mounted at once — desktop sidebar and mobile topbar are both
 * always in the DOM, just CSS-hidden depending on viewport — re-renders
 * together when the theme changes, instead of only the instance that
 * triggered the toggle. */
export function useTheme() {
  const theme = useSyncExternalStore(subscribe, getSnapshot);
  const toggleTheme = () => applyTheme(theme === 'dark' ? 'light' : 'dark');
  return { theme, toggleTheme };
}
