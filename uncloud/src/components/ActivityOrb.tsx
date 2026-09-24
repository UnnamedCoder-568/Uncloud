import { ThinkingOrb } from 'thinking-orbs';
import type { OrbState, OrbSize } from 'thinking-orbs';

export default function ActivityOrb({
  state = 'working',
  size = 20,
  label,
  className,
}: {
  state?: OrbState;
  size?: OrbSize;
  label?: string;
  className?: string;
}) {
  return (
    <ThinkingOrb
      state={state}
      size={size}
      theme="dark"
      aria-label={label ?? `${state[0].toUpperCase()}${state.slice(1)}…`}
      className={className}
      style={{ display: 'inline-block', flex: '0 0 auto', verticalAlign: 'middle' }}
    />
  );
}
