/** Only the web leaves the application.
 *
 *  A model's reply is untrusted text. Whatever links it writes, the one the
 *  browser is asked to open must be a web page — not a local file, a script,
 *  or a scheme some other application has registered.
 */

import { describe, expect, it } from 'vitest';
import { isWebLink } from './links';

describe('outbound links', () => {
  it('lets web pages through', () => {
    expect(isWebLink('https://huggingface.co/Qwen/Qwen3.5-4B')).toBe(true);
    expect(isWebLink('http://example.com')).toBe(true);
  });

  it('refuses everything else a reply could contain', () => {
    for (const url of [
      'file:///etc/passwd',
      'javascript:alert(1)',
      'vscode://file/Users/me/.ssh/id_rsa',
      'data:text/html,<script>alert(1)</script>',
      'not a url',
      '',
    ]) expect(isWebLink(url)).toBe(false);
  });
});
