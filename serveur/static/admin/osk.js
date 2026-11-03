/* Clavier à l'écran pour les pages de configuration sur la borne tactile.
   S'active automatiquement sur la borne (adresse 127.0.0.1 / localhost) ou avec ?osk=1 dans l'adresse.
   Sur un ordinateur du réseau, rien ne change : on utilise le clavier physique. */
(function () {
  'use strict';
  const onKiosk = ['127.0.0.1', 'localhost'].includes(location.hostname) || new URLSearchParams(location.search).get('osk') === '1';
  if (!onKiosk) return;

  const TEXT_ROWS = [
    ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0', 'DEL'],
    ['a', 'z', 'e', 'r', 't', 'y', 'u', 'i', 'o', 'p', 'é'],
    ['q', 's', 'd', 'f', 'g', 'h', 'j', 'k', 'l', 'm', 'è'],
    ['SHIFT', 'w', 'x', 'c', 'v', 'b', 'n', 'à', 'ç', '\'', '-'],
    ['HIDE', '.', 'SPACE', '/', 'ê', 'ô', 'ENTER'],
  ];
  const NUM_ROWS = [['7', '8', '9'], ['4', '5', '6'], ['1', '2', '3'], ['HIDE', '0', 'DEL'], ['ENTER']];
  const LABELS = { DEL: '⌫', SHIFT: 'Maj', SPACE: 'Espace', ENTER: 'OK', HIDE: 'Masquer' };

  const css = document.createElement('style');
  css.textContent = `
  .osk-pad { position: fixed; left: 0; right: 0; bottom: 0; z-index: 1000; background: #DDE3E5; border-top: 1px solid #C8D1D4;
    padding: 8px; display: flex; flex-direction: column; gap: 6px; box-shadow: 0 -6px 20px rgba(0,0,0,.15); touch-action: manipulation; }
  .osk-pad[hidden] { display: none; }
  .osk-pad.is-num { left: auto; width: 320px; border-left: 1px solid #C8D1D4; border-radius: 12px 0 0 0; }
  .osk-row { display: flex; gap: 6px; justify-content: center; }
  .osk-pad button { flex: 1 1 0; min-width: 0; max-width: 96px; height: 54px; border: 0; border-radius: 8px; background: #fff; color: #1A1A1A;
    font: 500 20px "Roboto", system-ui, sans-serif; box-shadow: 0 1px 1px rgba(0,0,0,.12); }
  .osk-pad.is-num button { max-width: none; }
  .osk-pad button:active { background: #D4E8EC; }
  .osk-pad button[data-k="SPACE"] { flex-grow: 5; max-width: 420px; font-size: 16px; }
  .osk-pad button[data-k="ENTER"] { background: #276577; color: #fff; flex-grow: 1.6; font-size: 17px; }
  .osk-pad button[data-k="SHIFT"], .osk-pad button[data-k="HIDE"], .osk-pad button[data-k="DEL"] { background: #EEF1F2; font-size: 16px; }
  .osk-pad button.is-on { background: #276577; color: #fff; }
  body.osk-open { padding-bottom: 330px; }
  dialog[open].osk-host { margin: 12px auto auto; max-height: calc(100vh - 360px); overflow: auto; }`;
  document.head.appendChild(css);

  const pad = document.createElement('div');
  pad.className = 'osk-pad';
  pad.hidden = true;
  pad.setAttribute('aria-label', 'Clavier à l’écran');
  document.body.appendChild(pad);

  let target = null;
  let shift = false;
  let numeric = false;

  function build() {
    pad.textContent = '';
    pad.classList.toggle('is-num', numeric);
    (numeric ? NUM_ROWS : TEXT_ROWS).forEach((row) => {
      const r = document.createElement('div');
      r.className = 'osk-row';
      row.forEach((k) => {
        const b = document.createElement('button');
        b.type = 'button';
        b.dataset.k = k;
        b.textContent = LABELS[k] || (shift ? k.toUpperCase() : k);
        if (k === 'SHIFT' && shift) b.classList.add('is-on');
        r.appendChild(b);
      });
      pad.appendChild(r);
    });
  }

  function isTextField(el) {
    if (!el || el.disabled || el.readOnly) return false;
    if (el.tagName === 'TEXTAREA') return true;
    if (el.tagName !== 'INPUT') return false;
    return ['text', 'search', 'number', 'password', 'email', 'tel', ''].includes((el.getAttribute('type') || '').toLowerCase());
  }

  function insert(text) {
    const el = target;
    let start = null, end = null;
    try { start = el.selectionStart; end = el.selectionEnd; } catch (e) { /* champs number : pas de curseur */ }
    if (start == null) {
      el.value = el.value + text;
    } else {
      el.value = el.value.slice(0, start) + text + el.value.slice(end);
      const pos = start + text.length;
      try { el.setSelectionRange(pos, pos); } catch (e) { /* ignoré */ }
    }
    el.dispatchEvent(new Event('input', { bubbles: true }));
  }

  function backspace() {
    const el = target;
    let start = null, end = null;
    try { start = el.selectionStart; end = el.selectionEnd; } catch (e) { /* number */ }
    if (start == null) { el.value = el.value.slice(0, -1); }
    else if (start !== end) { el.value = el.value.slice(0, start) + el.value.slice(end); el.setSelectionRange(start, start); }
    else if (start > 0) { el.value = el.value.slice(0, start - 1) + el.value.slice(start); el.setSelectionRange(start - 1, start - 1); }
    el.dispatchEvent(new Event('input', { bubbles: true }));
  }

  function hide() {
    pad.hidden = true;
    document.body.classList.remove('osk-open');
    document.querySelectorAll('dialog.osk-host').forEach((d) => d.classList.remove('osk-host'));
  }

  function show(el) {
    target = el;
    const wantNum = (el.getAttribute('type') || '') === 'number';
    if (wantNum !== numeric || pad.childElementCount === 0) { numeric = wantNum; shift = false; build(); }
    // une fenêtre modale (<dialog>) rend le reste de la page inactif : le clavier doit être dedans
    const dlg = el.closest('dialog');
    const host = dlg || document.body;
    if (pad.parentNode !== host) host.appendChild(pad);
    document.querySelectorAll('dialog.osk-host').forEach((d) => { if (d !== dlg) d.classList.remove('osk-host'); });
    if (dlg) dlg.classList.add('osk-host');
    pad.hidden = false;
    document.body.classList.add('osk-open');
    setTimeout(() => el.scrollIntoView({ block: 'center', behavior: 'smooth' }), 50);
  }

  // garder le focus dans le champ quand on touche le clavier
  pad.addEventListener('pointerdown', (e) => e.preventDefault());
  pad.addEventListener('mousedown', (e) => e.preventDefault());
  pad.addEventListener('click', (e) => {
    const b = e.target.closest('button');
    if (!b || !target) return;
    const k = b.dataset.k;
    if (k === 'SHIFT') { shift = !shift; build(); return; }
    if (k === 'HIDE') { target.blur(); hide(); return; }
    if (k === 'DEL') { backspace(); return; }
    if (k === 'SPACE') { insert(' '); return; }
    if (k === 'ENTER') {
      const el = target;
      const ev = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true });
      const handled = !el.dispatchEvent(ev);   // la page a géré « Entrée » (ex. page Clés)
      if (!handled && el.form && el.tagName !== 'TEXTAREA') {
        if (el.form.requestSubmit) el.form.requestSubmit(); else el.form.submit();
      }
      el.blur();
      hide();
      return;
    }
    insert(shift ? k.toUpperCase() : k);
    if (shift) { shift = false; build(); }
  });

  document.addEventListener('focusin', (e) => { if (isTextField(e.target)) show(e.target); });
  document.addEventListener('focusout', () => {
    setTimeout(() => { if (!isTextField(document.activeElement)) hide(); }, 120);
  });
})();
