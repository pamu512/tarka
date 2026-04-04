/**
 * Stylized “T” mark — vector paths only, fills with currentColor for light/dark themes.
 */
export function TarkaMark({
  className = "h-9 w-9",
  "aria-hidden": ariaHidden = true,
}: {
  className?: string;
  "aria-hidden"?: boolean;
}) {
  return (
    <svg
      className={className}
      viewBox="0 0 40 52"
      fill="currentColor"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden={ariaHidden}
    >
      {/* Left crossbar — gap before stem reads as diagonal negative space */}
      <path d="M3 10.5h12.75v4.25H3V10.5z" />
      {/* Stem */}
      <path d="M17.75 10.5h8.75v40H17.75v-40z" />
      {/* Right cap — arc out from stem then back */}
      <path d="M26.5 10.5C33 8 39.5 12 39 17.5 38.5 21.5 33 23 26.5 21V10.5z" />
    </svg>
  );
}
