/**
 * A QR code drawn from the modules the engine computed.
 *
 * Black on white regardless of theme. That is not a styling choice: a phone
 * camera expects dark modules on a light ground, and an inverted code is one
 * that many scanners refuse. The four-module quiet zone is part of the
 * standard for the same reason — without it the code has no edge to find.
 */

export default function QrCode({ matrix, size = 196, label }: {
  matrix: number[][];
  size?: number;
  label: string;
}) {
  const quiet = 4;
  const total = matrix.length + quiet * 2;
  let d = '';
  matrix.forEach((row, y) => row.forEach((dark, x) => {
    if (dark) d += `M${x + quiet} ${y + quiet}h1v1h-1z`;
  }));
  return (
    <svg viewBox={`0 0 ${total} ${total}`} width={size} height={size}
         role="img" aria-label={label} shapeRendering="crispEdges"
         className="rounded-lg shrink-0">
      <rect width={total} height={total} fill="#fff" />
      <path d={d} fill="#000" />
    </svg>
  );
}
