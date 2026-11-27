// Browser-side half of scripts/check-ui-components.mjs (CI only, never part of the production bundle).
// It mounts the REAL RowMenu and GuidedTour components on a small fake page, drives them with clicks and key presses, and writes
// the outcome of every check as JSON into <pre id="out">. The runner opens this page in headless Chrome and reads that JSON.
// Opened with "#control" it uses a deliberately broken menu and hides every tour target: the same checks must then FAIL,
// which proves they can fail (a check that cannot fail proves nothing).
import { useState } from 'react';
import { createRoot } from 'react-dom/client';
import RowMenu from '../src/RowMenu';
import GuidedTour from '../src/GuidedTour';
import { tourStepsFor } from '../src/tourSteps';

const CONTROL = window.location.hash === '#control';
const results = [];
const errors = [];
window.addEventListener('error', (event) => errors.push(String(event.message)));
const check = (name, ok, detail = '') => results.push({ name, ok: Boolean(ok), detail: String(detail) });
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const press = (key, target) => (target || document.activeElement).dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }));
const fits = (r) => r.left >= -0.5 && r.top >= -0.5 && r.right <= window.innerWidth + 0.5 && r.bottom <= window.innerHeight + 0.5;
const touches = (a, b) => a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
const $ = (selector) => document.querySelector(selector);

// ---------------------------------------------------------------- scene 1: the three-dot menu
const calls = [];
let rowClicks = 0;
const items = [
  { id: 'edit', label: 'Edit all fields', onSelect: () => calls.push('edit') },
  { id: 'more', label: 'More', onSelect: () => calls.push('more') },
  { id: 'delete', label: 'Delete', danger: true, onSelect: () => calls.push('delete') },
];

// The control: the classic wrong way to build it. The list sits inside the table cell, nothing stops the click from reaching the
// row, there is no keyboard handling.
function BrokenRowMenu({ items: list, label }) {
  const [open, setOpen] = useState(false);
  return (
    <span style={{ position: 'relative' }}>
      <button type="button" className="nq-rowmenu-trigger" aria-label={label} aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)}>⋮</button>
      {open && (
        <div className="nq-rowmenu" role="menu" style={{ position: 'absolute', top: '100%', left: 0 }}>
          {list.map((item) => (
            <button key={item.id} type="button" role="menuitem" className={`nq-rowmenu-item${item.danger ? ' danger' : ''}`} onClick={item.onSelect}>{item.label}</button>
          ))}
        </div>
      )}
    </span>
  );
}
const Menu = CONTROL ? BrokenRowMenu : RowMenu;

function MenuScene() {
  const width = 'min(600px, calc(100vw - 32px))';
  return (
    <div style={{ padding: 8 }}>
      {/* a short box that clips whatever is drawn inside it: a menu that is not drawn on top of the page would be cut off here */}
      <div id="clip" style={{ width, height: 56, overflow: 'hidden', border: '1px solid #888' }}>
        <table style={{ width: '100%' }}><tbody>
          <tr id="row" onClick={() => { rowClicks += 1; }}>
            <td>Row</td>
            <td style={{ textAlign: 'right' }}><Menu lang="en" label="Actions for Row" items={items} /></td>
          </tr>
        </tbody></table>
      </div>
      <div id="rtl" dir="rtl" style={{ width, marginTop: 14 }}>
        {/* in a right-to-left table the actions column is the last cell, which is the left-hand one */}
        <table style={{ width: '100%' }}><tbody><tr><td>صف</td><td><Menu lang="ar" label="إجراءات الصف" items={items} /></td></tr></tbody></table>
      </div>
      <div id="empty"><Menu lang="en" label="none" items={[]} /></div>
    </div>
  );
}

