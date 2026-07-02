/**
 * ChatPanel.tsx — the right-hand "Ask the PLC" column: streaming chat over the
 * /api/chat WebSocket. Renders markdown answers, tool breadcrumbs as subtle
 * inline chips ("traced blockers for Press_Cycle_Start — 1 failing path"),
 * and citations as clickable chips that open the ladder view at the cited
 * rung. Shows a hero card (controller + stats + suggested questions) until
 * the first message. Audience comes from the Topbar toggle via the store;
 * connection state feeds the Topbar dot.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { Cpu, PanelRightClose, Search, Send, Sparkles } from "lucide-react";
import { openChat, type ChatHandle } from "../lib/api";
import type { ChatFrame, Cite } from "../lib/types";
import { renderMarkdown } from "../lib/markdown";
import { useApp } from "../state/store";
import { CiteChip } from "./InterlockTree";

interface Breadcrumb {
  tool: string;
  text: string | null; // null until the tool_result_summary arrives
}

interface AssistantMsg {
  kind: "assistant";
  text: string;
  breadcrumbs: Breadcrumb[];
  citations: Cite[];
  done: boolean;
  error?: string;
}

interface UserMsg {
  kind: "user";
  text: string;
}

type ChatItem = AssistantMsg | UserMsg;

const SUGGESTIONS = [
  "Why is the press not cycling?",
  "What does this machine do?",
  "What would it take for Press_Cycle_Start to go true?",
];

export function ChatPanel({ onCollapse }: { onCollapse?: () => void }) {
  const {
    sid,
    dossier,
    snapshot,
    audience,
    setConn,
    chatPrefill,
    openRoutine,
  } = useApp();
  const [items, setItems] = useState<ChatItem[]>([]);
  const [draft, setDraft] = useState("");
  const [working, setWorking] = useState(false);
  const handle = useRef<ChatHandle | null>(null);
  const scroller = useRef<HTMLDivElement | null>(null);
  const input = useRef<HTMLTextAreaElement | null>(null);
  const audienceRef = useRef(audience);
  audienceRef.current = audience;

  // (re)connect the socket per session
  useEffect(() => {
    if (!sid) return;
    setConn("connecting");
    const h = openChat(sid, onFrame, {
      onOpen: () => setConn("connected"),
      onClose: () => setConn("disconnected"),
      onError: () => setConn("disconnected"),
    });
    handle.current = h;
    return () => {
      handle.current = null;
      h.close();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sid]);

  // dossier example chips pre-fill the composer
  useEffect(() => {
    if (chatPrefill) {
      setDraft(chatPrefill.text);
      input.current?.focus();
    }
  }, [chatPrefill]);

  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: "smooth" });
  }, [items, working]);

  function onFrame(frame: ChatFrame) {
    setItems((prev) => {
      const next = [...prev];
      const last = next[next.length - 1];
      if (!last || last.kind !== "assistant" || last.done) return next;
      const msg: AssistantMsg = { ...last };
      switch (frame.type) {
        case "text_delta":
          msg.text += frame.text;
          break;
        case "tool_call":
          msg.breadcrumbs = [...msg.breadcrumbs, { tool: frame.tool, text: null }];
          break;
        case "tool_result_summary": {
          const bc = [...msg.breadcrumbs];
          for (let i = bc.length - 1; i >= 0; i--) {
            if (bc[i].tool === frame.tool && bc[i].text === null) {
              bc[i] = { tool: frame.tool, text: frame.breadcrumb };
              break;
            }
          }
          msg.breadcrumbs = bc;
          break;
        }
        case "citations":
          msg.citations = frame.citations;
          break;
        case "done":
          msg.done = true;
          setWorking(false);
          break;
        case "error":
          msg.error = frame.message;
          msg.done = true;
          setWorking(false);
          break;
      }
      next[next.length - 1] = msg;
      return next;
    });
  }

  function send(text: string) {
    const t = text.trim();
    if (!t || !handle.current || working) return;
    setItems((prev) => [
      ...prev,
      { kind: "user", text: t },
      { kind: "assistant", text: "", breadcrumbs: [], citations: [], done: false },
    ]);
    setWorking(true);
    setDraft("");
    handle.current.send(t, audienceRef.current);
  }

  const hero = items.length === 0;
  const stats = useMemo(() => {
    if (!dossier) return [];
    return [
      { label: "tags", value: dossier.counts.tags },
      { label: "routines", value: dossier.counts.routines },
      { label: "rungs", value: dossier.counts.parsed_rungs },
      { label: "AOIs", value: dossier.counts.aois },
      { label: "modules", value: dossier.counts.modules },
      { label: "doc cov.", value: `${dossier.documentation.coverage_pct}%` },
    ];
  }, [dossier]);

  return (
    <aside className="flex w-[26rem] shrink-0 flex-col border-l border-line bg-surface">
      <div className="flex h-9 shrink-0 items-center justify-between border-b border-line px-3">
        <span className="text-[11px] font-semibold uppercase tracking-wider text-muted">
          Ask the PLC
        </span>
        {onCollapse && (
          <button onClick={onCollapse} title="Collapse chat" className="text-faint hover:text-ink">
            <PanelRightClose size={15} />
          </button>
        )}
      </div>

      <div ref={scroller} className="min-h-0 flex-1 overflow-y-auto px-3 py-3">
        {hero && dossier && (
          <div className="fade-up rounded-lg border border-line bg-surface2/60 p-4">
            <div className="flex items-center gap-2.5">
              <div className="rounded-md border border-accent/30 bg-accent/10 p-2 text-accent">
                <Cpu size={16} />
              </div>
              <div>
                <div className="font-mono text-[14px] font-semibold text-ink">
                  {dossier.controller.name}
                </div>
                <div className="text-[10.5px] text-muted">
                  {dossier.controller.processor_type}
                  {snapshot && (
                    <span className="ml-1.5 rounded bg-warn/15 px-1 py-[1px] font-mono text-[9px] text-warn">
                      {snapshot}
                    </span>
                  )}
                </div>
              </div>
            </div>

            <div className="mt-3 grid grid-cols-3 gap-1.5">
              {stats.map((s) => (
                <div key={s.label} className="rounded border border-line bg-surface px-2 py-1.5">
                  <div className="font-mono text-[13px] font-semibold text-ink">{s.value}</div>
                  <div className="text-[9px] uppercase tracking-wider text-faint">{s.label}</div>
                </div>
              ))}
            </div>

            <div className="mt-3 border-t border-line pt-2.5">
              <div className="mb-1.5 flex items-center gap-1.5 text-[9px] uppercase tracking-wider text-faint">
                <Sparkles size={10} /> try asking
              </div>
              <div className="flex flex-col gap-1.5">
                {SUGGESTIONS.map((s) => (
                  <button
                    key={s}
                    onClick={() => send(s)}
                    className="rounded border border-line bg-surface px-2.5 py-1.5 text-left text-[11.5px] text-ink/90 transition-colors hover:border-accent/50 hover:text-accent"
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}

        {items.map((item, idx) =>
          item.kind === "user" ? (
            <div key={idx} className="fade-up mb-3 flex justify-end">
              <div className="max-w-[88%] rounded-lg rounded-br-sm border border-accent/25 bg-accent/10 px-3 py-2 text-[12.5px] text-ink">
                {item.text}
              </div>
            </div>
          ) : (
            <div key={idx} className="fade-up mb-4">
              {item.breadcrumbs.length > 0 && (
                <div className="mb-1.5 flex flex-wrap gap-1.5">
                  {item.breadcrumbs.map((b, i) => (
                    <span
                      key={i}
                      className="inline-flex items-center gap-1 rounded-full border border-line bg-surface2 px-2 py-[2px] font-mono text-[9.5px] text-muted"
                    >
                      <Search size={9} className="shrink-0 text-faint" />
                      {b.text ?? `${b.tool}…`}
                    </span>
                  ))}
                </div>
              )}

              <div className="text-[12.5px] text-ink/90">
                {item.text ? renderMarkdown(item.text) : !item.done ? <WorkingDots /> : null}
                {!item.done && item.text && <span className="animate-power text-accent">▍</span>}
              </div>

              {item.error && (
                <div className="mt-1 rounded border border-blocked/40 bg-blocked/10 px-2 py-1 text-[11px] text-blocked">
                  {item.error}
                </div>
              )}

              {item.citations.length > 0 && (
                <div className="mt-2 flex flex-wrap items-center gap-1">
                  <span className="text-[9px] uppercase tracking-wider text-faint">cites</span>
                  {item.citations.map((c, i) => (
                    <CiteChip
                      key={i}
                      cite={c}
                      onClick={(cite) => openRoutine(cite.program, cite.routine, cite.rung_number)}
                    />
                  ))}
                </div>
              )}
            </div>
          ),
        )}
      </div>

      {/* composer */}
      <div className="border-t border-line px-2.5 py-2.5">
        <div className="flex items-end gap-2 rounded-lg border border-line bg-surface2 px-2.5 py-2 focus-within:border-accent/50">
          <textarea
            ref={input}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send(draft);
              }
            }}
            rows={Math.min(4, Math.max(1, draft.split("\n").length))}
            placeholder='Ask the PLC… ("why is the machine down?")'
            className="max-h-32 w-full resize-none bg-transparent text-[12.5px] text-ink outline-none placeholder:text-faint"
          />
          <button
            onClick={() => send(draft)}
            disabled={!draft.trim() || working}
            className="rounded-md border border-accent/40 bg-accent/15 p-1.5 text-accent transition-opacity disabled:opacity-30"
            title="Send (Enter)"
          >
            <Send size={13} />
          </button>
        </div>
        <div className="mt-1 px-1 text-[9.5px] text-faint">
          Enter to send · click a cite to open the rung in the ladder view
        </div>
      </div>
    </aside>
  );
}

function WorkingDots() {
  return (
    <span className="inline-flex items-center gap-1 text-muted">
      <span className="animate-power">●</span>
      <span className="animate-power" style={{ animationDelay: "0.2s" }}>
        ●
      </span>
      <span className="animate-power" style={{ animationDelay: "0.4s" }}>
        ●
      </span>
      <span className="ml-1 text-[11px]">working…</span>
    </span>
  );
}

export default ChatPanel;
