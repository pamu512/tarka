import type { CSSProperties } from "react";

type SparklineProps = {
  values: number[];
  /** SVG viewBox height; width scales with container. */
  height?: number;
  className?: string;
  strokeClassName?: string;
  fillClassName?: string;
  /** When true, draws baseline at zero even when flat */
  showBaseline?: boolean;
  /** Accessible label for the polyline */
  "aria-label"?: string;
};

/**
 * Minimal SVG sparkline (single-series line + optional soft fill). Values assumed non-negative.
 */
export function Sparkline({
  values,
  height = 36,
  className = "",
  strokeClassName = "stroke-brand-400",
  fillClassName = "fill-brand-500/25",
  showBaseline = true,
  "aria-label": ariaLabel = "Trend sparkline",
}: SparklineProps) {
  const w = 240;
  const padX = 2;
  const padY = 3;
  const innerW = w - padX * 2;
  const innerH = height - padY * 2;

  const maxVal = values.length === 0 ? 0 : Math.max(...values, 0);
  const minVal = 0;
  const span = Math.max(maxVal - minVal, 1e-9);
  const n = values.length;
  const step = n <= 1 ? 0 : innerW / (n - 1);

  const pts = values.map((v, i) => {
    const x = padX + i * step;
    const y = padY + innerH - ((v - minVal) / span) * innerH;
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  });

  const linePts = pts.join(" ");
  const lastX = padX + (n <= 1 ? 0 : (n - 1) * step);
  const areaD =
    n === 0 || linePts.length === 0
      ? ""
      : `M ${padX},${padY + innerH} L ${linePts.replace(/ /g, " L ")} L ${lastX.toFixed(2)},${padY + innerH} Z`;

  const baselineY = padY + innerH;

  return (
    <svg
      viewBox={`0 0 ${w} ${height}`}
      className={`w-full max-w-full ${className}`}
      preserveAspectRatio="none"
      role="img"
      aria-label={ariaLabel}
    >
      {showBaseline ? (
        <line
          x1={padX}
          y1={baselineY}
          x2={w - padX}
          y2={baselineY}
          className="stroke-surface-600"
          strokeWidth={1}
          vectorEffect="non-scaling-stroke"
        />
      ) : null}
      {areaD ? <path d={areaD} className={fillClassName} /> : null}
      <polyline
        points={linePts}
        fill="none"
        className={strokeClassName}
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
        style={{ vectorEffect: "non-scaling-stroke" } as CSSProperties}
      />
    </svg>
  );
}