async function runMenu() {
  const trigger = $('#clip .nq-rowmenu-trigger');
  check('menu: the ⋮ button is there, closed, labelled', trigger && trigger.getAttribute('aria-haspopup') === 'menu'
    && trigger.getAttribute('aria-expanded') === 'false' && trigger.getAttribute('aria-label') === 'Actions for Row' && !$('.nq-rowmenu'));
  check('menu: no button at all when there is nothing to do', !$('#empty .nq-rowmenu-trigger'));

  trigger.click(); await sleep(80);
  let menu = $('.nq-rowmenu');
  check('menu: a click opens a menu with the 3 actions', menu && menu.getAttribute('role') === 'menu'
    && menu.querySelectorAll('[role="menuitem"]').length === 3 && trigger.getAttribute('aria-expanded') === 'true');
  check('menu: it is drawn on top of the page, not inside the clipping table', menu && menu.parentElement === document.body);
  const r = menu.getBoundingClientRect(); const t = trigger.getBoundingClientRect();
  check('menu: it is fully inside the window', fits(r), JSON.stringify(r));
  check('menu: it sits under the button, edge to edge on the right (English)', r.top >= t.bottom && Math.abs(r.right - t.right) <= 2, `menu.right=${r.right} button.right=${t.right}`);
  check('menu: nothing covers or clips it (the point in its middle belongs to it)', menu.contains(document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2)));
  const listed = Array.from(menu.querySelectorAll('[role="menuitem"]'));
  check('menu: the first action has the keyboard focus', document.activeElement === listed[0]);
  check('menu: the delete action is set apart (a separator) and styled as dangerous',
    menu.querySelectorAll('.nq-rowmenu-sep').length === 1 && listed[2].classList.contains('danger') && !listed[0].classList.contains('danger'));
  check('menu: opening it did not open the row behind it', rowClicks === 0, `rowClicks=${rowClicks}`);

  press('ArrowDown'); check('menu: ArrowDown moves to the next action', document.activeElement === listed[1]);
  press('ArrowDown'); press('ArrowDown'); check('menu: ArrowDown wraps round to the first', document.activeElement === listed[0]);
  press('ArrowUp'); check('menu: ArrowUp wraps round to the last', document.activeElement === listed[2]);
  press('Home'); check('menu: Home goes to the first', document.activeElement === listed[0]);
  press('End'); check('menu: End goes to the last', document.activeElement === listed[2]);

  press('Escape'); await sleep(60);
  check('menu: Esc closes it and gives the focus back to the button', !$('.nq-rowmenu') && document.activeElement === trigger);

  trigger.focus(); press('ArrowDown', trigger); await sleep(80);
  check('menu: ArrowDown on the button opens it from the keyboard', Boolean($('.nq-rowmenu')) && document.activeElement === $('.nq-rowmenu [role="menuitem"]'));
  press('Tab'); await sleep(60);
  check('menu: Tab closes it', !$('.nq-rowmenu'));

  trigger.click(); await sleep(80);
  trigger.click(); await sleep(60);
  check('menu: pressing the button again closes it', !$('.nq-rowmenu'));

  trigger.click(); await sleep(80);
  $('.nq-rowmenu [role="menuitem"]').click(); await sleep(60);
  check('menu: choosing an action runs it once and closes the menu', calls.join() === 'edit' && !$('.nq-rowmenu'), calls.join());
  check('menu: choosing an action did not open the row behind it', rowClicks === 0, `rowClicks=${rowClicks}`);

  trigger.click(); await sleep(80);
  Array.from($('.nq-rowmenu').querySelectorAll('[role="menuitem"]'))[2].click(); await sleep(60);
  check('menu: the delete action runs too', calls.join() === 'edit,delete', calls.join());

  trigger.click(); await sleep(80);
  document.body.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true })); await sleep(60);
  check('menu: a click anywhere else closes it', !$('.nq-rowmenu'));

  trigger.click(); await sleep(80);
  window.dispatchEvent(new Event('scroll')); await sleep(60);
  check('menu: scrolling closes it (it would otherwise float away from its row)', !$('.nq-rowmenu'));

  $('#row td').click(); await sleep(20);
  check('control: a click on the row itself does reach the row (so the checks above mean something)', rowClicks >= 1, `rowClicks=${rowClicks}`);

  const rtlTrigger = $('#rtl .nq-rowmenu-trigger');
  rtlTrigger.click(); await sleep(80);
  menu = $('.nq-rowmenu');
  const rr = menu.getBoundingClientRect(); const rt = rtlTrigger.getBoundingClientRect();
  check('menu (Arabic): it is right-to-left, inside the window, edge to edge on the left',
    menu.getAttribute('dir') === 'rtl' && fits(rr) && Math.abs(rr.left - rt.left) <= 2, `menu.left=${rr.left} button.left=${rt.left}`);
  press('Escape'); await sleep(60);
}

