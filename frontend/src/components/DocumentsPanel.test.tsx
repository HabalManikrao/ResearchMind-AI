import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const { listDocuments, uploadDocument, deleteDocument, searchDocuments } = vi.hoisted(() => ({
  listDocuments: vi.fn(),
  uploadDocument: vi.fn(),
  deleteDocument: vi.fn(),
  searchDocuments: vi.fn(),
}));
vi.mock("../api/client", () => ({
  api: { listDocuments, uploadDocument, deleteDocument, searchDocuments },
}));

import DocumentsPanel from "./DocumentsPanel";
import type { DocumentItem, DocumentPassage } from "../api/types";

const doc: DocumentItem = {
  id: "d1",
  project_id: "p1",
  original_filename: "arch.pdf",
  mime_type: "application/pdf",
  size_bytes: 2048,
  status: "ready",
  page_count: 3,
  word_count: 100,
  chunk_count: 5,
  error_message: null,
  processed_at: null,
  created_at: "2026-01-01T00:00:00Z",
  meta: {},
};

describe("DocumentsPanel", () => {
  beforeEach(() => {
    listDocuments.mockReset().mockResolvedValue([doc]);
    uploadDocument.mockReset().mockResolvedValue(doc);
    deleteDocument.mockReset().mockResolvedValue({ message: "ok" });
    searchDocuments.mockReset().mockResolvedValue([]);
  });

  it("lists documents with status and metadata", async () => {
    render(<DocumentsPanel projectId="p1" />);
    expect(await screen.findByText("arch.pdf")).toBeInTheDocument();
    expect(screen.getByText("ready")).toBeInTheDocument();
    expect(screen.getByText(/3 pages/)).toBeInTheDocument();
    expect(screen.getByText(/5 chunks/)).toBeInTheDocument();
  });

  it("shows an empty state when there are no documents", async () => {
    listDocuments.mockResolvedValue([]);
    render(<DocumentsPanel projectId="p1" />);
    expect(await screen.findByText(/No documents yet/)).toBeInTheDocument();
  });

  it("uploads a selected file", async () => {
    const { container } = render(<DocumentsPanel projectId="p1" />);
    await screen.findByText("arch.pdf");
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["%PDF-1.4 data"], "new.pdf", { type: "application/pdf" });
    fireEvent.change(input, { target: { files: [file] } });
    await waitFor(() => expect(uploadDocument).toHaveBeenCalledWith("p1", file));
  });

  it("searches within documents and renders passages with page numbers", async () => {
    const passages: DocumentPassage[] = [
      {
        document_id: "d1",
        chunk_id: "c1",
        filename: "arch.pdf",
        text: "the modular offline pipeline supports local documents",
        score: 0.91,
        page_number: 2,
        section: null,
      },
    ];
    searchDocuments.mockResolvedValue(passages);
    const user = userEvent.setup();
    render(<DocumentsPanel projectId="p1" />);
    await screen.findByText("arch.pdf");
    await user.type(
      screen.getByPlaceholderText(/Search within your documents/), "pipeline"
    );
    await user.click(screen.getByRole("button", { name: /Search/ }));
    expect(await screen.findByText(/modular offline pipeline/)).toBeInTheDocument();
    expect(screen.getByText(/p\.2/)).toBeInTheDocument();
    expect(searchDocuments).toHaveBeenCalledWith("p1", "pipeline");
  });
});
