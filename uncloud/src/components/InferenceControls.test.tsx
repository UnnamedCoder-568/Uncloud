import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import InferenceControls from './InferenceControls';
import type { InferenceInfo } from '../lib/inference';

function render(levels: string[], graded = false, compact = false) {
  const info: InferenceInfo = { saved: { version: 1, defaults: {}, presets: {} }, active: {
    model_path: '/model', engine: 'mlx', context_limit: 8192,
    profile: { parameters: {}, sources: {}, capabilities: { fields: [],
      template: '', backend_version: 'test', reasoning: {
        levels, mechanism: graded ? 'template_effort' : 'template_toggle', explanation: 'Verified native controls',
      } } },
  } };
  return renderToStaticMarkup(<InferenceControls info={info} values={{ reasoning: 'high' }}
    onChange={() => {}} onRefresh={async () => {}} compact={compact} />);
}

describe('thinking effort presentation', () => {
  it('renders only model-declared graded levels as an accessible slider in both consumers', () => {
    for (const compact of [false, true]) {
      const html = render(['auto', 'low', 'medium', 'high'], true, compact);
      expect(html).toContain('type="range"');
      expect(html).toContain('aria-label="Thinking effort"');
      expect(html).toContain('aria-valuetext="high"');
      expect(html).toContain('max="3"');
      expect(html).toContain('value="3"');
    }
  });
  it('labels a binary model honestly and disables an unsupported control', () => {
    const binary = render(['auto', 'off', 'high']);
    expect(binary).toContain('aria-label="Thinking"');
    expect(binary).toContain('aria-valuetext="On"');
    expect(binary).not.toContain('>Medium<');
    expect(render(['auto'])).toContain('disabled=""');
  });
  it('does not offer application-defined creativity or speed presets', () => {
    const html = render(['auto', 'off', 'high']);
    expect(html).toContain('Model defaults');
    expect(html).not.toContain('value="Creative"');
    expect(html).not.toContain('value="Fast"');
  });
});
