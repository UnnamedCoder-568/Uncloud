/** What a failed update says to the person in front of it.
 *
 *  Updates are signed, and the signing key was rotated after 0.4.1. A copy
 *  installed before that can never verify anything published after it — the
 *  plugin says "the signature was created with a different key than the one
 *  provided", which is accurate and useless: nothing in it tells a tester that
 *  the fix is to download the application once.
 */

import { describe, expect, it } from 'vitest';
import { explain } from './updates';

describe('a failed update', () => {
  it('turns a key mismatch into something a person can act on', () => {
    const said = explain('The update could not be installed: The signature was created '
      + 'with a different key than the one provided');
    expect(said).toMatch(/too old to update itself/);
    expect(said).toMatch(/download/i);
    expect(said).not.toMatch(/signature/i);
  });

  it('passes anything else through, minus the noise', () => {
    expect(explain('Error: network unreachable')).toBe('network unreachable');
  });
});
