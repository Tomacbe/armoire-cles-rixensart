/* Réglages : temporisation du relais et durée de session */
(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const FIELDS = ['unlock_s', 'session_s', 'door_alert_s', 'door_grace_s', 'screen_sleep_min', 'retro_s'];
  const TEXTS = ['cabinet_name', 'screen_rotation'];
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
    t.textContent = text; t.className = 'toast' + (isError ? ' is-error' : ''); t.hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(() => { t.hidden = true; }, 3000);
  }
  function fill(d) {
    FIELDS.forEach((k) => {
      const i = $(k);
      i.value = d.values[k];
      i.min = d.spec[k].min; i.max = d.spec[k].max;
    });
    TEXTS.forEach((k) => { if (document.activeElement !== $(k)) $(k).value = d.values[k]; });
  }

  $('form').addEventListener('submit', async (e) => {
    e.preventDefault();
    $('error').hidden = true;
    const body = {};
    for (const k of FIELDS) {
      const i = $(k);
      if (!i.checkValidity()) { $('error').textContent = 'Valeur hors limites (' + i.min + ' à ' + i.max + ').'; $('error').hidden = false; i.focus(); return; }
      body[k] = Number(i.value);
    }
    for (const k of TEXTS) {
      const v = $(k).value.trim();
      if (!v) { $('error').textContent = 'Le nom de l\u2019armoire ne peut pas être vide.'; $('error').hidden = false; $(k).focus(); return; }
      body[k] = v;
    }
    try {
      fill(await api('/api/settings', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }));
      toast('Réglages enregistrés');
    } catch (err) { $('error').textContent = err.message; $('error').hidden = false; }
  });

  $('btn-test').addEventListener('click', async () => {
    try {
      const r = await api('/api/settings/test-unlock', { method: 'POST' });
      toast('Porte déverrouillée pendant ' + r.unlock_s + ' s');
    } catch (err) { toast(err.message, true); }
  });

  if (['127.0.0.1', 'localhost'].includes(location.hostname)) {
    let idle;
    const arm = () => { clearTimeout(idle); idle = setTimeout(() => { location.href = '/admin/logout'; }, 5 * 60 * 1000); };
    ['pointerdown', 'keydown'].forEach((ev) => document.addEventListener(ev, arm, { passive: true }));
    arm();
  }

  api('/api/settings').then(fill).catch((e) => toast(e.message, true));

  // ---------------------------------------------------------------- état du système
  function setDd(id, text, ok) {
    const el = $(id);
    el.textContent = text;
    el.className = ok === true ? 'is-ok' : ok === false ? 'is-ko' : '';
  }
  async function system() {
    try {
      const d = await api('/api/system');
      setDd('sys-server', 'En ligne', true);
      setDd('sys-arduino', d.serial.connected ? 'Connecté (' + (d.serial.port || '').split('/').pop() + ')' : 'Déconnecté', !!d.serial.connected);
      setDd('sys-door', !d.door ? 'Capteur jamais entendu' : d.door.status === 'OPEN' ? 'Ouverte' : 'Fermée', d.door ? true : null);
      const sync = d.ntp === true ? ' · synchronisée' : d.ntp === false ? ' · NON synchronisée' : '';
      const bad = d.clock_behind || d.year < 2026;
      setDd('sys-clock', d.time + sync, bad ? false : d.ntp === false ? null : true);
      $('sys-warn').hidden = !bad;
      $('sys-warn').textContent = bad ? 'L\u2019horloge du mini-PC semble fausse (pile du BIOS ?) : vérifiez la date avec « timedatectl » et la connexion internet.' : '';
    } catch (e) {
      setDd('sys-server', 'Injoignable', false);
    }
  }
  system();
  setInterval(system, 5000);

  // ---------------------------------------------------------------- test du son (haut-parleur de l'écran)
  $('btn-sound').addEventListener('click', async () => {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) { toast('Son non disponible dans ce navigateur', true); return; }
    const c = new AC();
    await c.resume();
    [[880, 0], [660, 0.25], [990, 0.5]].forEach(([f, t]) => {
      const o = c.createOscillator(), g = c.createGain();
      o.frequency.value = f; o.type = 'sine';
      g.gain.setValueAtTime(0.3, c.currentTime + t);
      g.gain.exponentialRampToValueAtTime(0.0001, c.currentTime + t + 0.22);
      o.connect(g).connect(c.destination);
      o.start(c.currentTime + t); o.stop(c.currentTime + t + 0.25);
    });
    toast('Trois bips joués : si rien n\u2019est audible, voir « Pas de son » dans le dépannage');
    setTimeout(() => c.close(), 1500);
  });
})();
