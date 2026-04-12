import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export type PageMeta = {
  title: string;
  subtitle?: string;
};

type Ctx = {
  meta: PageMeta | null;
  setPageMeta: (m: PageMeta | null) => void;
};

const PageMetaContext = createContext<Ctx | null>(null);

export function PageMetaProvider({ children }: { children: ReactNode }) {
  const [meta, setMeta] = useState<PageMeta | null>(null);
  const setPageMeta = useCallback((m: PageMeta | null) => setMeta(m), []);
  const value = useMemo(() => ({ meta, setPageMeta }), [meta, setPageMeta]);
  return <PageMetaContext.Provider value={value}>{children}</PageMetaContext.Provider>;
}

export function usePageMetaSetter() {
  const ctx = useContext(PageMetaContext);
  if (!ctx) throw new Error("usePageMetaSetter must be used within PageMetaProvider");
  return ctx.setPageMeta;
}

export function usePageMeta(): PageMeta | null {
  const ctx = useContext(PageMetaContext);
  return ctx?.meta ?? null;
}

/** Register page title in top bar; cleared on unmount. */
export function useRegisterPageMeta(meta: PageMeta | null) {
  const setPageMeta = usePageMetaSetter();
  useEffect(() => {
    setPageMeta(meta);
    return () => setPageMeta(null);
  }, [meta, setPageMeta]);
}
