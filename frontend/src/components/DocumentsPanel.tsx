import { useCallback, useEffect, useRef, useState } from "react";
import { Upload, FileText, Trash2, Search, AlertCircle } from "lucide-react";
import { api } from "../api/client";
import type { DocumentItem, DocumentPassage, DocumentStatus } from "../api/types";
import { Card } from "./ui";

const PROCESSING: DocumentStatus[] = [
  "uploaded",
  "parsing",
  "chunking",
  "embedding",
  "indexing",
];

const STATUS_STYLE: Record<DocumentStatus, string> = {
  uploaded: "bg-slate-100 text-slate-600",
  parsing: "bg-blue-100 text-blue-700",
  chunking: "bg-blue-100 text-blue-700",
  embedding: "bg-amber-100 text-amber-700",
  indexing: "bg-amber-100 text-amber-700",
  ready: "bg-emerald-100 text-emerald-700",
  failed: "bg-red-100 text-red-700",
};

function DocStatus({ status }: { status: DocumentStatus }) {
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STATUS_STYLE[status]}`}>
      {status}
    </span>
  );
}

function humanSize(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

export default function DocumentsPanel({ projectId }: { projectId: string }) {
  const [docs, setDocs] = useState<DocumentItem[]>([]);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [passages, setPassages] = useState<DocumentPassage[] | null>(null);
  const [searching, setSearching] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try {
      setDocs(await api.listDocuments(projectId));
    } catch {
      /* keep prior list on transient errors */
    }
  }, [projectId]);

  useEffect(() => {
    load();
  }, [load]);

  // Poll while any document is still being processed.
  const anyProcessing = docs.some((d) => PROCESSING.includes(d.status));
  useEffect(() => {
    if (!anyProcessing) return;
    const t = setInterval(load, 2500);
    return () => clearInterval(t);
  }, [anyProcessing, load]);

  const onUpload = async (file: File) => {
    setUploading(true);
    setError(null);
    try {
      await api.uploadDocument(projectId, file);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const onDelete = async (id: string) => {
    await api.deleteDocument(id);
    await load();
  };

  const onSearch = async () => {
    if (query.trim().length < 2) return;
    setSearching(true);
    try {
      setPassages(await api.searchDocuments(projectId, query.trim()));
    } catch {
      setPassages([]);
    } finally {
      setSearching(false);
    }
  };

  return (
    <div className="space-y-4">
      <Card>
        <div className="flex items-center justify-between gap-3">
          <div>
            <h3 className="font-semibold text-slate-900">Documents</h3>
            <p className="text-sm text-slate-500">
              Upload PDF or DOCX files to research offline against your own documents.
              Enable the <span className="font-medium">Documents</span> source on a run to
              use them as evidence.
            </p>
          </div>
          <label className="inline-flex shrink-0 cursor-pointer items-center gap-2 rounded-lg bg-brand-600 px-3 py-2 text-sm font-medium text-white hover:bg-brand-700">
            <Upload className="h-4 w-4" />
            {uploading ? "Uploading…" : "Upload"}
            <input
              ref={fileRef}
              type="file"
              accept=".pdf,.docx"
              className="hidden"
              disabled={uploading}
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) onUpload(f);
              }}
            />
          </label>
        </div>
        {error && (
          <p className="mt-2 flex items-center gap-1.5 text-sm text-red-600">
            <AlertCircle className="h-4 w-4" /> {error}
          </p>
        )}
      </Card>

      {docs.length === 0 ? (
        <Card>
          <p className="text-sm text-slate-500">
            No documents yet. Upload a PDF or DOCX to get started.
          </p>
        </Card>
      ) : (
        <div className="space-y-2">
          {docs.map((d) => (
            <Card key={d.id} className="py-3">
              <div className="flex items-start justify-between gap-3">
                <div className="flex min-w-0 items-start gap-2">
                  <FileText className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" />
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium text-slate-800">
                      {d.original_filename}
                    </div>
                    <div className="mt-0.5 flex flex-wrap gap-x-3 text-xs text-slate-500">
                      <span>{humanSize(d.size_bytes)}</span>
                      {d.page_count > 0 && <span>{d.page_count} pages</span>}
                      {d.status === "ready" && <span>{d.chunk_count} chunks</span>}
                      <span>{new Date(d.created_at).toLocaleDateString()}</span>
                    </div>
                    {d.status === "failed" && d.error_message && (
                      <div className="mt-1 text-xs text-red-600">{d.error_message}</div>
                    )}
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <DocStatus status={d.status} />
                  <button
                    onClick={() => onDelete(d.id)}
                    title="Delete document"
                    className="rounded-md p-1.5 text-slate-400 hover:bg-slate-100 hover:text-red-600"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}

      <Card>
        <div className="flex items-center gap-2">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && onSearch()}
            placeholder="Search within your documents…"
            className="flex-1 rounded-lg border border-slate-300 p-2 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500"
          />
          <button
            onClick={onSearch}
            disabled={searching}
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-700 hover:bg-slate-100"
          >
            <Search className="h-4 w-4" /> Search
          </button>
        </div>
        {passages !== null && (
          <div className="mt-3 space-y-2">
            {passages.length === 0 ? (
              <p className="text-sm text-slate-500">No matching passages.</p>
            ) : (
              passages.map((p) => (
                <div key={p.chunk_id} className="rounded-lg border border-slate-200 p-3">
                  <div className="mb-1 flex items-center gap-2 text-xs text-slate-500">
                    <FileText className="h-3.5 w-3.5" />
                    <span className="font-medium text-slate-700">{p.filename}</span>
                    {p.page_number != null && <span>· p.{p.page_number}</span>}
                    <span className="ml-auto">{Math.round(p.score * 100)}% match</span>
                  </div>
                  <p className="text-sm text-slate-600">{p.text}</p>
                </div>
              ))
            )}
          </div>
        )}
      </Card>
    </div>
  );
}
