import { useEffect, useId, useRef, useState } from 'react';

/**
 * The Uncloud wordmark: Montserrat Black with the O replaced by a cog carrying
 * the brand's amber-to-red gradient.
 *
 * The cog is the app icon too, so the two marks are literally the same drawing.
 * Its circuit traces are dropped below `TRACE_MIN` — at wordmark sizes they
 * collapse into noise and muddy the green rather than reading as detail.
 */


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
  // Unique per instance: several cogs can be on screen at once and duplicate
  // gradient ids would make them all resolve to whichever mounted first.
  const gid = useId();
  return (
    <svg viewBox="-52 -52 104 104" width={px} height={px} aria-hidden="true"
         style={{ display: 'block', flex: 'none' }}>
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="var(--accent, #f59e0b)" />
          <stop offset="100%" stopColor="var(--accent-2, #dc2626)" />
        </linearGradient>
      </defs>
      <g style={spinning
        ? { animation: 'uncloud-cog 2.4s linear infinite', transformOrigin: '0 0' }
        : undefined}>
        <g fill={`url(#${gid})`}>
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

/**
 * Loading state: the word assembles itself. Characters land left to right while
 * the whole mark stays centred, so it grows outward from the middle, and the
 * extra tracking on an unsettled glyph collapses to normal as it arrives.
 *
 * Laid out in a frame loop rather than CSS keyframes because the centred growth
 * needs real widths — a glyph that has not landed yet must occupy no space, and
 * CSS cannot interpolate to a text run's intrinsic width.
 */
const GLYPHS = ['U', 'N', 'C', 'L', null, 'U', 'D'] as const;  // null is the cog
const STAGGER = 0.085;
const EXTRA = 0.52;      // additional tracking while a glyph settles, in em
const CYCLE = 2600;      // ms for one full assemble, hold and reset

function smooth(t: number) {
  const x = Math.max(0, Math.min(1, t));
  return x * x * (3 - 2 * x);
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
  const cog = size * 1.16;
  const refs = useRef<(HTMLSpanElement | null)[]>([]);
  const [widths, setWidths] = useState<number[] | null>(null);
  const [p, setP] = useState(1);

  // Measure once at rest; the animation needs each glyph's natural width.
  useEffect(() => {
    const w = refs.current.map((el, i) =>
      i === 4 ? cog : (el?.getBoundingClientRect().width ?? 0),
    );
    if (w.every((n) => n > 0)) setWidths(w);
  }, [size, cog]);

  useEffect(() => {
    if (!spinning || !widths) { setP(1); return; }
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return;
    let raf = 0;
    const t0 = performance.now();
    const tick = (now: number) => {
      const phase = ((now - t0) % CYCLE) / CYCLE;
      // Assemble over the first 70%, hold, then reset for the next pass.
      setP(phase < 0.7 ? phase / 0.7 : 1);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [spinning, widths]);

  const n = GLYPHS.length;
  const win = 1 - STAGGER * (n - 1);
  const gp = GLYPHS.map((_, i) =>
    widths && spinning ? smooth((p - STAGGER * i) / win) : 1,
  );

  return (
    <span
      //: The gradient is clipped to the text of the WORD, not of each letter.
      //  Per-glyph it would repeat the whole amber-to-rose sweep six times over
      //  and read as noise; across the word it reads as one mark, and matches
      //  the cog sitting in the middle of it. The cog is an SVG with its own
      //  fill, so text-fill-color leaves it alone.
      className={`inline-flex items-center select-none grad-text ${className}`}
      style={{ fontSize: size, lineHeight: 1 }}
      role="img"
      aria-label="Uncloud"
    >
      {GLYPHS.map((ch, i) => {
        const natural = widths ? widths[i] : undefined;
        const advance =
          natural === undefined
            ? undefined
            : (natural + EXTRA * size * (1 - gp[i])) * gp[i];
        return (
          <span
            key={i}
            ref={(el) => { refs.current[i] = el; }}
            style={{
              display: 'inline-flex',
              justifyContent: 'center',
              overflow: 'visible',
              opacity: gp[i],
              width: advance,
              ...(ch === null ? {} : letter),
            }}
          >
            {ch === null ? <Cog px={cog} /> : ch}
          </span>
        );
      })}
    </span>
  );
}

const letter: React.CSSProperties = {
  fontFamily: "var(--display, 'Montserrat', system-ui, sans-serif)",
  fontWeight: 900,
  letterSpacing: '-0.07em',
};
