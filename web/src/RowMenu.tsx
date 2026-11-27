import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { EllipsisVertical } from 'lucide-react';
import './row-menu.css';

// The three-dot (⋮) menu of a table row: one small button, a list of actions when it is pressed.
// Click or Enter/Space opens it; ↑ ↓ move, Enter runs the action, Esc or a click elsewhere closes it.
// The list is drawn on top of the page (a portal with fixed position), so a table that scrolls sideways cannot clip it.

export type RowMenuItem = {
  id: string;
  label: string;
  icon?: ReactNode;
  /** Destructive action: shown in warning colours and set apart from the others. */
  danger?: boolean;
  disabled?: boolean;
  onSelect: () => void;
};

type Props = { items: RowMenuItem[]; label: string; lang: 'en' | 'ar' };

const MARGIN = 8;

export default function RowMenu({ items, label, lang }: Props) {
  const ar = lang === 'ar';
  const menuId = useId();
  const [open, setOpen] = useState(false);
  const [place, setPlace] = useState<{ top: number; left: number } | null>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);

  const close = useCallback((refocus: boolean) => {
    setOpen(false);
    setPlace(null);
    if (refocus) trigger.current?.focus();
  }, []);

  // Place the list under the button, its edge on the side the table's actions column is on; flip up when there is no room.
  useLayoutEffect(() => {
    if (!open || !trigger.current || !menu.current) return;
    const button = trigger.current.getBoundingClientRect();
    const list = menu.current.getBoundingClientRect();
    const left = Math.min(Math.max(MARGIN, ar ? button.left : button.right - list.width), window.innerWidth - list.width - MARGIN);
    let top = button.bottom + 4;
    if (top + list.height > window.innerHeight - MARGIN && button.top - list.height - 4 > MARGIN) top = button.top - list.height - 4;
    setPlace({ top, left });
  }, [open, ar, items.length]);

  // The list is invisible until it has been placed, and an invisible element cannot take the focus: focus the first action once placed.
  const placed = place !== null;
  useEffect(() => {
    if (open && placed) menu.current?.querySelector<HTMLElement>('[role="menuitem"]:not([disabled])')?.focus();
  }, [open, placed]);

  useEffect(() => {
    if (!open) return;
    const outside = (event: PointerEvent) => {
      const target = event.target as Node;
      if (menu.current?.contains(target) || trigger.current?.contains(target)) return;
      close(false);
    };
    const away = () => close(false);
    document.addEventListener('pointerdown', outside, true);
    window.addEventListener('resize', away);
    window.addEventListener('scroll', away, true);
    return () => {
      document.removeEventListener('pointerdown', outside, true);
      window.removeEventListener('resize', away);
      window.removeEventListener('scroll', away, true);
    };
  }, [open, close]);

  if (!items.length) return null;

  function onMenuKey(event: ReactKeyboardEvent<HTMLDivElement>) {
    const enabled = Array.from(menu.current?.querySelectorAll<HTMLElement>('[role="menuitem"]:not([disabled])') ?? []);
    if (!enabled.length) return;
    const at = enabled.indexOf(document.activeElement as HTMLElement);
    const go = (index: number) => { event.preventDefault(); enabled[(index + enabled.length) % enabled.length].focus(); };
    if (event.key === 'ArrowDown') go(at + 1);
    else if (event.key === 'ArrowUp') go(at <= 0 ? enabled.length - 1 : at - 1);
    else if (event.key === 'Home') go(0);
    else if (event.key === 'End') go(enabled.length - 1);
    else if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close(true); }
    else if (event.key === 'Tab') close(false);
  }

  const firstDanger = items.findIndex((item) => item.danger);

  return (
    <>
      <button
        ref={trigger}
        type="button"
        className="nq-rowmenu-trigger"
        aria-label={label}
        title={label}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={(event) => { event.stopPropagation(); if (open) close(false); else setOpen(true); }}
        onKeyDown={(event) => { if (event.key === 'ArrowDown' && !open) { event.preventDefault(); event.stopPropagation(); setOpen(true); } }}
      >
        <EllipsisVertical size={18} aria-hidden="true" />
      </button>
      {open && createPortal(
        <div
          ref={menu}
          id={menuId}
          role="menu"
          aria-label={label}
          dir={ar ? 'rtl' : 'ltr'}
          className="nq-rowmenu"
          style={{ top: place?.top ?? 0, left: place?.left ?? 0, visibility: place ? 'visible' : 'hidden' }}
          // The row behind may open its editor when clicked: nothing in here may reach it.
          onClick={(event) => event.stopPropagation()}
          onKeyDown={onMenuKey}
        >
          {items.map((item, index) => (
            <div key={item.id} role="none">
              {index === firstDanger && index > 0 && <hr className="nq-rowmenu-sep" />}
              <button
                type="button"
                role="menuitem"
                tabIndex={-1}
                disabled={item.disabled}
                className={`nq-rowmenu-item${item.danger ? ' danger' : ''}`}
                onClick={() => { close(true); item.onSelect(); }}
              >
                {item.icon && <span className="nq-rowmenu-icon" aria-hidden="true">{item.icon}</span>}
                <span>{item.label}</span>
              </button>
            </div>
          ))}
        </div>,
        document.body,
      )}
    </>
  );
}
