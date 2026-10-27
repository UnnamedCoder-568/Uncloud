import { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Download, Minus, Plus, Scan, X } from 'lucide-react';
import { usePaneVisible } from './Panes';

/** Uses the already authenticated blob URL; opening a preview never navigates
 * away from the app or creates a public URL for a private generated image. */
export function ImageViewer({ src, alt, name, onClose }: {
  src: string; alt: string; name?: string; onClose: () => void;
}) {
  const [zoom, setZoom] = useState(1);
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    panel.current?.querySelector<HTMLButtonElement>('[aria-label="Close image"]')?.focus();
    const keys = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); onClose(); }
      if (event.key !== 'Tab') return;
      const buttons = Array.from(panel.current?.querySelectorAll<HTMLElement>('button:not(:disabled), a[href]') ?? []);
      const first = buttons[0], last = buttons.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    };
    document.addEventListener('keydown', keys);
    return () => { document.removeEventListener('keydown', keys); if (previous?.isConnected) previous.focus(); };
  }, [onClose]);
  return createPortal(
    <div className="image-viewer-backdrop" onClick={event => { if (event.target === event.currentTarget) onClose(); }}>
      <div className="image-viewer" role="dialog" aria-modal="true" aria-label={alt || 'Image preview'} ref={panel}>
        <div className="image-viewer-toolbar">
          <span className="truncate flex-1 min-w-0">{name || alt || 'Image preview'}</span>
          <button className="tb-btn" aria-label="Zoom out" disabled={zoom === 1} onClick={() => setZoom(value => Math.max(1, value - 0.5))}><Minus size={18} /></button>
          <span className="text-xs tabular-nums">{zoom === 1 ? 'Fit' : `${zoom * 100}%`}</span>
          <button className="tb-btn" aria-label="Zoom in" disabled={zoom === 4} onClick={() => setZoom(value => Math.min(4, value + 0.5))}><Plus size={18} /></button>
          <button className="tb-btn" aria-label="Fit image" onClick={() => setZoom(1)}><Scan size={18} /></button>
          {name && <a className="tb-btn" href={src} download={name} aria-label="Download image"><Download size={18} /></a>}
          <button className="tb-btn" aria-label="Close image" onClick={onClose}><X size={20} /></button>
        </div>
        <div className="image-viewer-canvas">
          <div className="image-viewer-content" style={{ width: `${zoom * 100}%`, height: zoom === 1 ? '100%' : 'auto' }}>
            <img src={src} alt={alt} style={{ maxHeight: zoom === 1 ? '100%' : undefined, width: zoom === 1 ? 'auto' : '100%' }} />
          </div>
        </div>
      </div>
    </div>, document.body);
}

function PreviewButton({ src, alt, className, name, buttonClassName = '' }: {
  src: string; alt: string; className?: string; name?: string; buttonClassName?: string;
}) {
  const [open, setOpen] = useState(false);
  const close = useCallback(() => setOpen(false), []);
  return <>
    <button type="button" className={`image-preview-button ${buttonClassName}`} aria-label={`Enlarge ${alt || 'image'}`} onClick={() => setOpen(true)}>
      <img src={src} alt={alt} className={className} />
    </button>
    {open && <ImageViewer src={src} alt={alt} name={name} onClose={close} />}
  </>;
}

export default function ImagePreview(props: Parameters<typeof PreviewButton>[0]) {
  // Hidden panes remain mounted; unmount the viewer controller when leaving a
  // workspace so a portal cannot cover the next screen or reopen on return.
  return usePaneVisible() ? <PreviewButton {...props} /> : <img src={props.src} alt={props.alt} className={props.className} />;
}
