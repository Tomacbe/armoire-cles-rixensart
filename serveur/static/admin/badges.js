/* Gestion des badges — liste, ajout, scan sur le lecteur, activation, import CSV/Excel */
(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  let users = [];
  let filter = 'all';
  let editing = null;      // personne en cours de modification (null = ajout)
  let scanTimer = null;
  let importFile = null;
  let toastTimer = null;

  async function api(url, opts) {
    const r = await fetch(url, opts);
    if (r.status === 401) { location.href = '/?admin=1'; throw new Error('Session admin expirée'); }
    let data = null;
    try { data = await r.json(); } catch (e) { /* réponse vide */ }
    if (!r.ok) throw new Error((data && data.error) || 'Erreur ' + r.status);
    return data;
  }
  const json = (method, body) => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

  function toast(text, isError) {
    const t = $('toast');
    t.textContent = text;
    t.className = 'toast' + (isError ? ' is-error' : '');
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { t.hidden = true; }, 3000);
  }

  // ------------------------------------------------------------------ liste
  async function load() {
    try {
      users = await api('/api/badges');
      render();
    } catch (e) { toast(e.message, true); }
  }

  function render() {
    const q = $('search').value.trim().toLowerCase();
    const list = users.filter((u) =>
      (filter === 'all' || (filter === 'on') === u.active) &&
      (!q || u.name.toLowerCase().includes(q) || (u.badge_uid || '').toLowerCase().includes(q)));
    const nOn = users.filter((u) => u.active).length;
    $('counts').textContent = users.length + ' personne' + (users.length > 1 ? 's' : '') + ' · ' + nOn + ' active' + (nOn > 1 ? 's' : '') +
      ' · ' + (users.length - nOn) + ' désactivée' + (users.length - nOn > 1 ? 's' : '');
    const tb = $('rows');
    tb.textContent = '';
    list.forEach((u) => {
      const tr = document.createElement('tr');
      if (!u.active) tr.className = 'is-off';
      const tdName = document.createElement('td'); tdName.className = 'name'; tdName.textContent = u.name;
      const tdUid = document.createElement('td'); tdUid.className = 'mono'; tdUid.textContent = u.badge_uid || '—';
      const tdAct = document.createElement('td');
      const sw = document.createElement('label'); sw.className = 'switch';
      const cb = document.createElement('input'); cb.type = 'checkbox'; cb.checked = u.active;
      cb.setAttribute('aria-label', 'Accès de ' + u.name);
      const txt = document.createElement('span'); txt.textContent = u.active ? 'Actif' : 'Désactivé';
      cb.addEventListener('change', () => toggle(u, cb, txt));
      sw.append(cb, txt); tdAct.appendChild(sw);
      const tdCfg = document.createElement('td');
      const sw2 = document.createElement('label'); sw2.className = 'switch';
      const cb2 = document.createElement('input'); cb2.type = 'checkbox'; cb2.checked = !!u.config;
      cb2.setAttribute('aria-label', 'Accès à la configuration pour ' + u.name);
      const txt2 = document.createElement('span'); txt2.textContent = u.config ? 'Autorisé' : 'Non';
      cb2.addEventListener('change', () => toggleConfig(u, cb2, txt2));
      sw2.append(cb2, txt2); tdCfg.appendChild(sw2);
      const tdA = document.createElement('td');
      const box = document.createElement('div'); box.className = 'actions';
      const bE = document.createElement('button'); bE.type = 'button'; bE.className = 'btn btn--light btn--sm'; bE.textContent = 'Modifier';
      bE.addEventListener('click', () => openUser(u));
      const bD = document.createElement('button'); bD.type = 'button'; bD.className = 'btn btn--danger btn--sm'; bD.textContent = 'Supprimer';
      bD.addEventListener('click', () => remove(u));
      box.append(bE, bD); tdA.appendChild(box);
      tr.append(tdName, tdUid, tdAct, tdCfg, tdA);
      tb.appendChild(tr);
    });
    $('empty').hidden = list.length > 0;
    $('empty').textContent = users.length ? 'Aucun résultat.' : 'Aucune personne. Ajoutez-en une ou importez un fichier.';
  }

  async function toggle(u, cb, txt) {
    try {
      const r = await api('/api/badges/' + u.id, json('PATCH', { active: cb.checked }));
      Object.assign(u, r);
      txt.textContent = u.active ? 'Actif' : 'Désactivé';
      cb.closest('tr').classList.toggle('is-off', !u.active);
      toast(u.name + (u.active ? ' : accès activé' : ' : accès désactivé'));
      render();
    } catch (e) { cb.checked = !cb.checked; toast(e.message, true); }
  }

  async function toggleConfig(u, cb, txt) {
    try {
      const r = await api('/api/badges/' + u.id, json('PATCH', { config: cb.checked }));
      Object.assign(u, r);
      txt.textContent = u.config ? 'Autorisé' : 'Non';
      toast(u.name + (u.config ? ' : peut ouvrir la configuration avec son badge' : ' : accès à la configuration retiré'));
    } catch (e) { cb.checked = !cb.checked; toast(e.message, true); }
  }

  async function remove(u) {
    if (!window.confirm('Supprimer ' + u.name + ' (badge ' + u.badge_uid + ') ?')) return;
    try {
      await api('/api/badges/' + u.id, { method: 'DELETE' });
      toast(u.name + ' supprimé');
      load();
    } catch (e) { toast(e.message, true); }
  }

  $('search').addEventListener('input', render);
  $('filter').addEventListener('click', (e) => {
    const b = e.target.closest('button');
    if (!b) return;
    filter = b.dataset.f;
    document.querySelectorAll('#filter button').forEach((x) => x.classList.toggle('on', x === b));
    render();
  });

  // ------------------------------------------------------------------ ajout / modification
  function openUser(u) {
    editing = u || null;
    $('dlg-user-title').textContent = u ? 'Modifier ' + u.name : 'Ajouter une personne';
    $('f-name').value = u ? u.name : '';
    $('f-uid').value = u ? u.badge_uid : '';
    $('f-active').checked = u ? u.active : true;
    $('f-config').checked = u ? !!u.config : false;
    $('user-error').hidden = true;
    stopScan();
    $('dlg-user').showModal();
    $('f-name').focus();
  }

  $('btn-add').addEventListener('click', () => openUser(null));
  $('form-user').addEventListener('submit', async (e) => {
    e.preventDefault();
    const body = { name: $('f-name').value.trim(), badge_uid: $('f-uid').value.trim(), active: $('f-active').checked, config: $('f-config').checked };
    const err = !body.name ? 'Indiquez le nom de la personne.' : !body.badge_uid ? 'Scannez le badge ou saisissez son UID.' : null;
    if (err) { showError('user-error', err); return; }
    try {
      if (editing) await api('/api/badges/' + editing.id, json('PUT', body));
      else await api('/api/badges', json('POST', body));
      stopScan();
      $('dlg-user').close();
      toast(body.name + (editing ? ' modifié' : ' ajouté'));
      load();
    } catch (ex) { showError('user-error', ex.message); }
  });

  function showError(id, text) { const el = $(id); el.textContent = text; el.hidden = false; }

  // ------------------------------------------------------------------ scanner un badge sur le lecteur de l'armoire
  async function startScan() {
    stopScan();
    $('scan').hidden = false;
    $('scan').classList.remove('is-ok');
    $('scan-text').textContent = 'Passez le badge sur le lecteur de l’armoire…';
    let after;
    try { after = (await api('/api/badges/last-scan')).after; } catch (e) { showError('user-error', e.message); $('scan').hidden = true; return; }
    const until = Date.now() + 60000;
    const poll = async () => {
      if (Date.now() > until) { $('scan-text').textContent = 'Aucun badge lu depuis 1 minute.'; scanTimer = null; return; }
      try {
        const r = await api('/api/badges/last-scan?after=' + after);
        if (r.uid) {
          $('f-uid').value = r.uid;
          $('scan').classList.add('is-ok');
          const other = r.owner && (!editing || r.owner.id !== editing.id);
          $('scan-text').textContent = 'Badge lu : ' + r.uid + (other ? ' — déjà attribué à ' + r.owner.name : '');
          scanTimer = null;
          return;
        }
      } catch (e) { /* on réessaie */ }
      scanTimer = setTimeout(poll, 700);
    };
    poll();
  }
  function stopScan() { clearTimeout(scanTimer); scanTimer = null; $('scan').hidden = true; }

  $('btn-scan').addEventListener('click', startScan);
  $('scan-cancel').addEventListener('click', stopScan);

  // ------------------------------------------------------------------ import CSV / Excel
  $('btn-import').addEventListener('click', () => {
    importFile = null;
    $('f-file').value = '';
    $('drop-text').textContent = 'Choisir un fichier ou le glisser ici';
    $('preview').hidden = true;
    $('import-error').hidden = true;
    $('btn-commit').disabled = true;
    $('btn-commit').textContent = 'Importer';
    $('dlg-import').showModal();
  });

  $('f-file').addEventListener('change', () => { if ($('f-file').files[0]) preview($('f-file').files[0]); });
  const drop = $('drop');
  drop.addEventListener('dragover', (e) => { e.preventDefault(); drop.classList.add('is-over'); });
  drop.addEventListener('dragleave', () => drop.classList.remove('is-over'));
  drop.addEventListener('drop', (e) => {
    e.preventDefault(); drop.classList.remove('is-over');
    if (e.dataTransfer.files[0]) preview(e.dataTransfer.files[0]);
  });

  async function sendImport(commit) {
    const fd = new FormData();
    fd.append('file', importFile);
    fd.append('commit', commit ? '1' : '0');
    return api('/api/badges/import', { method: 'POST', body: fd });
  }

  const LABELS = { new: 'NOUVEAU', update: 'MISE À JOUR', same: 'INCHANGÉ', error: 'ERREUR' };

  async function preview(file) {
    importFile = file;
    $('drop-text').textContent = file.name;
    $('import-error').hidden = true;
    $('preview').hidden = true;
    $('btn-commit').disabled = true;
    try {
      const r = await sendImport(false);
      const s = r.summary;
      $('sum').innerHTML = '';
      [['new', s.new + ' à ajouter'], ['update', s.update + ' à mettre à jour'], ['same', s.same + ' inchangé(s)'], ['error', s.error + ' en erreur']]
        .forEach(([k, t]) => { const span = document.createElement('span'); span.className = 'tag tag--' + k; span.textContent = t; $('sum').appendChild(span); });
      const tb = $('prev-rows');
      tb.textContent = '';
      r.rows.forEach((row) => {
        const tr = document.createElement('tr');
        [row.line, row.name || '—', row.badge_uid || '—', row.active ? 'Actif' : 'Désactivé'].forEach((v, i) => {
          const td = document.createElement('td'); td.textContent = v; if (i === 2) td.className = 'mono'; tr.appendChild(td);
        });
        const td = document.createElement('td');
        const tag = document.createElement('span'); tag.className = 'tag tag--' + row.action; tag.textContent = LABELS[row.action];
        td.append(tag, document.createTextNode(row.action === 'new' || row.action === 'same' ? '' : ' ' + row.message));
        tr.appendChild(td);
        tb.appendChild(tr);
      });
      $('preview').hidden = false;
      const n = s.new + s.update;
      $('btn-commit').disabled = n === 0;
      $('btn-commit').textContent = n ? 'Importer ' + n + ' ligne' + (n > 1 ? 's' : '') : 'Rien à importer';
    } catch (e) { showError('import-error', e.message); }
  }

  $('btn-commit').addEventListener('click', async () => {
    $('btn-commit').disabled = true;
    try {
      const r = await sendImport(true);
      $('dlg-import').close();
      toast('Import terminé : ' + r.summary.new + ' ajout(s), ' + r.summary.update + ' mise(s) à jour');
      load();
    } catch (e) { showError('import-error', e.message); $('btn-commit').disabled = false; }
  });

  // fermeture des fenêtres
  document.querySelectorAll('[data-close]').forEach((b) => b.addEventListener('click', () => { stopScan(); b.closest('dialog').close(); }));
  $('dlg-user').addEventListener('close', stopScan);

  // Sur l'écran de l'armoire lui-même : retour automatique à l'accueil après 5 min sans action
  if (['127.0.0.1', 'localhost'].includes(location.hostname)) {
    let idle;
    const arm = () => { clearTimeout(idle); idle = setTimeout(() => { location.href = '/admin/logout'; }, 5 * 60 * 1000); };
    ['pointerdown', 'keydown'].forEach((ev) => document.addEventListener(ev, arm, { passive: true }));
    arm();
  }

  load();
})();
