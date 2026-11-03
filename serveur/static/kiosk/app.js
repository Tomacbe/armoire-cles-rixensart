/* Armoire à clés — écran kiosque branché sur le backend Flask (keybox.service).
   Interroge l'API toutes les 500 ms :
     GET /api/status  → [{key_number, label, status: "PRESENT"|..., last_updated, borrower?, building?}]
     GET /api/logs    → journal (format libre, lu de façon tolérante), toutes les 3 s
     GET /api/state   → FACULTATIF, à ajouter plus tard dans Flask :
                        {"door": {"status": "OPEN"|"CLOSED", "since": "<ISO>"},
                         "session": {"name", "uid", "expires": "<ISO>"} | null,
                         "serial": {"connected": true, "port": "/dev/ttyUSB0"}}
     POST /api/session/end → FACULTATIF, bouton « Terminer la session »
   Tant que /api/state n'existe pas : grille des clés toujours affichée, porte « État inconnu ». */
(function () {
  'use strict';

  const CFG = {
    pollMs: 500,
    logsEveryMs: 3000,
    stateEveryMs: 500,
    door_alert_s: 120,   // porte ouverte trop longtemps pendant une session
    door_grace_s: 15,    // porte ouverte sans session
    beep_every_s: 2,
    sound: true,
    site: 'Commune de Rixensart',
    cabinet: 'Armoire 01',      // remplacé par le nom réglé dans Configuration › Réglages
    sleep_min: 5,               // veille de l'écran (réglage screen_sleep_min ; 0 = jamais)
    logsMax: 200,               // événements chargés dans le journal (défilement au doigt)
  };

  const $ = (id) => document.getElementById(id);
  const body = document.body;

  let keys = null;           // dernière réponse /api/status
  let doorState = null;      // dernière réponse /api/state (null = pas encore disponible)
  let hasStateApi = null;    // null = inconnu, false = route absente (404)
  let logs = [];
  let apiOk = false;
  let apiDownSince = Date.now();
  let silencedUntil = 0;
  let lastLogKey = '';
  let lastActivity = Date.now();   // dernier toucher / badge / mouvement : sert à la mise en veille
  let asleep = false;
  let swallowUntil = 0;            // le toucher qui rallume l'écran ne doit rien déclencher d'autre
  let lastWakeCall = 0;
  let usedToken = null;
  let flashTimer = null;
  let prevSession = null;
  let prevDoor = null;
  let lastFlashId = null;
  const prevPresent = {};

  const now = () => Date.now() / 1000;
  const pad = (n) => String(n).padStart(2, '0');
  const mmss = (s) => { s = Math.max(0, Math.floor(s)); return Math.floor(s / 60) + ':' + pad(s % 60); };
  // Les dates Flask (datetime.now()/utcnow() sans fuseau) sont lues comme de l'UTC : le serveur est en UTC.
  const toEpoch = (v) => {
    if (v == null || v === '') return null;
    if (typeof v === 'number') return v > 1e12 ? v / 1000 : v;
    let s = String(v).trim().replace(' ', 'T');
    if (!/[zZ]|[+-]\d\d:?\d\d$/.test(s)) s += 'Z';
    const t = Date.parse(s);
    return isNaN(t) ? null : t / 1000;
  };
  const hhmm = (t) => { const d = new Date(t * 1000); return pad(d.getHours()) + ':' + pad(d.getMinutes()); };
  const since = (t) => {
    const d = new Date(t * 1000), today = new Date();
    return d.toDateString() === today.toDateString() ? hhmm(t) : pad(d.getDate()) + '/' + pad(d.getMonth() + 1) + ' ' + hhmm(t);
  };
  const initials = (name) => name.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join('');
  const DAYS = ['dim.', 'lun.', 'mar.', 'mer.', 'jeu.', 'ven.', 'sam.'];
  const MONTHS = ['janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin', 'juil.', 'août', 'sept.', 'oct.', 'nov.', 'déc.'];
  const TAGS = { badge: 'BADGE', out: 'SORTIE', ret: 'RETOUR', deny: 'ALERTE', sys: 'SYSTÈME' };

  async function getJSON(url) {
    const r = await fetch(url, { cache: 'no-store' });
    if (r.status === 404) { const e = new Error('404'); e.notFound = true; throw e; }
    if (!r.ok) throw new Error(r.status);
    return r.json();
  }

  // ------------------------------------------------------------------ interrogation de l'API
  async function pollStatus() {
    try {
      const data = await getJSON('/api/status');
      const list = Array.isArray(data) ? data : (data.keys || []);
      if (!apiOk) apiOk = true;
      onKeys(list);
    } catch (e) {
      if (apiOk) apiDownSince = Date.now();
      apiOk = false;
    }
    setTimeout(pollStatus, CFG.pollMs);
  }

  async function pollState() {
    if (hasStateApi === false) return; // route absente : on ne réessaie plus
    try {
      const s = await getJSON('/api/state');
      hasStateApi = true;
      onState(s);
    } catch (e) {
      if (e.notFound) { hasStateApi = false; doorState = null; return; }
    }
    setTimeout(pollState, CFG.stateEveryMs);
  }

  async function pollLogs() {
    try {
      const data = await getJSON('/api/logs?limit=' + CFG.logsMax);
      const list = Array.isArray(data) ? data : (data.logs || data.items || []);
      // ordre d'enregistrement (id) : correct même si l'horloge du mini-PC a été déréglée
      logs = list.map(normLog).filter(Boolean).sort((a, b) => (b.id - a.id) || (b.t - a.t));
      renderLog();
    } catch (e) { /* journal facultatif */ }
    setTimeout(pollLogs, CFG.logsEveryMs);
  }

  // Lecture d'une ligne de /api/logs : {timestamp, type, details, user}
  // types connus : badge_scan, badge_unknown, key_change, admin_login, admin_denied, user_admin
  function normLog(e) {
    if (!e || typeof e !== 'object') return null;
    const t = toEpoch(e.timestamp ?? e.time ?? e.created_at ?? e.date ?? e.datetime);
    const keyNo = e.key_number ?? e.key ?? e.slot;
    const user = e.user_name ?? e.user ?? e.name ?? e.borrower ?? '';
    const raw = String(e.type ?? e.event_type ?? e.event ?? e.action ?? e.status ?? '').toUpperCase();
    const details = String(e.details ?? e.message ?? e.text ?? e.description ?? '');
    let text = details;
    let tag = 'sys';
    if (raw === 'KEY_CHANGE') {
      // nouveau format : « Clé #05 Chaufferie (Bâtiment B) retirée par Jean Dupont » → affiché tel quel
      // ancien format  : « Clé sur pin 24 (Slot 5) est maintenant ABSENT » → « Clé #05 retirée »
      const absent = /ABSENT|retir/i.test(details);
      tag = absent ? 'out' : 'ret';
      const slot = (details.match(/Slot\s+(\d+)/i) || [])[1];
      if (slot) text = 'Clé #' + pad(slot) + (absent ? ' retirée' : ' restituée') + (user ? ' — ' + user : '');
    } else if (/BADGE|RFID/.test(raw)) tag = /DENY|REFUS|UNKNOWN|INCONNU/.test(raw) ? 'deny' : 'badge';
    else if (/DENIED|DENY|ERROR|ALERT/.test(raw)) tag = 'deny';
    else if (/^(ABSENT|OUT|REMOVED|TAKEN)$/.test(raw)) tag = 'out';
    else if (/^(PRESENT|RETURNED|IN)$/.test(raw)) tag = 'ret';
    if (/sans badge/i.test(details)) tag = 'deny';   // porte ou clé sans badge : alerte
    if (!text) {
      if (keyNo != null && tag === 'out') text = 'Clé #' + pad(keyNo) + ' retirée' + (user ? ' — ' + user : '');
      else if (keyNo != null && tag === 'ret') text = 'Clé #' + pad(keyNo) + ' restituée' + (user ? ' — ' + user : '');
      else text = [raw.toLowerCase(), keyNo != null ? 'clé #' + pad(keyNo) : '', user].filter(Boolean).join(' · ');
    }
    // l'écran public n'affiche jamais d'UID de badge, seulement le nom
    text = String(text).replace(/\s*\(UID\s*:?\s*[0-9A-F:]+\)/gi, '').replace(/(désactivé)\s*:\s*[0-9A-F:]+/i, '$1');
    return { id: Number(e.id) || 0, t: t || 0, tag, text };
  }

  // ------------------------------------------------------------------ données reçues
  function onKeys(list) {
    const first = !keys;
    keys = list.map((k) => {
      const st = String(k.status || '').toUpperCase();
      return {
        slot: Number(k.key_number),
        present: st === 'PRESENT' || st === 'IN' || k.present === true,
        label: k.label || '',
        building: k.building || '',
        borrower: k.borrower || k.user_name || null,
        since: toEpoch(k.last_updated),
      };
    }).filter((k) => k.slot > 0).sort((a, b) => a.slot - b.slot);
    if (first || $('grid').children.length !== keys.length) {
      $('slots-max').textContent = pad(keys.length);
      buildGrid(keys);
    }
    renderKeys(first);
  }

  function onState(s) {
    doorState = s || {};
    const session = activeSession();
    if (session && (!prevSession || prevSession.started !== session.started)) {
      activity();
      KioskAudio.play('ok');
      showFlash('Bonjour ' + session.name, 'ok', 1800);
    }
    if (!session && prevSession) { $('grid').dataset.filter = 'all'; setFilterChip('all'); }
    const door = doorState.door ? String(doorState.door.status).toUpperCase() : null;
    if (door === 'OPEN' && prevDoor && prevDoor !== 'OPEN') KioskAudio.play('open');
    if (door && prevDoor && door !== prevDoor) activity();
    const f = doorState.flash;
    if (f && f.text && f.id !== lastFlashId) {
      if (lastFlashId !== null) { activity(); showFlash(f.text, f.kind || 'deny'); }  // pas de rappel d'un ancien message au chargement
      lastFlashId = f.id;
    } else if (!f && lastFlashId === null) lastFlashId = 0;
    prevSession = session;
    // accès à la configuration accordé par badge (jeton remis uniquement à la borne)
    const g = doorState.admin_grant;
    if (g && g.token && g.token !== usedToken) { usedToken = g.token; badgeLogin(g.token); }
    if (doorState.settings) {
      if (doorState.settings.door_alert_s) CFG.door_alert_s = doorState.settings.door_alert_s;
      if (doorState.settings.door_grace_s) CFG.door_grace_s = doorState.settings.door_grace_s;
      if (doorState.settings.screen_sleep_min != null) CFG.sleep_min = Number(doorState.settings.screen_sleep_min);
      const name = doorState.settings.cabinet_name;
      if (name && $('cabinet-name').textContent !== name) $('cabinet-name').textContent = name;
    }
    prevDoor = door;
    renderUser();
    if (keys) renderKeys(false);
  }

  function activeSession() {
    const s = doorState && doorState.session;
    if (!s || !s.name) return null;
    const exp = toEpoch(s.expires);
    if (exp && exp < now()) return null;
    return { name: s.name, expires: exp, started: s.started || '' };
  }

  // ------------------------------------------------------------------ grille des clés
  function buildGrid(list) {
    const grid = $('grid');
    grid.textContent = '';
    const tpl = $('tpl-key');
    list.forEach((k) => {
      const el = tpl.content.firstElementChild.cloneNode(true);
      el.dataset.slot = k.slot;
      el.querySelector('.key__num').textContent = '#' + pad(k.slot);
      grid.appendChild(el);
    });
    layoutGrid();
  }
  // 6 colonnes à l'horizontale, 5 à la verticale ; le nombre de lignes suit le nombre de clés
  const portrait = window.matchMedia('(orientation: portrait)');
  function layoutGrid() {
    const grid = $('grid');
    const cols = portrait.matches ? 5 : 6;
    grid.style.gridTemplateColumns = 'repeat(' + cols + ', minmax(0, 1fr))';
    grid.style.gridTemplateRows = 'repeat(' + Math.ceil(grid.children.length / cols) + ', minmax(0, 1fr))';
  }
  portrait.addEventListener('change', layoutGrid);

  function renderKeys(first) {
    const grid = $('grid');
    const session = activeSession();
    const me = session ? session.name : null;
    let nIn = 0, nOut = 0;
    const loans = (doorState && doorState.loans) || {};
    const sessionStart = session ? toEpoch(session.started) : null;
    keys.forEach((k) => {
      const el = grid.querySelector('[data-slot="' + k.slot + '"]');
      if (!el) return;
      // clé sans nom = emplacement non paramétré : carte grise, pas de couleur, pas de LED
      const unset = !k.label || k.label === 'Clé n°' + k.slot;
      el.classList.toggle('is-unset', unset);
      if (unset) {
        ['is-out', 'is-mine', 'is-return', 'is-unknown'].forEach((c) => el.classList.remove(c));
        el.querySelector('.key__status').textContent = 'NON PARAMÉTRÉE';
        el.querySelector('.key__building').textContent = '';
        el.querySelector('.key__zone').textContent = 'Emplacement libre';
        el.querySelector('.key__foot').textContent = '';
        el.setAttribute('aria-label', 'Emplacement ' + k.slot + ' non paramétré');
        prevPresent[k.slot] = k.present;
        el.dataset.unset = '1';
        return;
      }
      delete el.dataset.unset;
      if (k.present) nIn++; else nOut++;
      // emprunteur : /api/state (table key_loan) en priorité
      const loan = !k.present ? loans[k.slot] || loans[String(k.slot)] : null;
      const borrower = loan ? loan.name : k.borrower;
      const out = loan ? toEpoch(loan.since) : k.since;
      const unknown = !k.present && borrower === 'Non identifié';
      const mine = !k.present && me && borrower === me;
      // clé prise lors d'un passage précédent par la personne qui vient de badger : à remettre (LED jaune)
      const toReturn = mine && sessionStart && out && out < sessionStart;
      el.classList.toggle('is-out', !k.present);
      el.classList.toggle('is-mine', !!mine);
      el.classList.toggle('is-return', !!toReturn);
      el.classList.toggle('is-unknown', unknown);
      el.querySelector('.key__status').textContent = k.present ? 'PRÉSENTE' : unknown ? 'SANS BADGE'
        : toReturn ? 'À REMETTRE' : mine ? 'CHEZ VOUS' : 'EMPRUNTÉE';
      el.querySelector('.key__building').textContent = (doorState && doorState.buildings && doorState.buildings[k.slot]) || k.building || '';
      el.querySelector('.key__zone').textContent = k.label || 'Emplacement ' + pad(k.slot);
      el.querySelector('.key__foot').textContent = k.present ? 'Disponible'
        : (borrower ? borrower + ' · ' : '') + (out ? 'sortie ' + since(out) : 'Absente');
      el.setAttribute('aria-label', 'Clé ' + k.slot + ', ' + (k.present ? 'présente' : 'absente'));
      if (!first && prevPresent[k.slot] !== undefined && prevPresent[k.slot] !== k.present) activity();
      prevPresent[k.slot] = k.present;
    });
    const n = nIn + nOut;   // clés paramétrées uniquement
    $('count-in').textContent = nIn; $('count-out').textContent = nOut;
    $('f-all').textContent = n; $('f-in').textContent = nIn; $('f-out').textContent = nOut;
    // dernier mouvement : clé paramétrée la plus récemment mise à jour
    const last = keys.filter((k) => k.since && k.label && k.label !== 'Clé n°' + k.slot).sort((a, b) => b.since - a.since)[0];
    $('last-move').textContent = last && !first ? hhmm(last.since) + ' · Clé #' + pad(last.slot) + (last.present ? ' restituée' : ' retirée') : '—';
  }

  function setFilterChip(f) {
    document.querySelectorAll('#filters .chip').forEach((c) => c.classList.toggle('is-on', c.dataset.filter === f));
  }
  $('filters').addEventListener('click', (e) => {
    const chip = e.target.closest('.chip');
    if (!chip) return;
    $('grid').dataset.filter = chip.dataset.filter;
    setFilterChip(chip.dataset.filter);
  });

  // ------------------------------------------------------------------ journal
  function renderLog() {
    const key = logs.map((e) => e.id + ':' + e.t + e.text).join('|');
    if (key === lastLogKey) return;
    lastLogKey = key;
    const ol = $('log');
    // garde la position de lecture si on a fait défiler la liste pendant qu'un événement arrive
    const keepTop = ol.scrollTop > 4;
    const before = ol.scrollHeight - ol.scrollTop;
    ol.textContent = '';
    logs.forEach((e) => {
      const li = document.createElement('li');
      li.className = 'log__item';
      const time = document.createElement('span'); time.className = 'log__time'; time.textContent = e.t ? since(e.t) : '';
      const b = document.createElement('div'); b.className = 'log__body';
      const tag = document.createElement('span'); tag.className = 'tag tag--' + e.tag; tag.textContent = TAGS[e.tag];
      const txt = document.createElement('span'); txt.className = 'log__text'; txt.textContent = e.text;
      b.append(tag, txt); li.append(time, b); ol.appendChild(li);
    });
    if (keepTop) ol.scrollTop = ol.scrollHeight - before;
    $('btn-log-top').hidden = ol.scrollTop < 40;
  }
  $('log').addEventListener('scroll', () => { $('btn-log-top').hidden = $('log').scrollTop < 40; }, { passive: true });
  $('btn-log-top').addEventListener('click', () => { $('log').scrollTop = 0; });

  // ------------------------------------------------------------------ historique d'une clé (toucher une carte)
  const hist = $('dlg-hist');
  let histTimer = null;
  const dayTime = (t) => { const d = new Date(t * 1000); return DAYS[d.getDay()] + ' ' + pad(d.getDate()) + '/' + pad(d.getMonth() + 1) + '/' + d.getFullYear() + ' ' + hhmm(t); };
  const duration = (s) => { const m = Math.max(0, Math.round(s / 60)); return m < 60 ? m + ' min' : Math.floor(m / 60) + ' h ' + pad(m % 60); };

  async function openHistory(slot) {
    let d;
    try { d = await getJSON('/api/keys/' + slot + '/history'); } catch (e) { showFlash('Historique indisponible', 'deny'); return; }
    $('hist-num').textContent = '#' + pad(slot);
    $('hist-title').textContent = d.label || 'Clé ' + pad(slot);
    $('hist-sub').textContent = [d.building, d.status === 'PRESENT' ? 'Présente dans l’armoire' : 'Sortie actuellement'].filter(Boolean).join(' · ');
    const ol = $('hist-list');
    ol.textContent = '';
    d.loans.forEach((l) => {
      const li = document.createElement('li');
      li.className = 'hist__item' + (l.returned ? '' : ' is-out');
      const who = document.createElement('b'); who.textContent = l.user;
      const out = document.createElement('span'); out.textContent = 'Sortie ' + (l.taken ? dayTime(l.taken) : '');
      const back = document.createElement('span');
      back.className = 'hist__back';
      back.textContent = l.returned
        ? 'Remise ' + dayTime(l.returned) + (l.returned_by && l.returned_by !== l.user ? ' par ' + l.returned_by : '') + ' · ' + duration(l.returned - l.taken)
        : 'Pas encore remise';
      li.append(who, out, back);
      ol.appendChild(li);
    });
    $('hist-empty').hidden = d.loans.length > 0;
    ol.scrollTop = 0;
    if (!hist.open) hist.showModal();
    clearTimeout(histTimer);
    histTimer = setTimeout(() => hist.open && hist.close(), 60000);
  }
  $('grid').addEventListener('click', (e) => {
    const card = e.target.closest('.key');
    if (!card || card.dataset.unset) return;
    openHistory(Number(card.dataset.slot));
  });
  $('btn-hist-close').addEventListener('click', () => hist.close());
  hist.addEventListener('click', (e) => { if (e.target === hist) hist.close(); });   // toucher hors de la fenêtre
  hist.addEventListener('scroll', () => {}, { passive: true });

  function renderUser() {
    const s = activeSession();
    $('user-pill').hidden = !s;
    $('btn-end').hidden = !s;
    if (s) {
      $('user-name').textContent = s.name;
      $('user-initials').textContent = initials(s.name);
    }
  }

  // ------------------------------------------------------------------ boucle d'affichage (4×/s)
  function tick() {
    const t = now();
    const d = new Date();
    $('clock-time').textContent = pad(d.getHours()) + ':' + pad(d.getMinutes());
    $('clock-date').textContent = DAYS[d.getDay()] + ' ' + d.getDate() + ' ' + MONTHS[d.getMonth()];

    $('offline').hidden = !(!apiOk && Date.now() - apiDownSince > 3000);
    // l'état Arduino / serveur n'est plus affiché ici : voir Configuration › Réglages
    const serial = doorState && doorState.serial;
    const ard = apiOk && serial ? !!serial.connected : null;

    if (!keys) return;
    const session = activeSession();
    const doorInfo = doorState && doorState.door;
    const doorOpen = doorInfo && String(doorInfo.status).toUpperCase() === 'OPEN';
    const openFor = doorOpen ? t - (toEpoch(doorInfo.since) || t) : 0;
    const alert = doorOpen && (session ? openFor > CFG.door_alert_s : openFor > CFG.door_grace_s);
    const door = !apiOk || !doorInfo || ard === false ? 'unknown' : !doorOpen ? 'closed' : alert ? 'alert' : 'open';
    if (body.dataset.door !== door) body.dataset.door = door;

    const label = { closed: 'Porte fermée', open: 'Porte ouverte', alert: 'Porte ouverte', unknown: 'État inconnu' }[door];
    const sub = door === 'closed' ? (session ? 'Déverrouillée — vous pouvez ouvrir' : 'Armoire sécurisée')
      : door === 'unknown' ? (!apiOk || ard === false ? 'Pas de liaison avec l’armoire' : 'Capteur de porte non raccordé')
      : door === 'alert' ? 'Depuis ' + mmss(openFor) + ' — refermez !' : 'Depuis ' + mmss(openFor);
    $('door-label').textContent = label;
    $('door-sub').textContent = sub;

    let banner = 'none', text = '', timer = '';
    if (door === 'alert') {
      banner = 'alert';
      text = '<b>Porte ouverte depuis ' + mmss(openFor) + '</b> — veuillez refermer l’armoire à clés.';
      timer = t < silencedUntil ? 'Son coupé ' + mmss(silencedUntil - t) : '';
    } else if (door === 'open') {
      banner = 'open';
      if (session) {
        text = '<b>Porte ouverte</b> — prenez ou déposez vos clés, puis refermez la porte et terminez votre session.';
        timer = session.expires ? 'Fin de session dans ' + mmss(session.expires - t) : '';
      } else {
        text = '<b>Porte ouverte sans session</b> — veuillez refermer l’armoire.';
        timer = 'Alarme dans ' + mmss(CFG.door_grace_s - openFor);
      }
    } else if (door === 'unknown' && session && apiOk) {
      banner = 'info';
      text = '<b>Bonjour ' + session.name.replace(/[<>&]/g, '') + '</b> — prenez ou déposez vos clés. Les clés à remettre sont en jaune.';
      timer = session.expires ? 'Fin de session dans ' + mmss(session.expires - t) : '';
    } else if (door === 'closed' && session) {
      banner = 'info';
      text = '<b>Badge accepté</b> — l’armoire est déverrouillée, ouvrez la porte.';
      timer = session.expires ? 'Fin de session dans ' + mmss(session.expires - t) : '';
    }
    // Sans session : invitation à badger, la grille des clés restant visible pour tous
    if (banner === 'none' && apiOk && !session) {
      banner = 'badge';
      text = '<b>Présentez votre badge</b> sous l’écran pour ouvrir l’armoire à clés.';
      timer = '';
    }
    if (body.dataset.banner !== banner) body.dataset.banner = banner;
    $('banner').hidden = banner === 'none';
    if ($('banner-text').innerHTML !== text) $('banner-text').innerHTML = text;
    $('banner-timer').textContent = timer;
    $('btn-silence').hidden = !(door === 'alert' && KioskAudio.enabled && t >= silencedUntil);
    $('sound-hint').hidden = !(door === 'alert' && KioskAudio.enabled && !KioskAudio.ready);

    // Sans gestion des badges dans Flask (/api/state absent) : la grille reste affichée en permanence.
    // La grille des clés est toujours affichée : le contenu de l'armoire est visible par tous
    const screen = 'session';
    if (body.dataset.screen !== screen) body.dataset.screen = screen;

    // ---- veille : jamais pendant une session, porte ouverte ou alerte
    const keepAwake = !!session || door === 'open' || door === 'alert';
    if (keepAwake) {
      lastActivity = Date.now();
      if (asleep) wakeUp();
      // demande au serveur de garder l'écran allumé (X l'éteindrait sinon après le délai)
      if (Date.now() - lastWakeCall > 60000 || (door === 'alert' && Date.now() - lastWakeCall > 5000 && !wasAlert)) {
        lastWakeCall = Date.now();
        fetch('/api/screen/wake', { method: 'POST' }).catch(() => {});
      }
    }
    wasAlert = door === 'alert';
    const shouldSleep = CFG.sleep_min > 0 && Date.now() - lastActivity > CFG.sleep_min * 60000;
    if (shouldSleep && !asleep) goToSleep();
  }
  let wasAlert = false;

  // ------------------------------------------------------------------ mise en veille de l'écran
  function goToSleep() {
    asleep = true;
    $('sleep').hidden = false;
    // retour à l'état de base pour le prochain utilisateur
    if (hist.open) hist.close();
    if (dlg.open) closeLogin();
    $('grid').dataset.filter = 'all'; setFilterChip('all');
    $('log').scrollTop = 0;
  }
  function wakeUp() {
    asleep = false;
    $('sleep').hidden = true;
  }
  function activity() {
    lastActivity = Date.now();
    if (asleep) wakeUp();
  }
  // toucher, souris ou clavier : l'écran se rallume ; le toucher de réveil ne déclenche rien d'autre
  $('sleep').addEventListener('pointerdown', (e) => {
    e.preventDefault();
    swallowUntil = Date.now() + 700;
    activity();
  });
  document.addEventListener('click', (e) => {
    if (Date.now() < swallowUntil) { e.stopPropagation(); e.preventDefault(); }
  }, true);
  ['pointerdown', 'keydown', 'wheel'].forEach((ev) => document.addEventListener(ev, () => { if (!asleep) lastActivity = Date.now(); }, { passive: true, capture: true }));
  let lastMove = 0;
  document.addEventListener('pointermove', () => {
    // la souris réveille aussi (X rallume l'écran au moindre mouvement)
    if (asleep) swallowUntil = Date.now() + 700;   // le clic qui suit le réveil ne déclenche rien
    if (asleep || Date.now() - lastMove > 1000) { lastMove = Date.now(); activity(); }
  }, { passive: true });
  $('log').addEventListener('scroll', () => { lastActivity = Date.now(); }, { passive: true });

  // ------------------------------------------------------------------ bip d'alerte (sans animation visuelle)
  setInterval(() => {
    if (body.dataset.door === 'alert' && now() >= silencedUntil) KioskAudio.play('alert');
  }, CFG.beep_every_s * 1000);

  $('btn-silence').addEventListener('click', () => { silencedUntil = now() + 120; tick(); });
  $('btn-end').addEventListener('click', () => { fetch('/api/session/end', { method: 'POST' }).catch(() => {}); });
  document.addEventListener('pointerdown', () => KioskAudio.unlock(), { passive: true });

  function showFlash(text, kind, ms) {
    const el = $('flash');
    el.textContent = text;
    el.className = 'flash' + (kind === 'ok' ? ' is-ok' : '');
    el.hidden = false;
    if (kind === 'deny') KioskAudio.play('deny');
    clearTimeout(flashTimer);
    flashTimer = setTimeout(() => { el.hidden = true; }, ms || 3500);
  }

  // ------------------------------------------------------------------ accès à la configuration (code vérifié par Flask)
  const dlg = $('dlg-login');
  const codeInput = $('admin-code');
  let loginIdle = null;
  let shift = false;
  const ROWS = [
    ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0'],
    ['a', 'z', 'e', 'r', 't', 'y', 'u', 'i', 'o', 'p'],
    ['q', 's', 'd', 'f', 'g', 'h', 'j', 'k', 'l', 'm'],
    ['SHIFT', 'w', 'x', 'c', 'v', 'b', 'n', '-', '.', 'DEL'],
  ];

  function buildKeyboard() {
    const osk = $('osk');
    osk.textContent = '';
    ROWS.forEach((row) => {
      const r = document.createElement('div');
      r.className = 'osk__row';
      row.forEach((k) => {
        const b = document.createElement('button');
        b.type = 'button';
        b.dataset.k = k;
        if (k === 'SHIFT') { b.textContent = 'Maj'; b.className = 'osk__wide' + (shift ? ' is-on' : ''); b.setAttribute('aria-pressed', String(shift)); }
        else if (k === 'DEL') { b.textContent = 'Effacer'; b.className = 'osk__wide'; }
        else b.textContent = shift ? k.toUpperCase() : k;
        r.appendChild(b);
      });
      osk.appendChild(r);
    });
  }
  $('osk').addEventListener('click', (e) => {
    const b = e.target.closest('button');
    if (!b) return;
    const k = b.dataset.k;
    if (k === 'SHIFT') { shift = !shift; buildKeyboard(); }
    else if (k === 'DEL') codeInput.value = codeInput.value.slice(0, -1);
    else { codeInput.value += shift ? k.toUpperCase() : k; if (shift) { shift = false; buildKeyboard(); } }
    const n = codeInput.value.length;
    codeInput.focus();
    codeInput.setSelectionRange(n, n);  // curseur en fin de champ, même si on continue au clavier physique
    $('login-error').hidden = true;
    armLoginIdle();
  });

  function armLoginIdle() { clearTimeout(loginIdle); loginIdle = setTimeout(closeLogin, 60000); badgeWait(true); }
  // tant que la fenêtre est ouverte, un badge autorisé donne accès à la configuration (sans ouvrir la porte)
  let lastWaitCall = 0;
  function badgeWait(on) {
    if (on && Date.now() - lastWaitCall < 20000) return;
    lastWaitCall = on ? Date.now() : 0;
    fetch('/api/admin/badge-wait', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ on }) }).catch(() => {});
  }
  async function badgeLogin(token) {
    try {
      const r = await fetch('/api/admin/badge-login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token }) });
      const d = await r.json().catch(() => ({}));
      if (r.ok && d.ok) { setTimeout(() => { location.href = d.next || '/admin/badges'; }, 900); return; }
      showFlash(d.error || 'Accès refusé', 'deny');
    } catch (e) { showFlash('Serveur injoignable', 'deny'); }
  }
  function openLogin(message) {
    codeInput.value = ''; codeInput.type = 'password'; shift = false; buildKeyboard();
    $('login-error').textContent = message || '';
    $('login-error').hidden = !message;
    dlg.showModal();
    codeInput.focus();
    armLoginIdle();
  }
  function closeLogin() { clearTimeout(loginIdle); codeInput.value = ''; badgeWait(false); if (dlg.open) dlg.close(); }

  $('btn-config').addEventListener('click', () => openLogin());
  $('btn-login-cancel').addEventListener('click', closeLogin);
  $('btn-eye').addEventListener('click', () => { codeInput.type = codeInput.type === 'password' ? 'text' : 'password'; });
  codeInput.addEventListener('input', () => { $('login-error').hidden = true; armLoginIdle(); });
  $('form-login').addEventListener('submit', async (e) => {
    e.preventDefault();
    $('btn-login-ok').disabled = true;
    try {
      const r = await fetch('/api/admin/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code: codeInput.value }) });
      const d = await r.json().catch(() => ({}));
      if (r.ok && d.ok) { location.href = d.next || '/admin/badges'; return; }
      $('login-error').textContent = d.error || 'Code incorrect';
      $('login-error').hidden = false;
      codeInput.value = '';
      KioskAudio.play('deny');
    } catch (err) {
      $('login-error').textContent = 'Serveur injoignable';
      $('login-error').hidden = false;
    } finally { $('btn-login-ok').disabled = false; armLoginIdle(); }
  });
  // Retour depuis une page de configuration dont la session a expiré
  if (new URLSearchParams(location.search).get('admin') === '1') {
    history.replaceState(null, '', '/');
    setTimeout(() => openLogin('Session expirée, entrez à nouveau le code.'), 300);
  }

  // ------------------------------------------------------------------ démarrage
  KioskAudio.enabled = CFG.sound;
  $('site-name').textContent = CFG.site;
  $('cabinet-name').textContent = CFG.cabinet;
  pollStatus();
  pollState();
  pollLogs();
  setInterval(tick, 250);
  tick();
})();
