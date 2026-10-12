import { describe, expect, it, vi } from 'vitest';
import { chatTurnInference, presetValues, resolvedDefaults } from './inference';
import type { InferenceInfo, InferenceValues } from './inference';

const info: InferenceInfo = { saved: { version: 1, presets: {}, defaults: {} },
  active: { model_path: '/model', engine: 'mlx', context_limit: 8192,
    profile: { parameters: { temperature: 0.65 }, sources: { temperature: 'metadata' },
      capabilities: { fields: ['temperature', 'seed'], template: '', backend_version: 'test',
        reasoning: { levels: ['auto'], mechanism: 'native_fixed', explanation: 'Native' } } } } };

describe('native inference controls', () => {
  it('Auto and Balanced presets do not invent native flags or fixed token counts', () => {
    expect(presetValues('Auto', info)).toEqual({});
    expect(presetValues('Balanced', info)).toEqual({});
    expect(presetValues('Deep', info)).toEqual({});
    expect(presetValues('Fast', info)).toEqual({});
  });
  it('supports real native toggles without changing temperature', () => {
    const supported = structuredClone(info);
    supported.active!.profile.capabilities.reasoning.levels = ['auto', 'off', 'high'];
    expect(presetValues('Fast', supported)).toEqual({ reasoning: 'off' });
    expect(presetValues('Deep', supported)).toEqual({ reasoning: 'high' });
  });
  it('uses native non-thinking for Auto greetings without changing saved preferences', () => {
    const saved = { temperature: 0.4, reasoning: 'auto' };
    expect(chatTurnInference('How are we today? Answer in one sentence.', saved,
      ['auto', 'off', 'high'])).toEqual({ temperature: 0.4, reasoning: 'off' });
    expect(saved.reasoning).toBe('auto');
  });
  it('never replaces explicit effort, custom thinking, raw mode or unsupported controls', () => {
    const overrides: InferenceValues[] = [{ reasoning: 'high' },
      { reasoning: 'auto', reasoning_budget: 300 }, { system_prompt: 'Think carefully.' }];
    for (const saved of overrides) {
      expect(chatTurnInference('How are we today?', saved, ['auto', 'off', 'high'])).toBe(saved);
    }
    expect(chatTurnInference('How are we today?', {}, ['auto'])).toEqual({});
    expect(chatTurnInference('How are we today?', {}, ['auto', 'off'], true)).toEqual({});
    expect(chatTurnInference('How are we today? What is the latest iPhone?', {}, ['auto', 'off'])).toEqual({});
    expect(chatTurnInference('Prove this mathematical theorem.', {}, ['auto', 'off'])).toEqual({});
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
