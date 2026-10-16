/** Portable lookup handoff for local servers with differing native tool support.
 *  The model requests a lookup in its answer; the app fetches the evidence.
 *  This is an application protocol, not a claim of universal native tool calling.
 *
 *      [[search: orbital period of Mars]]
 *      [[read: https://example.org/source]]
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

export type WebPhase = 'request' | 'results' | 'final';

export function lookupKey(lookup: Lookup): string {
  const argument = lookup.argument.trim().replace(/\s+/g, ' ');
  if (lookup.kind === 'read') {
    try {
      const url = new URL(argument);
      url.hash = '';
      return `read:${url.href}`;
    } catch { return `read:${argument}`; }
  }
  return `${lookup.kind}:${argument.toLowerCase()}`;
}

/** Per-reply handoff state. Only final-answer markers enter this protocol;
 * thinking text is never a tool request. Completed lookups cannot repeat. */
export class LookupSession {
  phase: WebPhase = 'request';
  private completed = new Set<string>();
  private rounds = 0;

  record(lookups: Lookup[]) {
    for (const lookup of lookups) this.completed.add(lookupKey(lookup));
    this.rounds++;
    this.phase = 'results';
  }

  next(reply: string, pictures = false):
    { kind: 'done' | 'answer'; lookups: [] } | { kind: 'lookup'; lookups: Lookup[] } {
    const requested = findLookups(reply).filter(l => pictures || l.kind !== 'pictures');
    return this.nextRequests(requested);
  }

  nextRequests(requested: Lookup[]):
    { kind: 'done' | 'answer'; lookups: [] } | { kind: 'lookup'; lookups: Lookup[] } {
    if (!requested.length) return { kind: 'done', lookups: [] };
    if (this.phase === 'final') {
      throw new Error('The model kept requesting a lookup instead of answering. The reply was stopped; no repeated search was run.');
    }
    const seen = new Set(this.completed);
    const fresh = requested.filter(l => {
      const key = lookupKey(l);
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
    if (fresh.length && this.rounds < MAX_ROUNDS) return { kind: 'lookup', lookups: fresh };
    // One explicit answer pass with the existing evidence, without the tool
    // protocol in its prompt. Never silently restart the same lookup.
    this.phase = 'final';
    return { kind: 'answer', lookups: [] };
  }
}

/** The results, formatted as the turn that goes back to the model.
 *
 *  Labelled as retrieved rather than known. Without that a model will cheerfully
 *  merge what it just read with what it half-remembers and present the mixture
 *  in one voice.
 */
export function resultsTurn(parts: { lookup: Lookup; text: string }[]): string {
  return JSON.stringify({ web_results: parts.map(({ lookup, text }) => ({
    type: lookup.kind, query: lookup.argument, content: text.slice(0, 16000),
    ...(text.length > 16000 ? { truncated: true } : {}),
  })) });
}

/** Read an explicitly supplied source immediately. Search decisions belong
 * to the model with the actual conversation, never a topic/keyword classifier. */
export function initialWebLookup(text: string): Lookup | null {
  const url = text.match(/https?:\/\/[^\s<>"'`]+/)?.[0]?.replace(/[.,;)]+$/, '');
  if (url && /\b(read|summarize|inspect|check|look\s+at)\b/i.test(text)) {
    return { kind: 'read', argument: url };
  }
  return null;
}

/** Availability of images is not a reason to inject their protocol every turn. */
export function wantsPictures(text: string): boolean {
  return /\b(draw|illustrate|sketch|render)\b/i.test(text)
    || /\b(make|create|generate|show|find|display)\b.{0,50}\b(image|picture|photo|photograph|illustration|diagram|wallpaper|poster)\b/i.test(text);
}
