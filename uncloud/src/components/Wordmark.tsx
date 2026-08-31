/**
 * The Uncloud wordmark: heavy rounded lettering with the second "O" replaced by a
 * cog. When `spinning` is true the cog rotates in place — that's the app's loading
 * state, so the brand mark and the spinner are the same object.
 */
export default function Wordmark({
  size = 28,
  spinning = false,
  className = '',
}: {
  size?: number;
  spinning?: boolean;
  className?: string;
}) {
  // Twelve teeth, drawn as trapezoids around the rim.
  const teeth = Array.from({ length: 12 }, (_, i) => {
    const a = (i * 360) / 12;
    return (
      <rect
        key={i}
        x={-4.6}
        y={-46}
        width={9.2}
        height={13}
        rx={2.4}
        transform={`rotate(${a})`}
      />
    );
  });

  return (
    <span
      className={`inline-flex items-baseline select-none ${className}`}
      style={{ fontSize: size, lineHeight: 1 }}
      role="img"
      aria-label="Uncloud"
    >
      <span style={letter}>UNCL</span>

      {/* The cog sits on the text baseline in place of the O */}
      <svg
        viewBox="-52 -52 104 104"
        width={size * 0.92}
        height={size * 0.92}
        style={{ display: 'block', alignSelf: 'center', margin: `0 ${size * 0.03}px` }}
        aria-hidden="true"
      >
        <g
          fill="currentColor"
          style={
            spinning
              ? { animation: 'uncloud-cog 2.4s linear infinite', transformOrigin: '0 0' }
              : undefined
          }
        >
          {teeth}
          <circle r={38} />
          {/* Punched-out centre, so it still reads as the letter O */}
          <circle r={15} fill="var(--bg, #0a0a0c)" />
        </g>
      </svg>

      <span style={letter}>UD</span>
    </span>
  );
}

const letter: React.CSSProperties = {
  fontWeight: 800,
  letterSpacing: '-0.02em',
  fontFamily: 'Inter, system-ui, sans-serif',
};
