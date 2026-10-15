import { describe, expect, it, vi } from 'vitest';
import { resolvedDefaults } from './inference';
import type { InferenceInfo } from './inference';

const info: InferenceInfo = { saved: { version: 1, presets: {}, defaults: {} },
  active: { model_path: '/model', engine: 'mlx', context_limit: 8192,
    profile: { parameters: { temperature: 0.65 }, sources: { temperature: 'metadata' },
      capabilities: { fields: ['temperature', 'seed'], template: '', backend_version: 'test',
        reasoning: { levels: ['auto'], mechanism: 'native_fixed', explanation: 'Native' } } } } };

describe('native inference controls', () => {
  it('Auto leaves the model controls unspecified', () => {
    expect(resolvedDefaults(info, '/model')).toEqual({});
  });
  it('manual controls survive switching models and opening a conversation', () => {
    const configured = structuredClone(info);
    configured.saved.defaults = { 'model:/other': { temperature: 0.9, max_tokens: 64 },
      'conversation:one': { max_tokens: 256 } };
    const manual = { max_tokens: 2048, temperature: 0.3, reasoning: 'auto' };
    expect(resolvedDefaults(configured, '/model', null, manual)).toEqual(manual);
    expect(resolvedDefaults(configured, '/other', 'one', manual)).toEqual(manual);
    expect(manual).toEqual({ max_tokens: 2048, temperature: 0.3, reasoning: 'auto' });
  });
  it('conversation settings win and empty custom system prompts remain explicit', () => {
    const configured = structuredClone(info);
    configured.saved.defaults = { 'model:/model': { temperature: 0.4 },
      'conversation:one': { temperature: 0.2, system_prompt: '' } };
    expect(resolvedDefaults(configured, '/model', 'one')).toEqual({ temperature: 0.2, system_prompt: '' });
  });
  it('migrates visible legacy overrides but respects an explicit native-default reset', () => {
    vi.stubGlobal('localStorage', { getItem: (key: string) => key.endsWith('temperatures') ? '{"/model":"0.3"}' : '{}' });
    expect(resolvedDefaults(info, '/model')).toEqual({ temperature: 0.3 });
    const reset = structuredClone(info); reset.saved.defaults['model:/model'] = {};
    expect(resolvedDefaults(reset, '/model')).toEqual({});
    vi.unstubAllGlobals();
  });
});
