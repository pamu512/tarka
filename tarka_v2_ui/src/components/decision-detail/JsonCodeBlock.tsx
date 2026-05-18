"use client";

import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";

type JsonCodeBlockProps = {
  value: unknown;
  "aria-label"?: string;
};

export function JsonCodeBlock({ value, "aria-label": ariaLabel }: JsonCodeBlockProps) {
  const text = JSON.stringify(value, null, 2);

  return (
    <SyntaxHighlighter
      language="json"
      style={oneDark}
      showLineNumbers
      wrapLongLines
      customStyle={{
        margin: 0,
        borderRadius: 6,
        maxHeight: "min(48vh, 380px)",
        fontSize: 11,
        lineHeight: 1.45,
        background: "rgb(15 23 42)",
      }}
      codeTagProps={{ className: "font-mono" }}
      PreTag="div"
      aria-label={ariaLabel}
    >
      {text}
    </SyntaxHighlighter>
  );
}
