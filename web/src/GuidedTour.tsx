import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties } from 'react';
import { ArrowLeft, ArrowRight, Globe2, X } from 'lucide-react';
import { tourStepsFor } from './tourSteps';
import './guided-tour.css';

// First-login tour: a spotlight on the part of the page a step talks about, plus a card with the text.
// It never changes anything in the app; it only reads element positions. Remembered per user and per browser.

const KEY = (userId: number) => `nuqati.tour.v1.${userId}`;

export function tourSeen(userId: number): boolean {
  try { return localStorage.getItem(KEY(userId)) !== null; } catch { return false; }
}
export function markTourSeen(userId: number): void {
  try { localStorage.setItem(KEY(userId), new Date().toISOString()); } catch { /* storage blocked: the tour may show again, nothing breaks */ }
}

type Props = {
  open: boolean;
  role: string;
  lang: 'en' | 'ar';
  onClose: () => void;
  onSwitchLang: (next: 'en' | 'ar') => void;
};

const PAD = 8;       // space between the spotlight edge and the element
const CARD_W = 380;  // card width next to a spotlight
const GAP = 16;

export default function GuidedTour({ open, role, lang, onClose, onSwitchLang }: Props) {
  const ar = lang === 'ar';
  const t = (en: string, arabic: string) => (ar ? arabic : en);
  const steps = useMemo(() => tourStepsFor(role), [role]);
  const [index, setIndex] = useState(0);
  const [rect, setRect] = useState<DOMRect | null>(null);
  const [viewport, setViewport] = useState({ w: 1280, h: 800 });
  const cardRef = useRef<HTMLDivElement>(null);
  const step = steps[Math.min(index, steps.length - 1)];
  const last = index >= steps.length - 1;

  useEffect(() => { if (open) setIndex(0); }, [open]);

  const measure = useCallback(() => {
    setViewport({ w: window.innerWidth, h: window.innerHeight });
    const element = step?.target ? document.querySelector<HTMLElement>(`[data-tour="${step.target}"]`) : null;
    if (!element) { setRect(null); return; }
    const box = element.getBoundingClientRect();
    setRect(box.width > 0 && box.height > 0 ? box : null);
  }, [step]);

  useLayoutEffect(() => {
    if (!open || !step) return;
    const element = step.target ? document.querySelector<HTMLElement>(`[data-tour="${step.target}"]`) : null;
    element?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' });
    measure();
  }, [open, step, measure, lang]);

  useEffect(() => {
    if (!open) return;
    window.addEventListener('resize', measure);
    window.addEventListener('scroll', measure, true);
    return () => { window.removeEventListener('resize', measure); window.removeEventListener('scroll', measure, true); };
  }, [open, measure]);

  useEffect(() => {
    if (open) cardRef.current?.querySelector<HTMLElement>('[data-tour-primary]')?.focus();
  }, [open, index]);

  const next = useCallback(() => { if (index >= steps.length - 1) onClose(); else setIndex(index + 1); }, [index, steps.length, onClose]);
  const back = useCallback(() => setIndex((i) => Math.max(0, i - 1)), []);

  useEffect(() => {
    if (!open) return;
    const forward = ar ? 'ArrowLeft' : 'ArrowRight';
    const backward = ar ? 'ArrowRight' : 'ArrowLeft';
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') { event.preventDefault(); onClose(); return; }
      if (event.key === forward) { event.preventDefault(); next(); return; }
      if (event.key === backward) { event.preventDefault(); back(); return; }
      if (event.key === 'Tab' && cardRef.current) {
        const items = Array.from(cardRef.current.querySelectorAll<HTMLElement>('button:not([disabled])'));
        if (!items.length) return;
        const first = items[0]; const lastItem = items[items.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); lastItem.focus(); }
        else if (!event.shiftKey && document.activeElement === lastItem) { event.preventDefault(); first.focus(); }
      }
    }
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, ar, next, back, onClose]);

  if (!open || !step) return null;

  const hole = rect ? { top: rect.top - PAD, left: rect.left - PAD, width: rect.width + PAD * 2, height: rect.height + PAD * 2 } : null;
  const narrow = viewport.w < 720;
  const mode: 'center' | 'sheet' | 'anchored' = !hole ? 'center' : narrow ? 'sheet' : 'anchored';
  let cardStyle: CSSProperties | undefined;
  if (mode === 'anchored' && hole) {
    const spaceRight = viewport.w - (hole.left + hole.width);
    let left: number;
    let top = Math.max(12, Math.min(viewport.h - 330, hole.top));
    if (spaceRight >= CARD_W + GAP + 12) left = hole.left + hole.width + GAP;
    else if (hole.left >= CARD_W + GAP + 12) left = hole.left - CARD_W - GAP;
    else { left = Math.max(12, Math.min(viewport.w - CARD_W - 12, hole.left)); top = Math.max(12, Math.min(viewport.h - 330, hole.top + hole.height + GAP)); }
    cardStyle = { left, top, width: CARD_W };
  }

  const dots = steps.map((s, i) => <span key={s.id} className={`nq-tour-dot${i === index ? ' on' : i < index ? ' done' : ''}`} />);
  const BackIcon = ar ? ArrowRight : ArrowLeft;
  const NextIcon = ar ? ArrowLeft : ArrowRight;

  return (
    <div className="nq-tour-overlay" data-testid="guided-tour">
      {hole ? <div className="nq-tour-hole" style={{ top: hole.top, left: hole.left, width: hole.width, height: hole.height }} /> : <div className="nq-tour-dim" />}
      <div
        ref={cardRef}
        className={`nq-tour-card nq-tour-card--${mode}`}
        style={cardStyle}
        dir={ar ? 'rtl' : 'ltr'}
        role="dialog"
        aria-modal="true"
        aria-labelledby="nq-tour-title"
        aria-describedby="nq-tour-body"
      >
        <div className="nq-tour-top">
          <span className="nq-tour-count">{t('Step', 'الخطوة')} {index + 1} / {steps.length}</span>
          <span className="nq-tour-top-actions">
            <button type="button" className="nq-tour-quiet" onClick={() => onSwitchLang(ar ? 'en' : 'ar')}><Globe2 size={14} aria-hidden="true" />{ar ? 'English' : 'العربية'}</button>
            <button type="button" className="nq-tour-icon" onClick={onClose} aria-label={t('Close the tour', 'إغلاق الجولة')}><X size={16} aria-hidden="true" /></button>
          </span>
        </div>
        <h2 id="nq-tour-title">{ar ? step.title.ar : step.title.en}</h2>
        <p id="nq-tour-body">{ar ? step.body.ar : step.body.en}</p>
        <div className="nq-tour-dots" aria-hidden="true">{dots}</div>
        <div className="nq-tour-footer">
          <button type="button" className="nq-tour-quiet" onClick={onClose}>{last ? t('Close', 'إغلاق') : t('Skip tour', 'تخطي الجولة')}</button>
          <span className="nq-tour-nav">
            <button type="button" className="nq-tour-secondary" onClick={back} disabled={index === 0}><BackIcon size={15} aria-hidden="true" />{t('Back', 'السابق')}</button>
            <button type="button" className="nq-tour-primary" data-tour-primary onClick={next}>{last ? t('Finish', 'إنهاء') : t('Next', 'التالي')}{!last && <NextIcon size={15} aria-hidden="true" />}</button>
          </span>
        </div>
      </div>
    </div>
  );
}
