/* Configuration des clés : nom (alias) et bâtiment, enregistrés à la sortie de chaque case */
(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const pad = (n) => String(n).padStart(2, '0');
  let keys = [];
  let toastTimer = null;

  async function api(url, opts) {
    const r = await fetch(url, opts);
    if (r.status === 401) { location.href = '/?admin=1'; throw new Error('Session admin expirée'); }
    let data = null;
    try { data = await r.json(); } catch (e) { /* vide */ }
    if (!r.ok) throw new Error((data && data.error) || 'Erreur ' + r.status);
    return data;
  }

  function toast(text, isError) {
    const t = $('toast');
    t.textContent = text;
    t.className = 'toast' + (isError ? ' is-error' : '');
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { t.hidden = true; }, 2500);
  }

  async function load() {
    try { keys = await api('/api/keys'); render(); } catch (e) { toast(e.message, true); }
  }

  function updateBuildings() {
    const set = [...new Set(keys.map((k) => k.building).filter(Boolean))].sort((a, b) => a.localeCompare(b, 'fr'));
    const dl = $('buildings');
    dl.textContent = '';
    set.forEach((b) => { const o = document.createElement('option'); o.value = b; dl.appendChild(o); });
    const named = keys.filter((k) => k.custom).length;
    $('counts').textContent = keys.length + ' clés · ' + named + ' nommée' + (named > 1 ? 's' : '') + ' · ' + set.length + ' bâtiment' + (set.length > 1 ? 's' : '');
  }

  function input(k, field) {
    const i = document.createElement('input');
    i.className = 'cell-input';
    i.value = field === 'label' ? (k.custom ? k.label : '') : k.building;
    i.placeholder = field === 'label' ? 'Clé n°' + k.key_number : 'ex. Bâtiment A';
    i.setAttribute('aria-label', (field === 'label' ? 'Nom de la clé ' : 'Bâtiment de la clé ') + k.key_number);
    i.maxLength = field === 'label' ? 100 : 120;
    if (field === 'building') i.setAttribute('list', 'buildings');
    i.dataset.saved = i.value;
    const save = async () => {
      if (i.value.trim() === i.dataset.saved) return;
      i.classList.remove('is-saved', 'is-error');
      try {
        const r = await api('/api/keys/' + k.key_number, {
          method: 'PATCH', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ [field]: i.value }),
        });
        Object.assign(k, r);
        i.value = field === 'label' ? (r.custom ? r.label : '') : r.building;
        i.dataset.saved = i.value;
        i.classList.add('is-saved');
        setTimeout(() => i.classList.remove('is-saved'), 1200);
        updateBuildings();
      } catch (e) { i.classList.add('is-error'); toast(e.message, true); }
    };
    i.addEventListener('blur', save);
    i.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); i.blur(); }
      if (e.key === 'Escape') { i.value = i.dataset.saved; i.blur(); }
    });
    return i;
  }

  function render() {
    const q = $('search').value.trim().toLowerCase();
    const tb = $('rows');
    tb.textContent = '';
    keys.filter((k) => !q || String(k.key_number) === q.replace('#', '') || pad(k.key_number) === q.replace('#', '')
        || k.label.toLowerCase().includes(q) || k.building.toLowerCase().includes(q))
      .forEach((k) => {
        const tr = document.createElement('tr');
        const tdN = document.createElement('td'); tdN.className = 'num'; tdN.textContent = '#' + pad(k.key_number);
        const tdL = document.createElement('td'); tdL.appendChild(input(k, 'label'));
        const tdB = document.createElement('td'); tdB.appendChild(input(k, 'building'));
        const tdS = document.createElement('td');
        const st = document.createElement('span');
        const out = k.status !== 'PRESENT';
        st.className = 'st' + (out ? ' st--out' : '');
        const dot = document.createElement('span'); dot.className = 'st__dot';
        st.append(dot, document.createTextNode(out ? 'Sortie' + (k.borrower ? ' · ' + k.borrower : '') : 'Présente'));
        tdS.appendChild(st);
        const tdLed = document.createElement('td'); tdLed.className = 'right';
        const bLed = document.createElement('button');
        bLed.type = 'button'; bLed.className = 'btn btn--light btn--sm'; bLed.textContent = 'Repérer';
        bLed.setAttribute('aria-label', 'Faire clignoter la LED de la clé ' + k.key_number);
        bLed.addEventListener('click', () => ledTest('identify', k.key_number));
        tdLed.appendChild(bLed);
        tr.append(tdN, tdL, tdB, tdS, tdLed);
        tb.appendChild(tr);
      });
    updateBuildings();
  }

  $('search').addEventListener('input', render);

  // ------------------------------------------------------------------ test des LED
  async function ledTest(mode, key) {
    const s = $('led-status');
    s.className = 'ledtest__status';
    s.textContent = 'Envoi…';
    try {
      const sent = await api('/api/leds/test', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ mode, key }) });
      const t0 = sent.t;  // heure du serveur au moment de l'envoi
      const what = mode === 'off' ? 'LED éteintes' : mode === 'identify' ? 'La LED de la clé #' + pad(key) + ' doit clignoter en jaune' : 'Statut affiché : vert = présente, rouge = sortie';
      // l'Arduino répond par un accusé de réception : on le vérifie 1,5 s plus tard
      setTimeout(async () => {
        try {
          const r = await api('/api/leds/ack');
          const ack = r && r.last_ack;
          if (ack && ack.t >= t0) { s.className = 'ledtest__status is-ok'; s.textContent = what + ' — l’Arduino a bien reçu la commande.'; }
          else { s.className = 'ledtest__status is-ko'; s.textContent = 'Commande envoyée, mais l’Arduino n’a pas répondu : armoire_leds.h n’est pas chargé dans le sketch, ou armoireLoop() n’est pas appelé.'; }
        } catch (e) { /* ignoré */ }
      }, 1500);
      s.textContent = what + '…';
    } catch (e) { s.className = 'ledtest__status is-ko'; s.textContent = e.message; }
  }
  document.querySelectorAll('[data-led]').forEach((b) => b.addEventListener('click', () => ledTest(b.dataset.led)));

  // Sur la borne : retour automatique à l'accueil après 5 min sans action
  if (['127.0.0.1', 'localhost'].includes(location.hostname)) {
    let idle;
    const arm = () => { clearTimeout(idle); idle = setTimeout(() => { location.href = '/admin/logout'; }, 5 * 60 * 1000); };
    ['pointerdown', 'keydown'].forEach((ev) => document.addEventListener(ev, arm, { passive: true }));
    arm();
  }

  load();
})();
