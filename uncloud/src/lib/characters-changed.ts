/** "The cast changed."
 *
 *  Characters are created in one tab and chosen in another, and the two do not
 *  share state. Without a signal the picker only saw a new character after the
 *  app was restarted — the feature looked broken to anyone who used it in the
 *  obvious order: make the character, then use it.
 *
 *  An event rather than polling, so the list refreshes the instant it changes
 *  and never otherwise.
 */

const CHARACTERS_CHANGED = 'uncloud:characters-changed';

export function characterListChanged(): void {
  window.dispatchEvent(new CustomEvent(CHARACTERS_CHANGED));
}

export function onCharacterListChange(handler: () => void): () => void {
  window.addEventListener(CHARACTERS_CHANGED, handler);
  return () => window.removeEventListener(CHARACTERS_CHANGED, handler);
}
