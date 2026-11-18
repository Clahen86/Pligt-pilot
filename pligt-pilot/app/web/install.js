// "Læg på hjemmeskærmen": a button where the browser can install the page as an app, a short tip on iPhone/iPad.
(function () {
  if (!/\/(k|p)\/[^/]+\//.test(location.pathname)) { return; }
  var standalone = (window.matchMedia && matchMedia('(display-mode: standalone)').matches) || navigator.standalone;
  if (standalone) { return; }
  try { if (localStorage.getItem('pp_install_later') > Date.now()) { return; } } catch (e) { /* private mode */ }
  var T = function (s) { return window.ppT ? window.ppT(s) : s; };
  var ios = /iphone|ipad|ipod/i.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  var asked = null, box = null;
  var SHARE = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="vertical-align:-3px"><path d="M12 3v12M7 8l5-5 5 5M5 13v6a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-6"/></svg>';

  function close(later) {
    if (box) { box.remove(); box = null; document.body.style.paddingBottom = ''; }
    if (later) { try { localStorage.setItem('pp_install_later', String(Date.now() + 7 * 864e5)); } catch (e) { /* ignore */ } }
  }
  function show() {
    if (box) { return; }
    box = document.createElement('div');
    box.setAttribute('role', 'dialog');
    box.style.cssText = 'position:fixed;left:12px;right:12px;bottom:max(12px,env(safe-area-inset-bottom));z-index:50;max-width:440px;margin:0 auto;' +
      'background:#fff;color:var(--ink,#22304A);border-radius:20px;padding:14px 16px;box-shadow:0 10px 30px rgba(34,48,74,.18);' +
      'display:flex;gap:12px;align-items:center;font-family:inherit';
    var how = asked ? T('Så åbner den som en app med ét tryk.')
      : T('Tryk på Del-knappen og vælg »Føj til hjemmeskærm«.').replace(/(Del|Share|Teilen|Dela)/, '$1 ' + SHARE);
    box.innerHTML = '<img src="icon.png" alt="" width="44" height="44" style="border-radius:12px;flex:none">' +
      '<div style="flex:1;min-width:0"><div style="font-weight:900;font-size:15px;line-height:1.2">' + T('Læg Pligter på hjemmeskærmen') + '</div>' +
      '<div style="font-size:13px;font-weight:700;color:var(--muted,#55627A);margin-top:2px">' + how + '</div></div>' +
      (asked ? '<button data-i style="flex:none;border:0;border-radius:999px;padding:10px 16px;background:var(--accent,#0B7A70);color:#fff;font-weight:900;font-size:14px">' + T('Installer') + '</button>' : '') +
      '<button data-x aria-label="' + T('Ikke nu') + '" style="flex:none;border:0;background:none;color:var(--muted,#55627A);font-size:22px;line-height:1;padding:4px">&times;</button>';
    box.querySelector('[data-x]').onclick = function () { close(true); };
    var go = box.querySelector('[data-i]');
    if (go) {
      go.onclick = function () {
        asked.prompt();
        asked.userChoice.then(function (c) { close(c.outcome !== 'accepted'); asked = null; }).catch(function () { close(false); });
      };
    }
    document.body.appendChild(box);
    document.body.style.paddingBottom = (box.offsetHeight + 24) + 'px';
  }
  window.addEventListener('beforeinstallprompt', function (e) { e.preventDefault(); asked = e; close(false); setTimeout(show, 1200); });
  window.addEventListener('appinstalled', function () { close(false); });
  // the children's page already says how on iPhone (with the notifications); the parents' page gets the tip here
  if (ios && window.isSecureContext && /\/p\/[^/]+\//.test(location.pathname)) { setTimeout(show, 2500); }
})();
