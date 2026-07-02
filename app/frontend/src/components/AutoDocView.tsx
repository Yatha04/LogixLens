/**
 * AutoDocView — the "leave-behind" auto-documentation mode.
 *
 * Reached from the Dossier's Doc Coverage stat card. Lists every undocumented
 * tag (via /api/tags, filtered to an empty description client-side), lets the
 * reviewer generate LLM-drafted descriptions in one batch (POST
 * /api/autodoc/{sid}, which internally batches ~30 tags/call and is
 * confidence-rated), and exports the reviewed table as CSV.
 */

import { useEffect, useState } from "react";
import { AlertTriangle, ArrowLeft, Download, FileEdit, Loader2, Sparkles } from "lucide-react";
import { autodocExportUrl, generateAutodoc, searchTags } from "../lib/api";
import type { AutodocProposal, Confidence } from "../lib/types";
import { useApp } from "../state/store";
import { Chip, cx, Panel } from "./ui";

interface Row {
  tag: string;
  data_type: string;
  scope: string;
}

const CONFIDENCE_TONE: Record<Confidence, string> = {
  high: "border-live/40 text-live",
  medium: "border-warn/40 text-warn",
  low: "border-line2 text-faint",
};

function ConfidenceBadge({ confidence }: { confidence: Confidence }) {
  return (
    <span
      className={cx(
        "rounded border px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wider",
        CONFIDENCE_TONE[confidence]
      )}
    >
      {confidence}
    </span>
  );
}

export function AutoDocView() {
  const { sid, openDossier, mock } = useApp();
  const [rows, setRows] = useState<Row[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [proposals, setProposals] = useState<Record<string, AutodocProposal>>({});
  const [generating, setGenerating] = useState(false);
  const [mode, setMode] = useState<"mock" | "real" | null>(null);

  useEffect(() => {
    if (!sid) return;
    let cancelled = false;
    setRows(null);
    setError(null);
    setProposals({});
    // No dedicated "list undocumented tags" endpoint; reuse the tag-search
    // tool with an empty query (matches every tag) and filter client-side.
    searchTags(sid, "", 2000)
      .then((res) => {
        if (cancelled) return;
        const undocumented = res.tags
          .filter((t) => !t.description)
          .map((t) => ({ tag: t.name, data_type: t.data_type, scope: t.scope }));
        setRows(undocumented);
      })
      .catch((e) => !cancelled && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      cancelled = true;
    };
  }, [sid]);

  const generate = async () => {
    if (!sid || !rows || rows.length === 0) return;
    setGenerating(true);
    setError(null);
    try {
      const res = await generateAutodoc(
        sid,
        rows.map((r) => r.tag)
      );
      setMode(res.mode);
      const next: Record<string, AutodocProposal> = {};
      for (const p of res.proposals) next[p.tag] = p;
      setProposals(next);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setGenerating(false);
    }
  };

  const generatedCount = Object.keys(proposals).length;
  const total = rows?.length ?? 0;

  return (
    <div className="mx-auto max-w-5xl space-y-4 p-5">
      <div className="flex items-center justify-between">
        <button
          onClick={openDossier}
          className="flex items-center gap-1.5 text-xs text-muted hover:text-accent"
        >
          <ArrowLeft size={13} /> Back to Dossier
        </button>
        {mode && (
          <span
            className={cx(
              "rounded border px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider",
              mode === "mock" ? "border-warn/40 text-warn" : "border-accent-dim text-accent"
            )}
          >
            {mode} mode
          </span>
        )}
      </div>

      <div className="rounded-lg border border-line bg-gradient-to-br from-surface2 to-surface p-5">
        <div className="flex items-center gap-2 text-[11px] uppercase tracking-widest text-accent">
          <FileEdit size={14} /> Auto-Doc
        </div>
        <h1 className="mt-1 text-xl font-bold text-ink">Undocumented tag review</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted">
          Every tag below has no description in the source program. Generate proposes a
          short description per tag from its name and how it's used in logic (rung
          citations included) — review, then export the table as a CSV a tech can drop
          straight into the tag database.
        </p>
        <div className="mt-3 flex items-center gap-2">
          <button
            onClick={generate}
            disabled={generating || !rows || rows.length === 0}
            className="flex items-center gap-1.5 rounded border border-accent-dim bg-accent/10 px-3 py-1.5 text-xs font-semibold text-accent transition-colors hover:bg-accent/20 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {generating ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />}
            {generating ? "Generating…" : `Generate (${total} tag${total === 1 ? "" : "s"})`}
          </button>
          <a
            href={sid ? autodocExportUrl(sid) : undefined}
            aria-disabled={generatedCount === 0}
            download
            className={cx(
              "flex items-center gap-1.5 rounded border px-3 py-1.5 text-xs font-semibold transition-colors",
              generatedCount === 0
                ? "pointer-events-none border-line2 text-faint opacity-40"
                : "border-line2 text-ink hover:border-accent hover:text-accent"
            )}
          >
            <Download size={13} /> Export CSV
          </a>
          {generatedCount > 0 && (
            <span className="text-[11px] text-muted">
              {generatedCount} of {total} proposed
            </span>
          )}
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-2 rounded border border-blocked/40 bg-blocked/10 p-3 text-sm text-blocked">
          <AlertTriangle size={16} /> {error}
        </div>
      )}

      <Panel title="Tags">
        {!rows && !error && (
          <div className="flex items-center gap-2 p-2 text-sm text-muted">
            <Loader2 size={16} className="animate-spin" /> loading undocumented tags…
          </div>
        )}
        {rows && rows.length === 0 && (
          <div className="p-2 text-sm text-muted">
            Every tag already has a description — nothing to document.
          </div>
        )}
        {rows && rows.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-[12px]">
              <thead>
                <tr className="border-b border-line text-[10px] uppercase tracking-wider text-faint">
                  <th className="py-1.5 pr-3 font-medium">Tag</th>
                  <th className="py-1.5 pr-3 font-medium">Type</th>
                  <th className="py-1.5 pr-3 font-medium">Scope</th>
                  <th className="py-1.5 pr-3 font-medium">Proposed description</th>
                  <th className="py-1.5 pr-3 font-medium">Confidence</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const p = proposals[r.tag];
                  return (
                    <tr key={r.tag} className="border-b border-line/50 last:border-0">
                      <td className="py-1.5 pr-3 font-mono text-ink">{r.tag}</td>
                      <td className="py-1.5 pr-3 font-mono text-[11px] text-muted">{r.data_type}</td>
                      <td className="py-1.5 pr-3 text-[11px] text-muted">{r.scope}</td>
                      <td className="py-1.5 pr-3 text-ink/90">
                        {p ? (
                          p.proposed_description
                        ) : (
                          <span className="text-faint">— not generated yet —</span>
                        )}
                      </td>
                      <td className="py-1.5 pr-3">
                        {p ? <ConfidenceBadge confidence={p.confidence} /> : <Chip>pending</Chip>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      {mock && (
        <p className="text-[11px] text-faint">
          Mock mode: proposals are a deterministic name-split heuristic (always low
          confidence) — the same pipeline the real Anthropic-backed path runs, without a
          network call.
        </p>
      )}
    </div>
  );
}

export default AutoDocView;
