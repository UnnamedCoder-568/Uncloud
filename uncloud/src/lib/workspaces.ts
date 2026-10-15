export type View =
  | 'chat' | 'models' | 'chisel' | 'automations' | 'image' | 'video' | 'music'
  | 'jarviz' | 'personas' | 'outputs' | 'guide' | 'settings';

/** Keep saved notification destinations working after workspace consolidation. */
export function resolveView(value: string): View | null {
  if (value === 'voice' || value === 'friday') return 'jarviz';
  if (value === 'recipes') return 'automations';
  return ['chat', 'models', 'chisel', 'automations', 'image', 'video', 'music',
    'jarviz', 'personas', 'outputs', 'guide', 'settings'].includes(value) ? value as View : null;
}
