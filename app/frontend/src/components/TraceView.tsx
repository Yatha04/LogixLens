/**
 * TraceView — center-column wrapper around the InterlockTree panel.
 *
 * The interlock tree (collapsible AND/OR condition tree with tri-state icons,
 * the failing-path / root-cause banner, and clickable cite chips) lives in
 * InterlockTree; this wrapper just frames it as a main view and is what the
 * App router renders for `{ kind: "trace", tag }`.
 */
import InterlockTree from "./InterlockTree";

export function TraceView({ tag }: { tag: string }) {
  return (
    <div className="mx-auto flex h-full max-w-4xl flex-col">
      <InterlockTree tag={tag} />
    </div>
  );
}

export default TraceView;
