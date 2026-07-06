import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { createSession, getDossier, uploadL5x } from "../lib/api";
import type { Audience, Dossier, SessionResponse } from "../lib/types";

export type ConnState = "connected" | "connecting" | "disconnected";

export interface SnapshotOption {
  id: string | null;
  label: string;
  tone: "healthy" | "fault" | "static";
}

export const SNAPSHOTS: SnapshotOption[] = [
  { id: "healthy", label: "healthy", tone: "healthy" },
  { id: "guard_door_open", label: "guard_door_open", tone: "fault" },
  { id: null, label: "no snapshot", tone: "static" },
];

/** Sentinel `<select>` value for the live OPC UA source (distinct from any
 * snapshot id, and from "" which means "no snapshot"). */
export const LIVE_SOURCE = "__live__";

export interface SourceOption {
  id: string; // snapshot id, "" == no snapshot, LIVE_SOURCE == live cell
  label: string;
  tone: "healthy" | "fault" | "static" | "live";
}

export const SOURCES: SourceOption[] = [
  { id: "healthy", label: "healthy", tone: "healthy" },
  { id: "guard_door_open", label: "guard_door_open", tone: "fault" },
  { id: "", label: "no snapshot", tone: "static" },
  { id: LIVE_SOURCE, label: "LIVE (OPC UA)", tone: "live" },
];

export type View =
  | { kind: "dossier" }
  | { kind: "routine"; program: string; routine: string; highlightRung?: number }
  | { kind: "trace"; tag: string }
  | { kind: "autodoc" };

// ── Hash routing ─────────────────────────────────────────────────────────
// The view is mirrored into location.hash so every screen is linkable and
// back/forward work. The hash is a projection of view state, not the source
// of truth: navigation sets state synchronously (tests stay synchronous) and
// pushes the hash; a hashchange (back/forward, hand-edited URL) syncs back.

const enc = encodeURIComponent;

export function viewToHash(v: View): string {
  switch (v.kind) {
    case "dossier":
      return "#/";
    case "routine":
      return (
        `#/routine/${enc(v.program)}/${enc(v.routine)}` +
        (v.highlightRung != null ? `/r${v.highlightRung}` : "")
      );
    case "trace":
      return `#/trace/${enc(v.tag)}`;
    case "autodoc":
      return "#/autodoc";
  }
}

