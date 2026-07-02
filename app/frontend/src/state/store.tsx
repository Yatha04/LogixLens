import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { createSession, getDossier } from "../lib/api";
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
  const [view, setView] = useState<View>({ kind: "dossier" });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [chatPrefill, setChatPrefill] = useState<{ text: string; nonce: number } | null>(null);
  const [audience, setAudience] = useState<Audience>("maintenance");
  const [conn, setConn] = useState<ConnState>("connecting");

  const boot = useCallback(async (opts: { snapshot?: string | null; live?: boolean }) => {
    setLoading(true);
    setError(null);
    try {
      const s = opts.live
        ? await createSession({ live: true })
        : await createSession({ snapshot: opts.snapshot ?? null });
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
  }, []);

  useEffect(() => {
    void boot({ snapshot: "guard_door_open" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const switchSource = useCallback(
    (id: string) => {
      // Any source change creates a fresh session (per spec) so live evaluation
      // and the chat context reflect the selected cell state.
      if (id === LIVE_SOURCE) void boot({ live: true });
      else void boot({ snapshot: id || null });
    },
    [boot]
  );

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
      openDossier: () => setView({ kind: "dossier" }),
      openRoutine: (program, routine, highlightRung) =>
        setView({ kind: "routine", program, routine, highlightRung }),
      openTrace: (tag) => setView({ kind: "trace", tag }),
      openAutodoc: () => setView({ kind: "autodoc" }),
      prefillChat: (text) => setChatPrefill({ text, nonce: Date.now() }),
      chatPrefill,
      audience,
      setAudience,
      conn,
      setConn,
    }),
    [session, dossier, snapshot, live, view, loading, error, switchSource, switchSnapshot, chatPrefill, audience, conn]
  );

  return <Ctx.Provider value={api}>{children}</Ctx.Provider>;
}

export function useApp(): AppApi {
  const v = useContext(Ctx);
  if (!v) throw new Error("useApp must be used inside <AppProvider>");
  return v;
}
