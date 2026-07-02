import { useState } from "react";
import { useApp } from "../state/store";
import { cx, RoutineTypeTag } from "./ui";
import { ChevronRight, FolderTree, Boxes, Component } from "lucide-react";

export function Sidebar() {
  const { dossier, view, openRoutine } = useApp();
  if (!dossier) return <aside className="w-64 shrink-0 border-r border-line bg-surface" />;

  const activeRoutine =
    view.kind === "routine" ? `${view.program}/${view.routine}` : null;

  return (
    <aside className="flex w-64 shrink-0 flex-col overflow-y-auto border-r border-line bg-surface">
      <div className="flex items-center gap-2 px-3 py-2 text-[11px] font-semibold uppercase tracking-wider text-muted">
        <FolderTree size={13} /> Controller Organizer
      </div>

      <div className="px-1.5 pb-3">
        {dossier.programs.map((prog) => (
          <ProgramNode
            key={prog.name}
            name={prog.name}
            disabled={prog.disabled}
            main={prog.main_routine}
            routines={prog.routines.map((r) => ({ name: r.name, type: r.type }))}
            activeRoutine={activeRoutine}
            onOpen={(routine) => openRoutine(prog.name, routine)}
          />
        ))}
      </div>

      <AnatomyPanel instances={dossier.aoi_instances} />
    </aside>
  );
}

function ProgramNode({
  name,
  disabled,
  main,
  routines,
  activeRoutine,
  onOpen,
}: {
  name: string;
  disabled: boolean;
  main: string | null;
  routines: { name: string; type: string }[];
  activeRoutine: string | null;
  onOpen: (routine: string) => void;
}) {
  const [open, setOpen] = useState(true);
  return (
    <div className="mb-0.5">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-1 rounded px-1.5 py-1 text-left text-[13px] text-ink hover:bg-surface2"
      >
        <ChevronRight size={13} className={cx("text-faint transition-transform", open && "rotate-90")} />
        <Boxes size={13} className="text-accent/70" />
        <span className="truncate font-medium">{name}</span>
        {disabled && <span className="ml-auto text-[9px] text-warn">disabled</span>}
      </button>
      {open && (
        <ul className="ml-4 border-l border-line pl-1.5">
          {routines.map((r) => {
            const id = `${name}/${r.name}`;
            const active = id === activeRoutine;
            return (
              <li key={r.name}>
                <button
                  onClick={() => onOpen(r.name)}
                  className={cx(
                    "flex w-full items-center gap-1.5 rounded px-1.5 py-1 text-left text-[12px]",
                    active ? "bg-accent/10 text-accent" : "text-muted hover:bg-surface2 hover:text-ink"
                  )}
                >
                  <RoutineTypeTag type={r.type} />
                  <span className="truncate font-mono">{r.name}</span>
                  {main === r.name && <span className="ml-auto text-[9px] text-faint">main</span>}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function AnatomyPanel({ instances }: { instances: Record<string, string[]> }) {
  const groups = Object.entries(instances).filter(([, v]) => v.length > 0);
  if (groups.length === 0) return null;
  return (
    <div className="mt-auto border-t border-line px-3 py-2">
      <div className="mb-1.5 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider text-muted">
        <Component size={13} /> Machine Anatomy
      </div>
      <div className="space-y-2">
        {groups.map(([type, names]) => (
          <div key={type}>
            <div className="text-[10px] font-mono text-accent/80">
              {type} <span className="text-faint">×{names.length}</span>
            </div>
            <div className="mt-0.5 flex flex-wrap gap-1">
              {names.map((n) => (
                <span
                  key={n}
                  title={`${n} : ${type}`}
                  className="truncate rounded bg-surface2 px-1.5 py-0.5 text-[10px] font-mono text-muted"
                >
                  {n}
                </span>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
