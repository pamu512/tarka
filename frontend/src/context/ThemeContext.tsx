import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export type ThemePreference = "light" | "dark" | "system";

const STORAGE_KEY = "tarka-theme";

export function resolveIsDark(preference: ThemePreference): boolean {
  if (preference === "light") return false;
  if (preference === "dark") return true;
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

export function applyThemeToDocument(preference: ThemePreference): void {
  document.documentElement.classList.toggle("dark", resolveIsDark(preference));
}

type ThemeContextValue = {
  preference: ThemePreference;
  setPreference: (p: ThemePreference) => void;
  effective: "light" | "dark";
};

const ThemeContext = createContext<ThemeContextValue | null>(null);

function readStoredPreference(): ThemePreference {
  try {
    const s = localStorage.getItem(STORAGE_KEY);
    if (s === "light" || s === "dark" || s === "system") return s;
  } catch {
    /* ignore */
  }
  return "system";
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [preference, setPreferenceState] = useState<ThemePreference>(readStoredPreference);
  /** Bumps when OS theme changes while preference is "system" (forces effective recalculation). */
  const [mediaEpoch, setMediaEpoch] = useState(0);

  useEffect(() => {
    applyThemeToDocument(preference);
    try {
      localStorage.setItem(STORAGE_KEY, preference);
    } catch {
      /* ignore */
    }
  }, [preference]);

  useEffect(() => {
    if (preference !== "system") return;
    const mql = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => {
      setMediaEpoch((n) => n + 1);
      applyThemeToDocument("system");
    };
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, [preference]);

  const effective: "light" | "dark" = useMemo(
    () => (resolveIsDark(preference) ? "dark" : "light"),
    /* eslint-disable-next-line react-hooks/exhaustive-deps -- `mediaEpoch` bumps on system scheme change */
    [preference, mediaEpoch],
  );

  const setPreference = useCallback((p: ThemePreference) => {
    setPreferenceState(p);
    queueMicrotask(() => applyThemeToDocument(p));
  }, []);

  const value = useMemo(
    () => ({ preference, setPreference, effective }),
    [preference, setPreference, effective],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used within ThemeProvider");
  return ctx;
}
