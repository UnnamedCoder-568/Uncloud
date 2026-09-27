import { useCallback, useLayoutEffect, useRef, type RefObject, type TextareaHTMLAttributes } from 'react';

/** Grow on typing, paste, dictation and layout changes, including a hidden tab
 * becoming visible. Respect the CSS ceiling so long drafts scroll internally. */
export default function AutoGrowTextarea({ inputRef, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement> & { inputRef?: RefObject<HTMLTextAreaElement | null> }) {
  const ownRef = useRef<HTMLTextAreaElement>(null);
  const field = inputRef ?? ownRef;
  const resize = useCallback((allowCollapse = true) => {
    const el = field.current;
    if (!el || !el.clientWidth) return;
    const style = getComputedStyle(el);
    const line = parseFloat(style.lineHeight) || 21;
    const padding = parseFloat(style.paddingTop) + parseFloat(style.paddingBottom);
    const border = parseFloat(style.borderTopWidth) + parseFloat(style.borderBottomWidth);
    const ceiling = parseFloat(style.maxHeight) || window.innerHeight * 0.4;
    el.style.height = '0px';
    const natural = Math.max(el.scrollHeight + border, line * (props.rows ?? 1) + padding + border, parseFloat(style.minHeight) || 0);
    const height = Math.min(natural, ceiling);
    el.style.height = `${height}px`;
    el.style.overflowY = natural > ceiling + 1 ? 'auto' : 'hidden';
    if (allowCollapse || natural > line + padding + border + 2) {
      el.dataset.expanded = String(natural > line + padding + border + 2);
    }
  }, [field, props.rows]);
  useLayoutEffect(() => resize(), [props.value, props.rows, resize]);
  useLayoutEffect(() => {
    const el = field.current;
    if (!el) return;
    let width = el.clientWidth;
    const observer = new ResizeObserver(() => {
      if (el.clientWidth !== width) { width = el.clientWidth; resize(false); }
    });
    observer.observe(el);
    const onResize = () => resize(false);
    window.addEventListener('resize', onResize);
    return () => { observer.disconnect(); window.removeEventListener('resize', onResize); };
  }, [resize]);
  return <textarea {...props} ref={field} onInput={(event) => {
    props.onInput?.(event); resize();
  }} />;
}
