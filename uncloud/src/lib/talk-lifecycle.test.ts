import { beforeEach, describe, expect, it, vi } from 'vitest';
const h = vi.hoisted(() => ({ states: [] as unknown[], native: true,
  event: null as null | ((event: {event: string; text?: string}) => void),
  synth: vi.fn(), play: vi.fn(), nativeStart: vi.fn(), nativeReady: null as null | Promise<void>, released: vi.fn() }));
vi.mock('../components/Panes', () => ({usePaneVisible: () => true}));
vi.mock('react', () => ({useRef: (value: unknown) => ({current: value}),
  useState: (value: unknown) => [value, (next: unknown) => h.states.push(next)],
  useCallback: (fn: unknown) => fn, useEffect: (fn: () => unknown) => {fn();}}));
vi.mock('./nativeListen', () => ({nativeListening: async () => h.native,
  startNativeListener: async (fn: typeof h.event) => { h.event = fn; h.nativeStart(); if (h.nativeReady) await h.nativeReady; return () => h.released(); }, endNativeTurn: async () => {}}));
vi.mock('./sidecar', () => ({getLibrary: async () => [], speakReply: (...args: unknown[]) => h.synth(...args), transcribeAudio: async () => 'hello'}));
vi.mock('./converse', () => ({Conversation: class { start() { return Promise.reject(new Error('Microphone denied')); } stop() {} setSpeaking() {} }}));
import { useTalk } from './useTalk';
const flush = async () => { for (let i=0;i<12;i++) await Promise.resolve(); };
function deferred<T>() { let resolve!: (v:T) => void; const promise = new Promise<T>(r => {resolve=r;}); return {promise,resolve}; }
beforeEach(() => { h.states=[]; h.native=true; h.event=null; h.synth.mockReset(); h.play.mockReset(); h.nativeStart.mockReset(); h.nativeReady=null; h.released.mockReset();
  vi.stubGlobal('Audio', class {src=''; onended: null|(()=>void)=null; onerror=null; onpause: null|(()=>void)=null; play() {h.play(); return Promise.resolve();} pause() {this.onpause?.();} });
});
describe('voice lifecycle stress cases', () => {
  it('rejects duplicate utterances while answering and aborts on Stop', async () => {
    const pending=deferred<string>(); let signal: AbortSignal | undefined;
    const handler=vi.fn((_text, _say, s) => {signal=s; return pending.promise;});
    const talk=useTalk('bf_emma',handler); await talk.start();
    h.event?.({event:'endOfTurn',text:'hello'}); h.event?.({event:'endOfTurn',text:'hello again'});
    expect(handler).toHaveBeenCalledTimes(1); talk.stop(); expect(signal?.aborted).toBe(true);
    pending.resolve('late response'); await flush(); expect(h.synth).not.toHaveBeenCalled();
  });
  it('does not play speech whose synthesis completes after Stop', async () => {
    const synth=deferred<string>(); h.synth.mockReturnValue(synth.promise);
    const talk=useTalk('bf_emma',async (_text,say) => {say('A complete sentence.');}); await talk.start();
    h.event?.({event:'endOfTurn',text:'hello'}); await flush(); talk.stop();
    synth.resolve('blob:late'); await flush(); expect(h.play).not.toHaveBeenCalled();
  });
  it('can retry starting after microphone permission fails', async () => {
    h.native=false; const talk=useTalk('bf_emma',async () => 'hi');
    await expect(talk.start()).rejects.toThrow('Microphone denied');
    h.native=true; await talk.start(); expect(h.nativeStart).toHaveBeenCalledTimes(1);
  });
  it('releases a native listener if Stop occurs during startup', async () => {
    const ready=deferred<void>(); h.nativeReady=ready.promise;
    const talk=useTalk('bf_emma',async () => 'hi'); const starting=talk.start(); await flush();
    talk.stop(); ready.resolve(); await starting; expect(h.released).toHaveBeenCalledTimes(1);
    h.event?.({event:'ready'}); expect(h.states.at(-1)).toBe('');
  });
  it('observes even a clip that ends immediately during play', async () => {
    h.synth.mockResolvedValue('blob:short');
    vi.stubGlobal('Audio', class {src=''; onended: null|(()=>void)=null; onerror=null; onpause: null|(()=>void)=null;
      play() {h.play(); this.onended?.(); return Promise.resolve();} pause() {this.onpause?.();} });
    const talk=useTalk('bf_emma',async () => 'A complete sentence.'); await talk.start();
    h.event?.({event:'endOfTurn',text:'hello'}); await flush();
    expect(h.play).toHaveBeenCalledTimes(1); expect(h.states).toContain('listening');
    expect(h.states.at(-1)).toBe('listening');
  });

});
