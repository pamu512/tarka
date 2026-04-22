import { useState } from "react";
import { extractSupportIdFromMessage } from "../utils/userFacingErrors";

type SupportIdHintProps = {
  message?: string | null;
  supportId?: string | null;
  className?: string;
  buttonClassName?: string;
  codeClassName?: string;
};

async function copyToClipboard(value: string) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value);
    return;
  }
  const ta = document.createElement("textarea");
  ta.value = value;
  ta.style.position = "fixed";
  ta.style.opacity = "0";
  document.body.appendChild(ta);
  ta.select();
  document.execCommand("copy");
  ta.remove();
}

export function SupportIdHint({
  message,
  supportId,
  className,
  buttonClassName,
  codeClassName,
}: SupportIdHintProps) {
  const resolvedSupportId = supportId ?? (message ? extractSupportIdFromMessage(message) : null);
  const [copied, setCopied] = useState(false);

  if (!resolvedSupportId) return null;

  const onCopy = async () => {
    try {
      await copyToClipboard(resolvedSupportId);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      /* ignore clipboard failures */
    }
  };

  return (
    <div className={className ?? "flex flex-wrap items-center gap-2 text-[11px]"}>
      <span>
        Support ID <code className={codeClassName ?? "font-mono"}>{resolvedSupportId}</code>
      </span>
      <button
        type="button"
        onClick={() => void onCopy()}
        className={
          buttonClassName ??
          "px-1.5 py-0.5 rounded border border-current/35 hover:border-current/60 transition-colors"
        }
      >
        {copied ? "Copied" : "Copy"}
      </button>
    </div>
  );
}
