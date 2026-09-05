/** Letting a conversation look things up.
 *
 *  Chat has no tool-calling protocol, deliberately: local servers vary in
 *  whether they support one at all, and a feature that works on a third of the
 *  models a customer might install is worse than one that works everywhere.
 *  So the model asks in the only way every model can — by writing it — and the
 *  application does the fetching. The same shape the image preview already
 *  uses, which is why it is spelled the same way.
 *
 *      [[search: what is in iOS 27]]
 *      [[read: https://www.apple.com/ios/]]
 *
 *  Parsing is here and tested, because the failure that matters is silent: a
 *  marker the parser misses is a lookup that never happens, and the model
 *  answers from memory as though it had checked.
 */

export interface Lookup {
  kind: 'search' | 'read' | 'pictures';
  /** A query, or a URL. */
  argument: string;
}

//: Tolerant on purpose. Models produce `[[search: x]]`, `[[ search : x ]]`,
//  `[[Search: x]]` and occasionally wrap the whole thing in backticks; all of
//  those mean the same thing and none of them should be a missed lookup.
const MARKER = /\[\[\s*(search|read|pictures|images)\s*:\s*([^\]]+?)\s*\]\]/gi;

/** Every lookup a reply asks for, in order, without duplicates. */
export function findLookups(text: string): Lookup[] {
  const found: Lookup[] = [];
  const seen = new Set<string>();
  for (const match of text.matchAll(MARKER)) {
    const raw = match[1].toLowerCase();
    // `images` is what models reach for about as often as `pictures`, and a
    // near miss here is a lookup that silently never happens.
    const kind = (raw === 'images' ? 'pictures' : raw) as Lookup['kind'];
    const argument = match[2].trim();
    if (!argument) continue;
    const key = `${kind}:${argument.toLowerCase()}`;
    if (seen.has(key)) continue;      // asking twice is asking once
    seen.add(key);
    found.push({ kind, argument });
  }
  return found;
}

/** The reply with its markers taken out, for showing.
 *
 *  A marker is an instruction to the application, not part of the answer.
 *  Left in, the user reads the model's plumbing.
 */
export function stripLookups(text: string): string {
  return text
    .replace(MARKER, '')
    // A marker alone on a line leaves the line behind; collapse the run of
    // blank lines it becomes rather than leaving a hole in the answer.
    .replace(/\n{3,}/g, '\n\n')
    .replace(/^[ \t]*\n/, '')
    .trimEnd();
}

/** What a lookup is called while it runs. Shown to the user, so it says what
 *  is happening to their machine's network connection in plain words. */
export function describe(lookup: Lookup): string {
  if (lookup.kind === 'search') return `Searching the web for “${lookup.argument}”`;
  if (lookup.kind === 'pictures') return `Finding pictures of “${lookup.argument}”`;
  return `Reading ${lookup.argument}`;
}

/** How many rounds of looking up one question may take.
 *
 *  A model that searches, reads the results, and searches again is working
 *  properly. A model that searches for the same thing forever is not, and
 *  without a ceiling it would do so while the user watched.
 */
export const MAX_ROUNDS = 3;

/** The results, formatted as the turn that goes back to the model.
 *
 *  Labelled as retrieved rather than known. Without that a model will cheerfully
 *  merge what it just read with what it half-remembers and present the mixture
 *  in one voice.
 */
export function resultsTurn(parts: { lookup: Lookup; text: string }[]): string {
  const body = parts.map(({ lookup, text }) => {
    const heading = lookup.kind === 'search'
      ? `Search results for "${lookup.argument}"`
      : lookup.kind === 'pictures'
        ? `Pictures of "${lookup.argument}"`
        : `Contents of ${lookup.argument}`;
    // Bounded: a long page would otherwise crowd the question out of a small
    // model's context window, and the answer would drift off the point.
    const clipped = text.length > 6000 ? `${text.slice(0, 6000)}\n…(truncated)` : text;
    return `### ${heading}\n${clipped}`;
  }).join('\n\n');

  return (
    'These came from the web just now, in response to your request. Use them to '
    + 'answer, prefer them over what you remember, and say so if they do not '
    + 'settle the question. Do not ask for another lookup unless these genuinely '
    + 'do not answer it.\n\n' + body
  );
}
