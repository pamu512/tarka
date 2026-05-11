import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { FileUpload } from "./FileUpload";

const getDocumentMock = vi.hoisted(() =>
  vi.fn().mockReturnValue({
    promise: Promise.resolve({
      numPages: 1,
      getPage: vi.fn().mockResolvedValue({
        getTextContent: vi.fn().mockResolvedValue({
          items: [{ str: "Extracted " }, { str: "from PDF" }],
        }),
      }),
    }),
  }),
);

vi.mock("pdfjs-dist/build/pdf.worker.min.mjs?url", () => ({ default: "/pdf.worker.stub.mjs" }));

vi.mock("pdfjs-dist", () => ({
  GlobalWorkerOptions: { workerSrc: "" },
  getDocument: (...args: unknown[]) => getDocumentMock(...args),
}));

/** jsdom has no ``DataTransfer``; the component only reads ``files?.[0]``. */
function dropFile(dropzone: HTMLElement, file: File) {
  fireEvent.drop(dropzone, {
    dataTransfer: { files: [file] },
  });
}

describe("FileUpload", () => {
  beforeEach(() => {
    getDocumentMock.mockClear();
  });

  it("keeps Submit disabled until preview text is available", () => {
    render(<FileUpload />);
    expect(screen.getByTestId("file-upload-submit")).toBeDisabled();
  });

  it("gate: after dropping a TXT, preview shows text then Submit enables", async () => {
    render(<FileUpload />);
    const zone = screen.getByTestId("file-upload-dropzone");
    dropFile(zone, new File(["hello drop"], "notes.txt", { type: "text/plain" }));

    await waitFor(() => {
      expect(screen.getByTestId("file-upload-preview")).toHaveTextContent("hello drop");
    });
    expect(screen.getByTestId("file-upload-submit")).not.toBeDisabled();
  });

  it("gate: after dropping a PDF, pdf.js path fills preview then Submit enables", async () => {
    render(<FileUpload />);
    const zone = screen.getByTestId("file-upload-dropzone");
    const pdfBytes = new Uint8Array([0x25, 0x50, 0x44, 0x46]); // %PDF
    dropFile(zone, new File([pdfBytes], "report.pdf", { type: "application/pdf" }));

    await waitFor(() => {
      expect(screen.getByTestId("file-upload-preview")).toHaveTextContent("Extracted from PDF");
    });
    expect(getDocumentMock).toHaveBeenCalled();
    expect(screen.getByTestId("file-upload-submit")).not.toBeDisabled();
  });

  it("calls onSubmit with file and text when Submit is pressed", async () => {
    const onSubmit = vi.fn();
    render(<FileUpload onSubmit={onSubmit} />);
    const zone = screen.getByTestId("file-upload-dropzone");
    dropFile(zone, new File(["body"], "a.txt", { type: "text/plain" }));

    await waitFor(() => expect(screen.getByTestId("file-upload-submit")).not.toBeDisabled());
    fireEvent.click(screen.getByTestId("file-upload-submit"));

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledWith(
        expect.objectContaining({
          text: "body",
          file: expect.objectContaining({ name: "a.txt" }) as File,
        }),
      );
    });
  });

  it("rejects unsupported file types", async () => {
    render(<FileUpload />);
    dropFile(screen.getByTestId("file-upload-dropzone"), new File(["x"], "x.bin", { type: "application/octet-stream" }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/Only .pdf and .txt/);
    });
    expect(screen.getByTestId("file-upload-submit")).toBeDisabled();
  });
});
