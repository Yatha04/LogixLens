import { useApp } from "../state/store";
import { Panel, Stat, cx } from "./ui";
import { Cpu, Gauge, FileText, Cable, MessageSquareWarning, Search } from "lucide-react";

const EXAMPLES = [
  "Why won't the press cycle?",
  "What writes to Press_Cycle_Start?",
  "Explain rung 9 of R30_PressCycle like I'm a new operator",
  "What is FB_VALVE and where is it used?",
];

export function DossierView() {
  const { dossier, prefillChat, openTrace } = useApp();
  if (!dossier) return null;
  const { controller: c, counts, documentation: doc, aoi_instances, modules } = dossier;

  const anatomy = Object.entries(aoi_instances).filter(([, v]) => v.length > 0);
  const coverageTone = doc.coverage_pct >= 80 ? "text-live" : doc.coverage_pct >= 50 ? "text-warn" : "text-blocked";

  return (
    <div className="mx-auto max-w-5xl space-y-4 p-5">
      {/* Controller card */}
      <div className="rounded-lg border border-line bg-gradient-to-br from-surface2 to-surface p-5">
        <div className="flex items-start justify-between">
          <div>
            <div className="flex items-center gap-2 text-[11px] uppercase tracking-widest text-accent">
              <Cpu size={14} /> Machine Dossier
            </div>
            <h1 className="mt-1 font-mono text-2xl font-bold text-ink">{c.name}</h1>
            <p className="mt-1 text-sm text-muted">
              {c.processor_type} · firmware v{c.major_revision}.{c.minor_revision}
              {c.software_revision ? ` · ${c.software_revision}` : ""}
            </p>
          </div>
          <div className="text-right text-xs text-faint">
            <div>{counts.programs} programs</div>
            <div>{counts.parsed_rungs} rungs parsed</div>
          </div>
        </div>
      </div>

      {/* Example chips row -> pre-fill chat */}
      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-accent-dim/40 bg-accent/5 px-4 py-3">
        <MessageSquareWarning size={16} className="text-accent" />
        <span className="text-sm text-ink">Ask the PLC:</span>
        {EXAMPLES.map((q) => (
          <button
            key={q}
            onClick={() => prefillChat(q)}
            className="rounded-full border border-line2 bg-surface px-3 py-1 text-xs text-muted transition-colors hover:border-accent hover:text-accent"
          >
            {q}
          </button>
        ))}
      </div>

      {/* Health strip */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Tags" value={counts.tags} sub={`${doc.unused_tags} unused`} />
        <Stat
          label="Doc Coverage"
          value={<span className={coverageTone}>{doc.coverage_pct}%</span>}
          sub={`${doc.undocumented_tags} undocumented`}
        />
        <Stat
          label="Routines"
          value={counts.routines}
          sub={`${counts.rll_routines} RLL · ${counts.st_routines} ST · ${counts.sfc_routines} SFC`}
        />
        <Stat label="I/O Modules" value={counts.modules} sub={`${counts.aois} AOIs · ${counts.udts} UDTs`} />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* Anatomy */}
        <Panel title={<span className="flex items-center gap-1.5"><Gauge size={13} /> Machine Anatomy</span>}>
          <p className="mb-3 text-xs text-muted">
            Inferred from AOI instances — every tag of an AOI type is a physical component.
          </p>
          <div className="space-y-3">
            {anatomy.map(([type, names]) => (
              <div key={type} className="rounded-md border border-line bg-surface2/50 p-2.5">
                <div className="flex items-center justify-between">
                  <span className="font-mono text-sm text-accent">{type}</span>
                  <span className="text-[10px] text-faint">{names.length} instance{names.length > 1 ? "s" : ""}</span>
                </div>
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  {names.map((n) => (
                    <button
                      key={n}
                      onClick={() => openTrace(n)}
                      title={`Trace ${n}`}
                      className="rounded border border-line2 px-1.5 py-0.5 font-mono text-[11px] text-muted hover:border-accent hover:text-accent"
                    >
                      {n}
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </Panel>

        {/* Modules + trace shortcut */}
        <div className="space-y-4">
          <Panel title={<span className="flex items-center gap-1.5"><Cable size={13} /> I/O Modules</span>}>
            <ul className="space-y-1.5 text-sm">
              {modules.map((m) => (
                <li key={m.name} className="flex items-center justify-between gap-2">
                  <span className="truncate font-mono text-ink">{m.name}</span>
                  <span className="shrink-0 font-mono text-[11px] text-muted">{m.catalog_number}</span>
                </li>
              ))}
              {modules.length === 0 && <li className="text-muted">none declared</li>}
            </ul>
          </Panel>

          <Panel title={<span className="flex items-center gap-1.5"><Search size={13} /> Diagnose an output</span>}>
            <p className="mb-2 text-xs text-muted">Trace what it takes for an output to go true.</p>
            <div className="flex flex-wrap gap-1.5">
              {["Press_Cycle_Start", "System_Running", "Safety_OK"].map((t) => (
                <button
                  key={t}
                  onClick={() => openTrace(t)}
                  className={cx(
                    "rounded border border-line2 px-2 py-1 font-mono text-xs text-muted",
                    "hover:border-accent hover:text-accent"
                  )}
                >
                  {t}
                </button>
              ))}
            </div>
          </Panel>
        </div>
      </div>

      <div className="flex items-center gap-1.5 pt-1 text-xs text-faint">
        <FileText size={12} /> Deterministic static analysis · every answer carries a rung citation
      </div>
    </div>
  );
}