export function hashToView(hash: string): View {
  const parts = hash
    .replace(/^#\/?/, "")
    .split("/")
    .filter(Boolean)
    .map(decodeURIComponent);
  if (parts[0] === "routine" && parts[1] && parts[2]) {
    const m = /^r(\d+)$/.exec(parts[3] ?? "");
    return {
      kind: "routine",
      program: parts[1],
      routine: parts[2],
      highlightRung: m ? Number(m[1]) : undefined,
    };
  }
  if (parts[0] === "trace" && parts[1]) return { kind: "trace", tag: parts[1] };
  if (parts[0] === "autodoc") return { kind: "autodoc" };
  return { kind: "dossier" };
}

interface AppState {
  session: SessionResponse | null;
  dossier: Dossier | null;
  snapshot: string | null;
  live: boolean;
  view: View;
  loading: boolean;
  error: string | null;
  mock: boolean;
}

interface AppApi extends AppState {
  sid: string | null;
  /** Current source selector value (snapshot id, "" for none, or LIVE_SOURCE). */
  sourceId: string;
  /** Switch the value source — a snapshot id, "" (no snapshot), or LIVE_SOURCE. */
  switchSource: (id: string) => void;
  switchSnapshot: (id: string | null) => void;
  /** Upload an .L5X file and switch the whole app to it. */
  upload: (file: File) => Promise<void>;
  /** True while an upload is parsing. */
  uploading: boolean;
  /** Non-fatal upload failure (bad file) — shown inline, app keeps working. */
  uploadError: string | null;
  clearUploadError: () => void;
  /** Return to the bundled PressLine_3 demo cell. */
  loadDemo: () => void;
  openDossier: () => void;
  openRoutine: (program: string, routine: string, highlightRung?: number) => void;
  openTrace: (tag: string) => void;
  openAutodoc: () => void;
  /** Pre-fill the chat composer (used by the dossier example chips). */
  prefillChat: (text: string) => void;
  chatPrefill: { text: string; nonce: number } | null;
  /** Audience register sent with every chat message (Topbar toggle). */
  audience: Audience;
  setAudience: (a: Audience) => void;
  /** Chat WebSocket connection state (Topbar dot). */
  conn: ConnState;
  setConn: (c: ConnState) => void;
}

const Ctx = createContext<AppApi | null>(null);

export function AppProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<SessionResponse | null>(null);
  const [dossier, setDossier] = useState<Dossier | null>(null);
  const [snapshot, setSnapshot] = useState<string | null>("guard_door_open");
  const [live, setLive] = useState(false);
  const [view, setViewState] = useState<View>(() =>
    typeof window === "undefined" ? { kind: "dossier" } : hashToView(window.location.hash)
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [chatPrefill, setChatPrefill] = useState<{ text: string; nonce: number } | null>(null);
  const [audience, setAudience] = useState<Audience>("maintenance");
  const [conn, setConn] = useState<ConnState>("connecting");

  // Navigate: set state synchronously, then mirror into the hash (guarded so
  // the hashchange listener doesn't double-fire a state update).
  const selfHashWrite = useRef(false);
  const navigate = useCallback((v: View) => {
    setViewState(v);
    const h = viewToHash(v);
    if (window.location.hash !== h) {
      selfHashWrite.current = true;
      window.location.hash = h;
    }
  }, []);

  useEffect(() => {
    const onHashChange = () => {
      if (selfHashWrite.current) {
        selfHashWrite.current = false;
        return;
      }
      setViewState(hashToView(window.location.hash));
    };
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  const boot = useCallback(
    async (opts: { snapshot?: string | null; live?: boolean; l5x?: string }) => {
      setLoading(true);
      setError(null);
      try {
        const s = opts.live
          ? await createSession({ live: true, l5x: opts.l5x })
          : await createSession({ snapshot: opts.snapshot ?? null, l5x: opts.l5x });
        const d = await getDossier(s.session_id);
        setSession(s);
        setDossier(d);
        setLive(!!opts.live);
        setSnapshot(opts.live ? null : opts.snapshot ?? null);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setLoading(false);
      }
    },
    []
  );

  useEffect(() => {
    void boot({ snapshot: "guard_door_open" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const switchSource = useCallback(
    (id: string) => {
      // Any source change creates a fresh session (per spec) so live evaluation
      // and the chat context reflect the selected cell state. An uploaded file
      // stays loaded across source changes.
      const l5x = session?.uploaded ? session.l5x : undefined;
      if (id === LIVE_SOURCE) void boot({ live: true, l5x });
      else void boot({ snapshot: id || null, l5x });
    },
    [boot, session]
  );

  const upload = useCallback(
    async (file: File) => {
      setUploading(true);
      setUploadError(null);
      try {
        const s = await uploadL5x(file);
        const d = await getDossier(s.session_id);
        setSession(s);
        setDossier(d);
        setLive(false);
        setSnapshot(null);
        navigate({ kind: "dossier" });
      } catch (e) {
        setUploadError(e instanceof Error ? e.message : String(e));
      } finally {
        setUploading(false);
      }
    },
    [navigate]
  );

  const loadDemo = useCallback(() => {
    navigate({ kind: "dossier" });
    void boot({ snapshot: "guard_door_open" });
  }, [boot, navigate]);

  const switchSnapshot = useCallback(
    (id: string | null) => switchSource(id ?? ""),
    [switchSource]
  );

  const api = useMemo<AppApi>(
    () => ({
      session,
      dossier,
      snapshot,
      live,
      view,
      loading,
      error,
      mock: session?.mock ?? false,
      sid: session?.session_id ?? null,
      sourceId: live ? LIVE_SOURCE : snapshot ?? "",
      switchSource,
      switchSnapshot,
      upload,
      uploading,
      uploadError,
      clearUploadError: () => setUploadError(null),
      loadDemo,
      openDossier: () => navigate({ kind: "dossier" }),
      openRoutine: (program, routine, highlightRung) =>
        navigate({ kind: "routine", program, routine, highlightRung }),
      openTrace: (tag) => navigate({ kind: "trace", tag }),
      openAutodoc: () => navigate({ kind: "autodoc" }),
      prefillChat: (text) => setChatPrefill({ text, nonce: Date.now() }),
      chatPrefill,
      audience,
      setAudience,
      conn,
      setConn,
    }),
    [session, dossier, snapshot, live, view, loading, error, switchSource, switchSnapshot,
     upload, uploading, uploadError, loadDemo, navigate, chatPrefill, audience, conn]
  );

  return <Ctx.Provider value={api}>{children}</Ctx.Provider>;
}

export function useApp(): AppApi {
  const v = useContext(Ctx);
  if (!v) throw new Error("useApp must be used inside <AppProvider>");
  return v;
}