// ---------------------------------------------------------------- scene 2: the first-login tour
// Every target the tour can point at has a box here. "company" is left out on purpose: a step whose target is not on the page must
// fall back to a centred card. A target the tour knows and this list does not is reported, so a new step cannot slip past unchecked.
const PRESENT = ['sidebar', 'language', 'tour-replay', 'nav-home', 'nav-fleet', 'nav-safety', 'nav-maintenance', 'nav-reports', 'nav-admin'];
const ABSENT_ON_PURPOSE = ['company'];
const BOXES = {
  sidebar: { left: 0, top: 0, width: 240, height: 600 },
  language: { right: 20, top: 8, width: 90, height: 34 },
  'tour-replay': { right: 120, top: 8, width: 80, height: 34 },
  'nav-home': { left: 10, top: 60, width: 220, height: 40 },
  'nav-fleet': { left: 10, top: 120, width: 220, height: 40 },
  'nav-safety': { left: 10, top: 180, width: 220, height: 40 },
  'nav-maintenance': { left: 10, top: 240, width: 220, height: 40 },
  'nav-reports': { left: 10, top: 300, width: 220, height: 40 },
  'nav-admin': { left: 10, top: 540, width: 220, height: 40 },
};
let closes = 0;

function TourScene() {
  const [open, setOpen] = useState(false);
  const [lang, setLang] = useState('en');
  window.__reopen = () => setOpen(true);
  return (
    <div style={{ position: 'relative', height: 620 }}>
      {PRESENT.map((id) => (
        <div key={id} data-tour={id} style={{ position: 'absolute', border: '1px solid #456', background: '#1c2f3f', display: CONTROL ? 'none' : 'block', ...BOXES[id] }} />
      ))}
      <GuidedTour open={open} role="super_admin" lang={lang} onClose={() => { closes += 1; setOpen(false); }} onSwitchLang={setLang} />
    </div>
  );
}

const card = () => $('[role="dialog"]');
const counter = () => (($('.nq-tour-count') || {}).textContent || '').trim();
// The spotlight slides to the next target with a 0.2 s CSS transition, and a headless page with a virtual clock does not advance
// transitions reliably: finish every running one, then measure where the spotlight ended up.
const settle = async () => {
  await sleep(80);
  document.getAnimations().forEach((animation) => { try { animation.finish(); } catch { /* an animation that cannot finish is already over */ } });
  await sleep(80);
};

