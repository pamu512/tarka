import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { useEffect } from "react";

type Props = {
  /** Server-sanitized HTML; updates when parent remounts via `key` after load/save. */
  initialHtml: string;
  locked: boolean;
  /** Called when the analyst edits (not fired when `locked`). */
  onHtmlChange?: (html: string) => void;
};

/**
 * Rich-text (TipTap) for SAR investigative notes.
 * When `locked` is true, the ProseMirror editor is non-editable and must not be used to bypass server rules.
 */
export function SarInvestigativeNotesEditor({ initialHtml, locked, onHtmlChange }: Props) {
  const editor = useEditor({
    extensions: [StarterKit],
    content: initialHtml?.trim() ? initialHtml : "<p></p>",
    editable: !locked,
    editorProps: {
      attributes: {
        class: "sar-notes-prose min-h-[220px] px-3 py-2 outline-none text-sm text-gray-200",
        spellcheck: "true",
      },
    },
    onUpdate: ({ editor }) => {
      if (!locked && onHtmlChange) {
        onHtmlChange(editor.getHTML());
      }
    },
  });

  useEffect(() => {
    if (!editor) return;
    editor.setEditable(!locked);
  }, [editor, locked]);

  if (!editor) {
    return <div className="min-h-[220px] rounded-lg border border-surface-600 bg-surface-950/80 animate-pulse" />;
  }

  return (
    <div
      className={`rounded-lg border border-surface-600 bg-surface-950/80 overflow-hidden ${locked ? "opacity-95 select-text" : ""}`}
      data-sar-notes-locked={locked ? "1" : "0"}
    >
      {!locked ? (
        <div className="flex flex-wrap gap-1 border-b border-surface-700 bg-surface-900/90 px-2 py-1.5">
          <ToolbarBtn label="Bold" onClick={() => editor.chain().focus().toggleBold().run()} active={editor.isActive("bold")} />
          <ToolbarBtn label="Italic" onClick={() => editor.chain().focus().toggleItalic().run()} active={editor.isActive("italic")} />
          <ToolbarBtn label="Bullet list" onClick={() => editor.chain().focus().toggleBulletList().run()} active={editor.isActive("bulletList")} />
          <ToolbarBtn label="Ordered list" onClick={() => editor.chain().focus().toggleOrderedList().run()} active={editor.isActive("orderedList")} />
        </div>
      ) : (
        <div className="border-b border-surface-700 bg-amber-500/10 px-3 py-1.5 text-xs text-amber-200/95">
          Read-only: FinCEN payload is in <strong>Uploaded</strong> state (TRANSMITTED or ACKNOWLEDGED). Notes cannot be changed.
        </div>
      )}
      <EditorContent editor={editor} />
    </div>
  );
}

function ToolbarBtn({ label, onClick, active }: { label: string; onClick: () => void; active: boolean }) {
  return (
    <button
      type="button"
      className={`rounded px-2 py-0.5 text-[11px] font-medium border transition-colors ${
        active ? "bg-brand-600/30 border-brand-500/50 text-brand-100" : "border-transparent text-gray-400 hover:text-gray-200 hover:bg-surface-800"
      }`}
      onClick={onClick}
    >
      {label}
    </button>
  );
}
