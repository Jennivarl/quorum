import type { Standing } from "../lib/types";

/**
 * The whole iconography of this site.
 *
 * There is no icon library here, and these are not icons. A row of these
 * always draws the real counts from a check, so it is a chart: filled units
 * agreed, outlined units dissented, dotted units stayed silent. Read the row
 * and you have read the verdict without reading a word.
 */

const R = 5;
const GAP = 6;

function unit(kind: Standing, cx: number, key: number) {
  if (kind === "agreed") {
    return <circle key={key} cx={cx} cy={R} r={R} fill="var(--ink)" />;
  }
  if (kind === "dissented") {
    return (
      <circle
        key={key}
        cx={cx}
        cy={R}
        r={R - 0.8}
        fill="none"
        stroke="var(--dissent)"
        strokeWidth="1.6"
      />
    );
  }
  // Silence is drawn as absence. It is never counted as agreement, so it must
  // never look like a filled unit at a glance.
  return (
    <circle
      key={key}
      cx={cx}
      cy={R}
      r={R - 0.8}
      fill="none"
      stroke="var(--rule)"
      strokeWidth="1.4"
      strokeDasharray="2 2.2"
    />
  );
}

export function GlyphRow({
  agreed = 0,
  dissented = 0,
  silent = 0,
  label,
}: {
  agreed?: number;
  dissented?: number;
  silent?: number;
  label?: string;
}) {
  const kinds: Standing[] = [
    ...Array<Standing>(agreed).fill("agreed"),
    ...Array<Standing>(dissented).fill("dissented"),
    ...Array<Standing>(silent).fill("silent"),
  ];
  if (!kinds.length) return null;

  const width = kinds.length * R * 2 + (kinds.length - 1) * GAP;
  const described =
    label ??
    `${agreed} agreed, ${dissented} dissented` +
      (silent ? `, ${silent} silent` : "");

  return (
    <svg
      width={width}
      height={R * 2}
      viewBox={`0 0 ${width} ${R * 2}`}
      role="img"
      aria-label={described}
      style={{ flexShrink: 0 }}
    >
      {kinds.map((k, i) => unit(k, i * (R * 2 + GAP) + R, i))}
    </svg>
  );
}

export function Glyph({ kind }: { kind: Standing }) {
  const words = {
    agreed: "agreed",
    dissented: "dissented",
    silent: "did not answer",
  } as const;
  return (
    <svg
      width={R * 2}
      height={R * 2}
      viewBox={`0 0 ${R * 2} ${R * 2}`}
      role="img"
      aria-label={words[kind]}
      style={{ flexShrink: 0 }}
    >
      {unit(kind, R, 0)}
    </svg>
  );
}

/**
 * The same glyph bent into a ring: eight units, five filled. A quorum, just
 * barely. Positions are the eight 45 degree points on a circle of radius 13,
 * written out rather than computed so the shape cannot drift.
 */
export function Logo({ size = 28 }: { size?: number }) {
  const filled: [number, number][] = [
    [16, 3],
    [25.19, 6.81],
    [29, 16],
    [25.19, 25.19],
    [16, 29],
  ];
  const hollow: [number, number][] = [
    [6.81, 25.19],
    [3, 16],
    [6.81, 6.81],
  ];
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      role="img"
      aria-label="Quorum"
      style={{ flexShrink: 0 }}
    >
      {filled.map(([cx, cy], i) => (
        <circle key={`f${i}`} cx={cx} cy={cy} r={2.6} fill="var(--ink)" />
      ))}
      {hollow.map(([cx, cy], i) => (
        <circle
          key={`h${i}`}
          cx={cx}
          cy={cy}
          r={2.1}
          fill="none"
          stroke="var(--dissent)"
          strokeWidth={1.4}
        />
      ))}
    </svg>
  );
}
