import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { AutoDocView } from "./AutoDocView";

const openDossier = vi.fn();

vi.mock("../state/store", () => ({
  useApp: () => ({ sid: "sess1", openDossier, mock: true }),
}));

vi.mock("../lib/api", () => ({
  searchTags: vi.fn(),
  generateAutodoc: vi.fn(),
  autodocExportUrl: (sid: string) => `/api/autodoc/${sid}/export.csv`,
}));

import { searchTags, generateAutodoc } from "../lib/api";

const TAGS = [
  { name: "GuardDoor_Closed", data_type: "BOOL", scope: "Controller", description: "" },
  { name: "Press_Cycle_Start", data_type: "BOOL", scope: "Controller", description: "documented already" },
];

describe("<AutoDocView /> smoke", () => {
  beforeEach(() => {
    vi.mocked(searchTags).mockReset();
    vi.mocked(generateAutodoc).mockReset();
    openDossier.mockReset();
  });

  it("lists only undocumented tags, filtering out documented ones", async () => {
    vi.mocked(searchTags).mockResolvedValue({ total: TAGS.length, tags: TAGS });
    render(<AutoDocView />);

    await waitFor(() => expect(screen.getByText("GuardDoor_Closed")).toBeInTheDocument());
    expect(screen.queryByText("Press_Cycle_Start")).not.toBeInTheDocument();
    expect(screen.getByText(/Generate \(1 tag\)/)).toBeInTheDocument();
  });

  it("fills in proposals with a confidence badge after Generate", async () => {
    vi.mocked(searchTags).mockResolvedValue({ total: TAGS.length, tags: TAGS });
    vi.mocked(generateAutodoc).mockResolvedValue({
      session_id: "sess1",
      mode: "mock",
      total: 1,
      proposals: [
        {
          tag: "GuardDoor_Closed",
          data_type: "BOOL",
          scope: "Controller",
          current_description: "",
          proposed_description: "Guard door closed (inferred from tag name).",
          confidence: "low",
        },
      ],
    });

    render(<AutoDocView />);
    await waitFor(() => expect(screen.getByText("GuardDoor_Closed")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /Generate/ }));

    await waitFor(() =>
      expect(screen.getByText("Guard door closed (inferred from tag name).")).toBeInTheDocument()
    );
    expect(screen.getByText("low")).toBeInTheDocument();
    expect(generateAutodoc).toHaveBeenCalledWith("sess1", ["GuardDoor_Closed"]);
  });

  it("navigates back to the dossier", async () => {
    vi.mocked(searchTags).mockResolvedValue({ total: 0, tags: [] });
    render(<AutoDocView />);
    await waitFor(() => expect(searchTags).toHaveBeenCalled());
    fireEvent.click(screen.getByText(/Back to Dossier/));
    expect(openDossier).toHaveBeenCalled();
  });
});
