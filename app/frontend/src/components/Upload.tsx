/**
 * Upload.tsx — bring-your-own-L5X front door.
 *
 * Three pieces, all driven by store.upload():
 *   UploadButton   — compact "Open .L5X" button (topbar / empty states)
 *   DropOverlay    — window-level drag-and-drop target; drop an .L5X anywhere
 *   UploadErrorBar — dismissible parse-failure banner (bad files are a normal
 *                    user event, not an app error)
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useApp } from "../state/store";
import { cx } from "./ui";
import { FileUp, Loader2, X } from "lucide-react";

export function UploadButton({ className }: { className?: string }) {
  const { upload, uploading } = useApp();
  const inputRef = useRef<HTMLInputElement>(null);

  return (
    <>
      <input
        ref={inputRef}
        type="file"
        accept=".l5x,.L5X,.xml"
        className="hidden"
        data-testid="upload-input"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) void upload(f);
          e.target.value = ""; // allow re-selecting the same file
        }}
      />
      <button
        onClick={() => inputRef.current?.click()}
        disabled={uploading}
        title="Open a Rockwell .L5X export"
        className={cx(
          "flex items-center gap-1.5 rounded border border-accent-dim bg-accent/10 px-2.5 py-1",
          "text-[11px] font-medium text-accent transition-colors hover:bg-accent/20",
          "disabled:cursor-wait disabled:opacity-60",
          className
        )}
      >
        {uploading ? <Loader2 size={13} className="animate-spin" /> : <FileUp size={13} />}
        {uploading ? "parsing…" : "Open .L5X"}
      </button>
    </>
  );
}

/** Full-window drag-and-drop. Renders nothing until a file is dragged in. */
export function DropOverlay() {
  const { upload, uploading } = useApp();
  const [dragging, setDragging] = useState(false);
  // dragenter/leave fire for every child element — count to know when we
  // actually left the window.
  const depth = useRef(0);

  const onDrop = useCallback(
    (e: DragEvent) => {
      e.preventDefault();
      depth.current = 0;
      setDragging(false);
      const f = e.dataTransfer?.files?.[0];
      if (f && !uploading) void upload(f);
    },
    [upload, uploading]
  );

  useEffect(() => {
    const enter = (e: DragEvent) => {
      if (!e.dataTransfer?.types.includes("Files")) return;
      depth.current += 1;
      setDragging(true);
    };
    const leave = () => {
      depth.current = Math.max(0, depth.current - 1);
      if (depth.current === 0) setDragging(false);
    };
    const over = (e: DragEvent) => e.preventDefault(); // required to allow drop
    window.addEventListener("dragenter", enter);
    window.addEventListener("dragleave", leave);
    window.addEventListener("dragover", over);
    window.addEventListener("drop", onDrop);
    return () => {
      window.removeEventListener("dragenter", enter);
      window.removeEventListener("dragleave", leave);
      window.removeEventListener("dragover", over);
      window.removeEventListener("drop", onDrop);
    };
  }, [onDrop]);

  if (!dragging) return null;
  return (
    <div
      data-testid="drop-overlay"
      className="pointer-events-none fixed inset-0 z-50 grid place-items-center bg-base/80 backdrop-blur-sm"
    >
      <div className="rounded-xl border-2 border-dashed border-accent bg-surface px-10 py-8 text-center">
        <FileUp size={28} className="mx-auto text-accent" />
        <div className="mt-3 font-semibold text-ink">Drop the .L5X export</div>
        <div className="mt-1 text-sm text-muted">parsed locally, chat-ready in seconds</div>
      </div>
    </div>
  );
}

export function UploadErrorBar() {
  const { uploadError, clearUploadError } = useApp();
  if (!uploadError) return null;
  return (
    <div
      data-testid="upload-error"
      className="flex items-center justify-between gap-3 border-b border-blocked/40 bg-blocked/10 px-4 py-2 text-sm text-blocked"
    >
      <span className="min-w-0 truncate">{uploadError}</span>
      <button onClick={clearUploadError} className="shrink-0 hover:text-ink" title="dismiss">
        <X size={14} />
      </button>
    </div>
  );
}
