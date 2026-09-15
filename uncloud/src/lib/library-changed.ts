/** "A model was added."
 *
 *  Models are added from the Models page and from the picker in whichever
 *  view needs one, and every other view that lists models holds its own copy
 *  of the library. Without a signal a model added from the Image picker would
 *  not appear in Chat until the app restarted.
 */

import { useEffect, useState } from 'react';

const LIBRARY_CHANGED = 'uncloud:library-changed';

export function libraryChanged(): void {
  window.dispatchEvent(new CustomEvent(LIBRARY_CHANGED));
}

export function onLibraryChange(handler: () => void): () => void {
  window.addEventListener(LIBRARY_CHANGED, handler);
  return () => window.removeEventListener(LIBRARY_CHANGED, handler);
}

/** A number that goes up whenever the library changes — put it in the
 *  dependencies of whatever reads the library. */
export function useLibraryVersion(): number {
  const [version, setVersion] = useState(0);
  useEffect(() => onLibraryChange(() => setVersion((v) => v + 1)), []);
  return version;
}
