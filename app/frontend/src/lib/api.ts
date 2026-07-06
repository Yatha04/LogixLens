/**
 * api.ts — typed client for the Ask-the-PLC FastAPI backend.
 *
 * In the browser, requests go to same-origin `/api/...` (Vite proxies to the
 * backend on :8000). Tests/tools can point elsewhere via `setApiBase`.
 */

import type {
  SessionResponse,
  Dossier,
  RoutinePayload,
  RungPayload,
  TracePayload,
  Audience,
  ChatFrame,
  AutodocResponse,
  LiveStatus,
  ChaosFault,
} from "./types";

let API_BASE = "";
let WS_BASE = ""; // empty => derive from window.location

export function setApiBase(httpBase: string, wsBase?: string) {
  API_BASE = httpBase.replace(/\/$/, "");
  if (wsBase) WS_BASE = wsBase.replace(/\/$/, "");
}

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, `${path} -> ${res.status}: ${detail}`);
  }
  return res.json() as Promise<T>;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

const enc = encodeURIComponent;

export async function createSession(opts: {
  l5x?: string;
  snapshot?: string | null;
  live?: boolean;
  opcua_url?: string;
} = {}): Promise<SessionResponse> {
  const res = await fetch(`${API_BASE}/api/session`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      l5x: opts.l5x,
      snapshot: opts.snapshot ?? undefined,
      live: opts.live ?? undefined,
      opcua_url: opts.opcua_url ?? undefined,
    }),
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, `/api/session -> ${res.status}: ${detail}`);
  }
  return res.json();
}

/** Upload an .L5X file; the backend parses it and returns a ready session. */
export async function uploadL5x(file: File): Promise<SessionResponse> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API_BASE}/api/upload`, { method: "POST", body: form });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json();
}

// ── Live cell (status + chaos proxy) ─────────────────────────────────────
export const getLiveStatus = (sid: string) =>
  getJSON<LiveStatus>(`/api/live/${enc(sid)}/status`);

async function postJSON<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) throw new ApiError(res.status, `${path} -> ${res.status}`);
  return res.json() as Promise<T>;
}

export const injectChaos = (sid: string, fault: ChaosFault) =>
  postJSON<LiveStatus>(`/api/live/${enc(sid)}/chaos`, { fault });

export const clearChaos = (sid: string) =>
  postJSON<LiveStatus>(`/api/live/${enc(sid)}/chaos/clear`);

export const getDossier = (sid: string) => getJSON<Dossier>(`/api/dossier/${enc(sid)}`);

export const getRoutine = (sid: string, program: string, routine: string) =>
  getJSON<RoutinePayload>(`/api/routine/${enc(sid)}/${enc(program)}/${enc(routine)}`);

export function getRung(
  sid: string,
  program: string,
  routine: string,
  number: number,
  snapshot?: string | null
): Promise<RungPayload> {
  const q = snapshot ? `?snapshot=${enc(snapshot)}` : "";
  return getJSON<RungPayload>(
    `/api/rung/${enc(sid)}/${enc(program)}/${enc(routine)}/${number}${q}`
  );
}

export function getTrace(
  sid: string,
  tag: string,
  snapshot?: string | null
): Promise<TracePayload> {
  const q = snapshot ? `?snapshot=${enc(snapshot)}` : "";
  return getJSON<TracePayload>(`/api/trace/${enc(sid)}/${enc(tag)}${q}`);
}

export interface TagHit {
  name: string;
  data_type: string;
  scope: string;
  description: string;
}
export const searchTags = (sid: string, q: string, limit = 15) =>
  getJSON<{ total: number; tags: TagHit[] }>(
    `/api/tags/${enc(sid)}?q=${enc(q)}&limit=${limit}`
  );

// ── Auto-doc ─────────────────────────────────────────────────────────────
export async function generateAutodoc(sid: string, tags?: string[]): Promise<AutodocResponse> {
  const res = await fetch(`${API_BASE}/api/autodoc/${enc(sid)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tags: tags ?? undefined }),
  });
  if (!res.ok) throw new ApiError(res.status, `/api/autodoc/${sid} -> ${res.status}`);
  return res.json();
}

/** Direct download URL for the reviewed autodoc table (browser navigates/opens it). */
export const autodocExportUrl = (sid: string) => `${API_BASE}/api/autodoc/${enc(sid)}/export.csv`;

// ── Chat WebSocket ──────────────────────────────────────────────────────
export interface ChatHandle {
  send: (message: string, audience: Audience) => void;
  close: () => void;
}

function wsUrl(sid: string): string {
  if (WS_BASE) return `${WS_BASE}/api/chat/${enc(sid)}`;
  if (API_BASE) {
    return `${API_BASE.replace(/^http/, "ws")}/api/chat/${enc(sid)}`;
  }
  const loc = window.location;
  const proto = loc.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${loc.host}/api/chat/${enc(sid)}`;
}

/**
 * Open a chat WebSocket. `onFrame` receives every streamed frame; `onOpen` and
 * `onClose` are optional lifecycle hooks.
 */
export function openChat(
  sid: string,
  onFrame: (frame: ChatFrame) => void,
  hooks: { onOpen?: () => void; onClose?: () => void; onError?: (e: Event) => void } = {}
): ChatHandle {
  const ws = new WebSocket(wsUrl(sid));
  ws.onopen = () => hooks.onOpen?.();
  ws.onclose = () => hooks.onClose?.();
  ws.onerror = (e) => hooks.onError?.(e);
  ws.onmessage = (ev) => {
    try {
      onFrame(JSON.parse(ev.data) as ChatFrame);
    } catch {
      /* ignore malformed */
    }
  };
  return {
    send: (message, audience) => {
      const doSend = () => ws.send(JSON.stringify({ message, audience }));
      if (ws.readyState === WebSocket.OPEN) doSend();
      else ws.addEventListener("open", doSend, { once: true });
    },
    close: () => ws.close(),
  };
}
