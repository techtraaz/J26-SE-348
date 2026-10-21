import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { LibraryLayout } from "./LibraryLayout";

// Only the panel's visibility is under test here.
vi.mock("@/features/extraction/ExtractionLayout", () => ({ ExtractionLayout: () => <p>library</p> }));
vi.mock("./CasePanel", () => ({ CasePanel: () => <p>case panel</p> }));

function renderAt(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/documents/*" element={<LibraryLayout />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("LibraryLayout", () => {
  it.each(["/documents", "/documents/folders", "/documents/folders/unfiled", "/documents/folders/f1"])(
    "shows the case panel on %s",
    (path) => {
      renderAt(path);
      expect(screen.getByText("case panel")).toBeInTheDocument();
    },
  );

  it("hides it on a document's review page, which needs the width", () => {
    renderAt("/documents/6f1c2b9e-0000-4000-8000-000000000001");
    expect(screen.queryByText("case panel")).not.toBeInTheDocument();
  });
});
