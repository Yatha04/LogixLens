import type { ReactNode } from "react";
import type { Satisfied } from "../lib/types";

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

/** Small tri-state status dot (green / red / grey). */
export function StateDot({ state, size = 8 }: { state: Satisfied; size?: number }) {
  const color =
    state === true ? "var(--color-live)" : state === false ? "var(--color-blocked)" : "var(--color-idle)";
  return (
    <span
      className="inline-block rounded-full shrink-0"
      style={{ width: size, height: size, background: color, boxShadow: state === true ? `0 0 8px ${color}` : undefined }}
    />
  );
}

export function Chip({
  children,
  onClick,
  tone = "default",
  title,
}: {
  children: ReactNode;
  onClick?: () => void;
  tone?: "default" | "accent" | "warn" | "danger";
  title?: string;
}) {
  const tones: Record<string, string> = {
    default: "border-line2 text-muted hover:text-ink hover:border-faint",
    accent: "border-accent-dim text-accent hover:border-accent",
    warn: "border-warn/40 text-warn",
    danger: "border-blocked/40 text-blocked",
  };
  const Comp = onClick ? "button" : "span";
  return (
    <Comp
      title={title}
      onClick={onClick}
      className={cx(
        "inline-flex items-center gap-1 rounded border px-2 py-0.5 text-[11px] font-mono transition-colors",
        tones[tone],
        onClick && "cursor-pointer"
      )}
    >
      {children}
    </Comp>
  );
}

export function Stat({
  label,
  value,
  sub,
  onClick,
  title,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  onClick?: () => void;
  title?: string;
}) {
  const Comp = onClick ? "button" : "div";
  return (
    <Comp
      onClick={onClick}
      title={title}
      className={cx(
        "rounded-lg border border-line bg-surface px-3 py-2.5 text-left",
        onClick && "cursor-pointer transition-colors hover:border-accent/60 hover:bg-surface2"
      )}
    >
      <div className="text-[10px] uppercase tracking-wider text-faint">{label}</div>
      <div className="mt-0.5 text-xl font-semibold tabular-nums text-ink">{value}</div>
      {sub !== undefined && <div className="text-[11px] text-muted">{sub}</div>}
    </Comp>
  );
}

export function Panel({
  title,
  right,
  children,
  className,
}: {
  title?: ReactNode;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cx("rounded-lg border border-line bg-surface", className)}>
      {title && (
        <header className="flex items-center justify-between border-b border-line px-3.5 py-2">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted">{title}</h3>
          {right}
        </header>
      )}
      <div className="p-3.5">{children}</div>
    </section>
  );
}

export function RoutineTypeTag({ type }: { type: string }) {
  const tones: Record<string, string> = {
    RLL: "text-accent border-accent-dim",
    ST: "text-warn border-warn/40",
    SFC: "text-[#7aa2ff] border-[#7aa2ff]/40",
  };
  return (
    <span className={cx("rounded border px-1 text-[9px] font-mono uppercase", tones[type] ?? "text-muted border-line2")}>
      {type}
    </span>
  );
}
