/* Journal : consultation filtrée et export CSV */
(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const TAG = { badge_scan: 'badge', badge_unknown: 'error', key_change: 'new', door: 'update', session_end: 'update',
                user_admin: 'same', admin_login: 'same', admin_denied: 'error' };
  const iso = (d) => d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');

  // 7 derniers jours par défaut
  const today = new Date();
  const weekAgo = new Date(today.getTime() - 6 * 864e5);
  $('from').value = iso(weekAgo);
  $('to').value = iso(today);

  function params() {
    const p = new URLSearchParams();
    if ($('from').value) p.set('from', $('from').value);
    if ($('to').value) p.set('to', $('to').value);
    if ($('type').value !== 'all') p.set('type', $('type').value);
    if ($('q').value.trim()) p.set('q', $('q').value.trim());
    return p;
  }

  async function load() {
    const p = params();
    $('exp-journal').href = '/api/journal/export.csv?' + p.toString();
    const pl = new URLSearchParams();
    if (p.get('from')) pl.set('from', p.get('from'));
    if (p.get('to')) pl.set('to', p.get('to'));
    $('exp-loans').href = '/api/loans/export.csv?' + pl.toString();
    try {
      const r = await fetch('/api/journal?' + p.toString());
      if (r.status === 401) { location.href = '/?admin=1'; return; }
      const d = await r.json();
      if (!r.ok) throw new Error(d.error || 'Erreur');
      const tb = $('rows');
      tb.textContent = '';
      d.rows.forEach((e) => {
        const tr = document.createElement('tr');
        const t = document.createElement('td'); t.className = 'mono nowrap'; t.textContent = e.t;
        const ty = document.createElement('td');
        const tag = document.createElement('span'); tag.className = 'tag tag--' + (TAG[e.type] || 'same'); tag.textContent = e.type_label.toUpperCase();
        ty.appendChild(tag);
        const de = document.createElement('td'); de.textContent = e.details || '';
        const us = document.createElement('td'); us.textContent = e.user || '';
        tr.append(t, ty, de, us);
        tb.appendChild(tr);
      });
      $('empty').hidden = d.rows.length > 0;
      $('counts').textContent = d.total + ' événement' + (d.total > 1 ? 's' : '') + (d.total > d.rows.length ? ' · ' + d.rows.length + ' affichés (l’export contient tout)' : '');
    } catch (err) {
      const t = $('toast'); t.textContent = err.message; t.className = 'toast is-error'; t.hidden = false;
      setTimeout(() => { t.hidden = true; }, 3000);
    }
  }

  $('filters').addEventListener('submit', (e) => { e.preventDefault(); load(); });
  ['from', 'to', 'type'].forEach((id) => $(id).addEventListener('change', load));

  if (['127.0.0.1', 'localhost'].includes(location.hostname)) {
    let idle;
    const arm = () => { clearTimeout(idle); idle = setTimeout(() => { location.href = '/admin/logout'; }, 5 * 60 * 1000); };
    ['pointerdown', 'keydown'].forEach((ev) => document.addEventListener(ev, arm, { passive: true }));
    arm();
  }

  load();
})();
