(function () {
  'use strict';

  var _pendingUrl = null;

  var TYPES = {
    approve: { icon: '✅', label: 'Yes, Approve', bg: '#16a34a' },
    reject:  { icon: '🚫', label: 'Yes, Reject',  bg: '#dc2626' },
    revoke:  { icon: '⚠️',  label: 'Yes, Revoke',  bg: '#b45309' },
  };

  function build() {
    if (document.getElementById('mc-overlay')) return;
    document.body.insertAdjacentHTML('beforeend', [
      '<div id="mc-overlay" style="',
        'position:fixed;inset:0;background:rgba(0,0,0,.6);',
        'display:none;align-items:center;justify-content:center;z-index:99999;">',
        '<div id="mc-card" style="',
          'background:#1e293b;border:1px solid #334155;border-radius:16px;',
          'padding:36px 40px;max-width:420px;width:90%;',
          'box-shadow:0 32px 80px rgba(0,0,0,.7);text-align:center;">',
          '<div id="mc-icon"  style="font-size:48px;margin-bottom:12px;line-height:1;"></div>',
          '<p  id="mc-msg"   style="color:#e2e8f0;font-size:14px;font-weight:500;',
            'margin:0 0 28px;line-height:1.65;"></p>',
          '<div style="display:flex;gap:10px;justify-content:center;">',
            '<button id="mc-yes" style="',
              'padding:10px 28px;border:none;border-radius:10px;',
              'font-size:13px;font-weight:700;cursor:pointer;',
              'color:#fff;min-width:130px;transition:opacity .15s;">Confirm</button>',
            '<button id="mc-no"  style="',
              'padding:10px 28px;border:1px solid #475569;border-radius:10px;',
              'background:transparent;color:#94a3b8;',
              'font-size:13px;font-weight:600;cursor:pointer;min-width:110px;">Cancel</button>',
          '</div>',
        '</div>',
      '</div>',
    ].join(''));

    document.getElementById('mc-no').addEventListener('click', close);
    document.getElementById('mc-overlay').addEventListener('click', function (e) {
      if (e.target.id === 'mc-overlay') close();
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') close();
    });
  }

  function close() {
    var el = document.getElementById('mc-overlay');
    if (el) el.style.display = 'none';
    _pendingUrl = null;
  }

  function refreshConfirmBtn(t) {
    var old = document.getElementById('mc-yes');
    var btn = old.cloneNode(true);
    btn.textContent       = t.label;
    btn.style.background  = t.bg;
    old.parentNode.replaceChild(btn, old);
    btn.addEventListener('click', function () {
      if (_pendingUrl) window.location.href = _pendingUrl;
      close();
    });
  }

  window.adminConfirm = function (msg, url, type) {
    build();
    _pendingUrl = url;
    var t = TYPES[type] || TYPES.approve;
    document.getElementById('mc-icon').textContent = t.icon;
    document.getElementById('mc-msg').textContent  = msg;
    refreshConfirmBtn(t);
    document.getElementById('mc-overlay').style.display = 'flex';
  };
}());
