/* Bips générés par le navigateur (Web Audio API) — aucun fichier son nécessaire.
   En mode kiosque, lancer Chromium avec --autoplay-policy=no-user-gesture-required,
   sinon le son ne démarre qu'après un premier toucher de l'écran. */
(function () {
  'use strict';
  let ctx = null;

  function context() {
    if (!ctx) {
      const AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return null;
      ctx = new AC();
    }
    return ctx;
  }

  // Une note : fréquence (Hz), départ (s), durée (s), forme, volume
  function tone(freq, start, dur, type, vol) {
    const c = context();
    const t0 = c.currentTime + start;
    const osc = c.createOscillator();
    const gain = c.createGain();
    osc.type = type || 'square';
    osc.frequency.setValueAtTime(freq, t0);
    gain.gain.setValueAtTime(0.0001, t0);
    gain.gain.exponentialRampToValueAtTime(vol || 0.25, t0 + 0.01);
    gain.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
    osc.connect(gain).connect(c.destination);
    osc.start(t0);
    osc.stop(t0 + dur + 0.02);
  }

  const patterns = {
    alert: () => { tone(1046, 0, 0.16, 'square', 0.22); tone(784, 0.2, 0.16, 'square', 0.22); },
    ok: () => { tone(660, 0, 0.09, 'sine', 0.3); tone(990, 0.1, 0.14, 'sine', 0.3); },
    deny: () => { tone(220, 0, 0.18, 'sawtooth', 0.2); tone(196, 0.22, 0.3, 'sawtooth', 0.2); },
    open: () => { tone(880, 0, 0.08, 'sine', 0.2); },
  };

  window.KioskAudio = {
    enabled: true,
    // true si le navigateur autorise le son
    get ready() { const c = context(); return !!c && c.state === 'running'; },
    unlock() {
      const c = context();
      if (c && c.state !== 'running') return c.resume().catch(() => {});
      return Promise.resolve();
    },
    play(kind) {
      if (!this.enabled) return;
      const c = context();
      if (!c) return;
      if (c.state !== 'running') { c.resume().catch(() => {}); return; }
      (patterns[kind] || patterns.alert)();
    },
  };
})();
