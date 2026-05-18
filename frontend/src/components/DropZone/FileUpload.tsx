import { useCallback, useId, useState } from "react";
import { FileText, Upload } from "lucide-react";
import { getDocument, GlobalWorkerOptions } from "pdfjs-dist";
import pdfWorkerSrc from "pdfjs-dist/build/pdf.worker.min.mjs?url";

GlobalWorkerOptions.workerSrc = pdfWorkerSrc;

const ACCEPT = ".pdf,.txt,application/pdf,text/plain";

function isAllowedFile(file: File): boolean {
  const name = file.name.toLowerCase();
  if (name.endsWith(".txt")) return true;
  if (name.endsWith(".pdf")) return true;
  if (file.type === "application/pdf") return true;
  if (file.type === "text/plain") return true;
  return false;
}

function readFileAsText(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(reader.error ?? new Error("Failed to read file"));
    reader.readAsText(file);
  });
}

/** Drag/drop in some test environments yields ``File``-like objects without ``arrayBuffer``. */
function readFileAsArrayBuffer(file: Blob): Promise<ArrayBuffer> {
  if (typeof file.arrayBuffer === "function") {
    return file.arrayBuffer();
  }
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as ArrayBuffer);
    reader.onerror = () => reject(reader.error ?? new Error("Failed to read file"));
    reader.readAsArrayBuffer(file);
  });
}

async function extractTextFromPdf(file: File): Promise<string> {
  const data = new Uint8Array(await readFileAsArrayBuffer(file));
  const pdf = await getDocument({ data }).promise;
  const chunks: string[] = [];
  for (let p = 1; p <= pdf.numPages; p++) {
    const page = await pdf.getPage(p);
    const content = await page.getTextContent();
    const line = content.items
      .map((item) => {
        if (item && typeof item === "object" && "str" in item && typeof (item as { str: unknown }).str === "string") {
          return (item as { str: string }).str;
        }
        return "";
      })
      .join(" ");
    chunks.push(line.trim());
  }
  return chunks.filter(Boolean).join("\n\n");
}

export type FileUploadSubmitPayload = {
  file: File;
  text: string;
};

export type FileUploadProps = {
  className?: string;
  disabled?: boolean;
  onSubmit?: (payload: FileUploadSubmitPayload) => void | Promise<void>;
};

type ReadStatus = "idle" | "reading" | "ready" | "error";

/**
 * Drag-and-drop (or pick) **.pdf** / **.txt** uploads. PDFs are parsed with **pdf.js** for an immediate text preview before Submit.
 */
export function FileUpload({ className, disabled = false, onSubmit }: FileUploadProps) {
  const inputId = useId();
  const [isDragging, setIsDragging] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [previewText, setPreviewText] = useState("");
  const [status, setStatus] = useState<ReadStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const ingestFile = useCallback(async (next: File) => {
    if (!isAllowedFile(next)) {
      setError("Only .pdf and .txt files are supported.");
      setFile(null);
      setPreviewText("");
      setStatus("error");
      return;
    }
    setError(null);
    setFile(next);
    setStatus("reading");
    setPreviewText("");
    try {
      const text = next.name.toLowerCase().endsWith(".pdf") ? await extractTextFromPdf(next) : await readFileAsText(next);
      setPreviewText(text);
      setStatus("ready");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not read file.");
      setPreviewText("");
      setStatus("error");
    }
  }, []);

  const onInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const f = e.target.files?.[0];
      e.target.value = "";
      if (f) void ingestFile(f);
    },
    [ingestFile],
  );

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setIsDragging(false);
      if (disabled) return;
      const f = e.dataTransfer.files?.[0];
      if (f) void ingestFile(f);
    },
    [disabled, ingestFile],
  );

  const canSubmit =
    !disabled && status === "ready" && file != null && previewText.trim().length > 0 && !submitting;

  const handleSubmit = useCallback(async () => {
    if (!canSubmit || !file) return;
    setSubmitting(true);
    try {
      await onSubmit?.({ file, text: previewText });
    } finally {
      setSubmitting(false);
    }
  }, [canSubmit, file, onSubmit, previewText]);

  return (
    <div className={`space-y-4 ${className ?? ""}`}>
      <label
        htmlFor={inputId}
        onDragEnter={(e) => {
          e.preventDefault();
          if (!disabled) setIsDragging(true);
        }}
        onDragOver={(e) => {
          e.preventDefault();
          if (!disabled) setIsDragging(true);
        }}
        onDragLeave={(e) => {
          e.preventDefault();
          if (!e.currentTarget.contains(e.relatedTarget as Node)) setIsDragging(false);
        }}
        onDrop={onDrop}
        className={`flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors ${
          disabled
            ? "cursor-not-allowed border-surface-700 bg-surface-900/40 text-gray-500"
            : isDragging
              ? "border-brand-400 bg-brand-500/10 text-gray-100"
              : "border-surface-600 bg-surface-900/60 text-gray-300 hover:border-surface-500 hover:bg-surface-900"
        }`}
        data-testid="file-upload-dropzone"
      >
        <input
          id={inputId}
          type="file"
          accept={ACCEPT}
          className="sr-only"
          disabled={disabled}
          onChange={onInputChange}
          aria-label="Choose PDF or text file"
        />
        <Upload className="h-10 w-10 opacity-70" aria-hidden />
        <span className="text-sm font-medium">Drop a PDF or TXT file here</span>
        <span className="text-xs text-gray-500">or click to browse — text preview loads before you submit</span>
      </label>

      {error ? (
        <p className="text-sm text-red-400" role="alert">
          {error}
        </p>
      ) : null}

      {status === "reading" ? (
        <p className="text-sm text-gray-400" data-testid="file-upload-reading">
          Extracting text…
        </p>
      ) : null}

      {previewText.trim().length > 0 ? (
        <section className="rounded-xl border border-surface-700 bg-surface-950" aria-label="Extracted text preview">
          <div className="flex items-center gap-2 border-b border-surface-700 px-3 py-2 text-xs text-gray-400">
            <FileText className="h-4 w-4" aria-hidden />
            <span className="truncate font-mono">{file?.name ?? "Preview"}</span>
          </div>
          <pre
            className="max-h-72 overflow-auto whitespace-pre-wrap break-words p-3 text-sm text-gray-200"
            data-testid="file-upload-preview"
          >
            {previewText}
          </pre>
        </section>
      ) : null}

      <div className="flex justify-end">
        <button
          type="button"
          className="rounded-lg bg-brand-500 px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-40"
          disabled={!canSubmit}
          onClick={() => void handleSubmit()}
          data-testid="file-upload-submit"
        >
          {submitting ? "Submitting…" : "Submit"}
        </button>
      </div>
    </div>
  );
}
