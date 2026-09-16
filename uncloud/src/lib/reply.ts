/** Remove application/model protocol from what a person reads.
 *
 * The raw turn is kept long enough for lookup and draft-image instructions to
 * be acted on. This is the display/storage boundary: plumbing stops here.
 */
const INTERNAL_MARKER = /\[\[\s*(?:(?:search|read|pictures|images)\s*:|image(?:\s+(?:draft|high))?(?:\s+\d{1,5}x\d{1,5})?\s*:)[^\]\n]*\]\]/gi;
const CONTROL_TOKEN = /<\|(?:assistant|user|system|end|eot_id|im_start|im_end)\|>/gi;
const MARKER_NAMES = ['search', 'read', 'pictures', 'images', 'image'];

export function cleanReply(text: string, streaming = false): string {
  let clean = text.replace(INTERNAL_MARKER, '').replace(CONTROL_TOKEN, '');
  if (streaming) {
    const start = clean.lastIndexOf('[[');
    if (start >= 0 && !clean.slice(start).includes(']]')) {
      const name = clean.slice(start + 2).trimStart().split(/[\s:]/, 1)[0].toLowerCase();
      if (name && MARKER_NAMES.some((known) => known.startsWith(name) || name === known)) {
        clean = clean.slice(0, start).replace(/\n$/, '');
      }
    }
  }
  return clean
    .replace(/^\s*assistant\s*:\s*/i, '')
    .replace(/\n{3,}/g, '\n\n')
    .replace(/^[ \t]*\n/, '')
    .trimEnd();
}
