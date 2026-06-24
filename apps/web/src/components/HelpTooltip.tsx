import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { HelpCircle } from 'lucide-react';
import { cn } from '../lib/utils';

interface HelpTooltipProps {
  title?: string;
  content: string;
  align?: 'left' | 'center' | 'right';
  className?: string;
}

const POPUP_W = 288; // w-72 = 18rem = 288px

export function HelpTooltip({ title, content, align = 'center', className }: HelpTooltipProps) {
  const [open, setOpen] = useState(false);
  const [style, setStyle] = useState<React.CSSProperties>({});
  const wrapRef = useRef<HTMLDivElement>(null);
  const btnRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;

    function reposition() {
      if (!btnRef.current) return;
      const rect = btnRef.current.getBoundingClientRect();
      const showBelow = rect.top < 160;

      let left: number;
      if (align === 'left') {
        left = rect.left;
      } else if (align === 'right') {
        left = rect.right - POPUP_W;
      } else {
        left = rect.left + rect.width / 2 - POPUP_W / 2;
      }

      // Clamp so popup never bleeds off the viewport edges
      left = Math.max(8, Math.min(left, window.innerWidth - POPUP_W - 8));

      setStyle({
        position: 'fixed',
        zIndex: 9999,
        left,
        ...(showBelow
          ? { top: rect.bottom + 8 }
          : { top: rect.top - 8, transform: 'translateY(-100%)' }),
      });
    }

    reposition();

    const close = (e: MouseEvent | TouchEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', close);
    document.addEventListener('touchstart', close);
    window.addEventListener('scroll', reposition, true);
    window.addEventListener('resize', reposition);

    return () => {
      document.removeEventListener('mousedown', close);
      document.removeEventListener('touchstart', close);
      window.removeEventListener('scroll', reposition, true);
      window.removeEventListener('resize', reposition);
    };
  }, [open, align]);

  const popup = open
    ? createPortal(
        <div
          style={style}
          className="w-72 rounded-lg border border-border bg-popover text-popover-foreground shadow-xl p-3 text-left"
        >
          {title && (
            <p className="text-xs font-semibold text-foreground pb-1.5 mb-1.5 border-b border-border/50">
              {title}
            </p>
          )}
          <p className="text-xs text-muted-foreground leading-relaxed whitespace-pre-line">
            {content}
          </p>
        </div>,
        document.body,
      )
    : null;

  return (
    <div ref={wrapRef} className={cn('relative inline-flex items-center', className)}>
      <button
        ref={btnRef}
        type="button"
        aria-label="Help"
        onClick={(e) => {
          e.stopPropagation();
          setOpen((v) => !v);
        }}
        className={cn(
          'inline-flex items-center justify-center h-4 w-4 rounded-full shrink-0 transition-colors',
          open
            ? 'text-primary bg-primary/10'
            : 'text-muted-foreground hover:text-primary hover:bg-primary/10',
        )}
      >
        <HelpCircle className="h-3.5 w-3.5" />
      </button>

      {popup}
    </div>
  );
}
