import { useState } from "react";
import { AppProvider, useApp } from "./state/store";
import { Sidebar } from "./components/Sidebar";
import { Topbar } from "./components/Topbar";
import { DossierView } from "./components/DossierView";
import { RoutineView } from "./components/RoutineView";
import { TraceView } from "./components/TraceView";
import { AutoDocView } from "./components/AutoDocView";
import { ChatPanel } from "./components/ChatPanel";
import { PanelRightOpen } from "lucide-react";

function MainView() {
  const { view } = useApp();
  switch (view.kind) {
    case "dossier":
      return <DossierView />;
    case "routine":
      return <RoutineView key={`${view.program}/${view.routine}`} view={view} />;
    case "trace":
      return <TraceView key={view.tag} tag={view.tag} />;
    case "autodoc":
      return <AutoDocView />;
  }
}

function Shell() {
  const { loading, error, dossier } = useApp();
  const [chatOpen, setChatOpen] = useState(true);

  if (error) {
    return (
      <div className="flex h-full items-center justify-center p-8">
        <div className="max-w-md rounded-lg border border-blocked/40 bg-surface p-6 text-center">
          <div className="text-blocked font-semibold">Backend unreachable</div>
          <p className="mt-2 text-sm text-muted">{error}</p>
          <p className="mt-3 text-xs text-faint font-mono">
            ASKPLC_MOCK=1 ./l5x-copilot/.venv/bin/python -m uvicorn app.backend.server:app --port 8000
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col bg-base">
      <Topbar />
      <div className="flex min-h-0 flex-1">
        <Sidebar />
        <main className="min-w-0 flex-1 overflow-auto bg-grid">
          {loading && !dossier ? (
            <div className="flex h-full items-center justify-center text-muted">
              <span className="animate-power">parsing L5X…</span>
            </div>
          ) : (
            <MainView />
          )}
        </main>
        {chatOpen ? (
          <ChatPanel onCollapse={() => setChatOpen(false)} />
        ) : (
          <button
            onClick={() => setChatOpen(true)}
            title="Open chat"
            className="flex w-10 shrink-0 flex-col items-center gap-2 border-l border-line bg-surface py-3 text-muted hover:text-accent"
          >
            <PanelRightOpen size={18} />
            <span className="mt-1 [writing-mode:vertical-rl] text-[11px] uppercase tracking-widest">
              Ask the PLC
            </span>
          </button>
        )}
      </div>
    </div>
  );
}

export default function App() {
  return (
    <AppProvider>
      <Shell />
    </AppProvider>
  );
}
