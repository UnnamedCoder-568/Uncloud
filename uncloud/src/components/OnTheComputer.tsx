/**
 * Said where a control would be, on a device paired over the network.
 *
 * Folders and files belong to the computer running Uncloud. A phone cannot
 * browse that disk, and a button that does nothing when tapped reads as
 * broken — so the setting is shown, and it says where it is changed.
 */

import type { ReactNode } from 'react';
import { Monitor } from 'lucide-react';

export default function OnTheComputer({ children }: { children?: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-[11px] text-[var(--text-faint)] leading-relaxed">
      <Monitor size={11} className="shrink-0" />
      {children ?? 'Changed on the computer running Uncloud.'}
    </span>
  );
}