async function runTour() {
  const narrow = window.innerWidth < 720;
  const steps = tourStepsFor('super_admin');
  const n = steps.length;

  window.__reopen(); await sleep(200);
  check('tour: the card is on screen and is a dialog', card() && card().getAttribute('aria-modal') === 'true');
  check('tour: step 1 is the welcome card, centred, with no spotlight', $('#nq-tour-title') && $('#nq-tour-title').textContent === 'Welcome to Nuqati'
    && card().classList.contains('nq-tour-card--center') && !$('.nq-tour-hole'));
  check(`tour: it counts the steps of this role (Step 1 / ${n})`, counter() === `Step 1 / ${n}`, counter());
  check('tour: the focus is on the Next button', document.activeElement === $('[data-tour-primary]'));
  check('tour: Back is disabled on the first step', $('.nq-tour-secondary').disabled === true);

  for (let i = 1; i < n; i += 1) {
    press('ArrowRight'); await settle();
    const step = steps[i]; const c = card();
    if (!c) { check(`tour step ${i + 1} (${step.id}): the card is there`, false); break; }
    const hole = $('.nq-tour-hole');
    const cr = c.getBoundingClientRect();
    check(`tour step ${i + 1} (${step.id}): shows its own title`, $('#nq-tour-title').textContent === step.title.en, $('#nq-tour-title').textContent);
    check(`tour step ${i + 1} (${step.id}): the card is fully inside the window`, fits(cr), JSON.stringify(cr));
    if (!step.target || ABSENT_ON_PURPOSE.includes(step.target)) {
      check(`tour step ${i + 1} (${step.id}): its target is not on the page, so a centred card with no spotlight`, c.classList.contains('nq-tour-card--center') && !hole, c.className);
    } else if (!PRESENT.includes(step.target)) {
      check(`tour step ${i + 1} (${step.id}): the harness has a box for its target "${step.target}"`, false, 'add the target to PRESENT and BOXES in scripts/ui-harness.jsx');
    } else {
      const target = $(`[data-tour="${step.target}"]`);
      const hr = hole ? hole.getBoundingClientRect() : null; const tr = target.getBoundingClientRect();
      check(`tour step ${i + 1} (${step.id}): the spotlight surrounds its target`, hr && hr.left <= tr.left + 0.5 && hr.top <= tr.top + 0.5 && hr.right >= tr.right - 0.5 && hr.bottom >= tr.bottom - 0.5, hr ? JSON.stringify(hr) : 'no spotlight');
      check(`tour step ${i + 1} (${step.id}): ${narrow ? 'on a narrow screen the card is a bottom sheet' : 'the card sits beside the target without covering it'}`,
        narrow ? c.classList.contains('nq-tour-card--sheet') : (c.classList.contains('nq-tour-card--anchored') && hr && !touches(cr, hr)), c.className);
    }
  }
  check('tour: the last step offers Finish', $('[data-tour-primary]') && $('[data-tour-primary]').textContent.includes('Finish'));
  $('[data-tour-primary]').click(); await sleep(80);
  check('tour: Finish closes the tour (once)', !card() && closes === 1, `closes=${closes}`);

  window.__reopen(); await sleep(150);
  check(`tour: it can be opened again and starts at step 1`, card() && counter() === `Step 1 / ${n}`, counter());
  press('ArrowRight'); await sleep(100);
  check('tour: ArrowRight goes to step 2', counter() === `Step 2 / ${n}`, counter());
  $('.nq-tour-secondary').click(); await sleep(100);
  check('tour: Back returns to the previous step', counter() === `Step 1 / ${n}`, counter());

  $('.nq-tour-top-actions .nq-tour-quiet').click(); await sleep(150);
  check('tour: the language button inside the tour switches to Arabic, right-to-left',
    card().getAttribute('dir') === 'rtl' && $('#nq-tour-title').textContent === steps[0].title.ar);
  check('tour (Arabic): the counter is Arabic', counter() === `الخطوة 1 / ${n}`, counter());
  press('ArrowLeft'); await sleep(100);
  check('tour (Arabic): ArrowLeft goes forward', counter() === `الخطوة 2 / ${n}`, counter());
  press('ArrowRight'); await sleep(100);
  check('tour (Arabic): ArrowRight goes back', counter() === `الخطوة 1 / ${n}`, counter());
  check('tour (Arabic): the card is inside the window', fits(card().getBoundingClientRect()));
  $('.nq-tour-top-actions .nq-tour-quiet').click(); await sleep(150);
  check('tour: switching back gives English, left-to-right', card().getAttribute('dir') === 'ltr' && $('#nq-tour-title').textContent === steps[0].title.en);

  const buttons = Array.from(card().querySelectorAll('button:not([disabled])'));
  buttons[buttons.length - 1].focus(); press('Tab'); await sleep(30);
  check('tour: Tab from the last button goes to the first (the focus cannot leave the card)', document.activeElement === buttons[0]);

  press('Escape'); await sleep(100);
  check('tour: Esc closes it', !card() && closes === 2, `closes=${closes}`);
}

function Scenes() { return <><MenuScene /><TourScene /></>; }

createRoot(document.getElementById('root')).render(<Scenes />);
(async () => {
  await sleep(200);
  for (const [name, run] of [['menu', runMenu], ['tour', runTour]]) {
    try { await run(); } catch (error) { check(`the ${name} checks ran to the end`, false, error && error.stack ? error.stack : error); }
  }
  check('no script error was raised on the page', errors.length === 0, errors.join(' | '));
  $('#out').textContent = JSON.stringify({ control: CONTROL, width: window.innerWidth, height: window.innerHeight, results });
})();
