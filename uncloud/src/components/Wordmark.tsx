/**
 * The Uncloud wordmark: Montserrat Black with the O replaced by a green cog.
 *
 * The cog is the app icon too, so the two marks are literally the same drawing.
 * Its circuit traces are dropped below `TRACE_MIN` — at wordmark sizes they
 * collapse into noise and muddy the green rather than reading as detail.
 */

const GREEN = '#22c55e';

/** Twelve trapezoidal teeth: wider at the root (r=32) than the tip (r=46).
 *  The taper is what makes it read as a gear instead of a flower. */
const TEETH =
  'M-32.00,5.60 -46.00,3.90 -46.00,-3.90 -32.00,-5.60ZM-30.51,-11.15 -41.79,-19.62 -37.89,-26.38 -24.91,-20.85Z' +
  'M-20.85,-24.91 -26.38,-37.89 -19.62,-41.79 -11.15,-30.51ZM-5.60,-32.00 -3.90,-46.00 3.90,-46.00 5.60,-32.00Z' +
  'M11.15,-30.51 19.62,-41.79 26.38,-37.89 20.85,-24.91ZM24.91,-20.85 37.89,-26.38 41.79,-19.62 30.51,-11.15Z' +
  'M32.00,-5.60 46.00,-3.90 46.00,3.90 32.00,5.60ZM30.51,11.15 41.79,19.62 37.89,26.38 24.91,20.85Z' +
  'M20.85,24.91 26.38,37.89 19.62,41.79 11.15,30.51ZM5.60,32.00 3.90,46.00 -3.90,46.00 -5.60,32.00Z' +
  'M-11.15,30.51 -19.62,41.79 -26.38,37.89 -20.85,24.91ZM-24.91,20.85 -37.89,26.38 -41.79,19.62 -30.51,11.15Z';

/** Six traces, each with a dog-leg bend, running hub -> via pad. */
const TRACES =
  'M12.22,3.27L20.02,5.36L24.69,14.83M3.27,12.22L5.36,20.02L-0.50,28.80' +
  'M-8.94,8.94L-14.65,14.65L-25.19,13.96M-12.22,-3.27L-20.02,-5.36L-24.69,-14.83' +
  'M-3.27,-12.22L-5.36,-20.02L0.50,-28.80M8.94,-8.94L14.65,-14.65L25.19,-13.96';

const VIAS: [number, number][] = [
  [24.69, 14.83], [-0.5, 28.8], [-25.19, 13.96],
  [-24.69, -14.83], [0.5, -28.8], [25.19, -13.96],
];

const TRACE_MIN = 40;

export function Cog({ px, spinning = false, traces }: {
  px: number; spinning?: boolean; traces?: boolean;
}) {
  const detail = traces ?? px >= TRACE_MIN;
  return (
    <svg viewBox="-52 -52 104 104" width={px} height={px} aria-hidden="true"
         style={{ display: 'block', flex: 'none' }}>
      <g style={spinning
        ? { animation: 'uncloud-cog 2.4s linear infinite', transformOrigin: '0 0' }
        : undefined}>
        <g fill={GREEN}>
          <path d={TEETH} />
          <circle r={36} />
        </g>
        {detail && (
          <>
            <path d={TRACES} fill="none" stroke="var(--bg, #0a0a0c)"
                  strokeWidth={3.45} strokeLinecap="round" strokeLinejoin="round" />
            {VIAS.map(([x, y]) => (
              <circle key={`${x},${y}`} cx={x} cy={y} r={4.83} fill="var(--bg, #0a0a0c)" />
            ))}
          </>
        )}
        <circle r={12.4} fill="var(--bg, #0a0a0c)" />
      </g>
    </svg>
  );
}

export default function Wordmark({
  size = 28,
  spinning = false,
  className = '',
}: {
  size?: number;
  spinning?: boolean;
  className?: string;
}) {
  const cog = size * 1.16;   // the cog carries a little past cap height, as an O would
  return (
    <span
      className={`inline-flex items-center select-none ${className}`}
      style={{ fontSize: size, lineHeight: 1 }}
      role="img"
      aria-label="Uncloud"
    >
      <span style={letter}>UNCL</span>
      <span style={{ display: 'inline-flex', margin: `0 ${size * 0.004}px` }}>
        <Cog px={cog} spinning={spinning} />
      </span>
      <span style={letter}>UD</span>
    </span>
  );
}

const letter: React.CSSProperties = {
  fontFamily: "var(--display, 'Montserrat', system-ui, sans-serif)",
  fontWeight: 900,
  letterSpacing: '-0.05em',
};
