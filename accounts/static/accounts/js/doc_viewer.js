(function () {
  'use strict';

  function openDocViewer(url, name) {
    var old = document.getElementById('_doc_viewer_overlay');
    if (old) old.remove();

    var overlay = document.createElement('div');
    overlay.id = '_doc_viewer_overlay';
    overlay.style.cssText = [
      'position:fixed;inset:0;background:rgba(0,0,0,.72);z-index:99999;',
      'display:flex;align-items:center;justify-content:center;',
    ].join('');

    var card = document.createElement('div');
    card.style.cssText = [
      'background:#1e293b;border-radius:14px;',
      'width:92vw;height:92vh;max-width:1200px;',
      'display:flex;flex-direction:column;overflow:hidden;',
      'box-shadow:0 32px 64px rgba(0,0,0,.6);',
    ].join('');

    /* ── header ── */
    var hdr = document.createElement('div');
    hdr.style.cssText = [
      'display:flex;align-items:center;justify-content:space-between;',
      'padding:10px 16px;border-bottom:1px solid rgba(255,255,255,.1);',
      'flex-shrink:0;',
    ].join('');

    var lbl = document.createElement('span');
    lbl.style.cssText = 'color:#cbd5e1;font-size:13px;font-weight:600;font-family:sans-serif;max-width:70%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;';
    lbl.textContent = name || 'Document';

    var closeBtn = document.createElement('button');
    closeBtn.type = 'button';
    closeBtn.style.cssText = [
      'display:inline-flex;align-items:center;gap:6px;',
      'background:#ef4444;border:none;color:#fff;',
      'border-radius:8px;padding:6px 14px;cursor:pointer;',
      'font-size:13px;font-weight:700;font-family:sans-serif;',
      'transition:background .15s;',
    ].join('');
    closeBtn.innerHTML = '&#10005; Close';
    closeBtn.onmouseover = function () { this.style.background = '#dc2626'; };
    closeBtn.onmouseout  = function () { this.style.background = '#ef4444'; };

    hdr.appendChild(lbl);
    hdr.appendChild(closeBtn);

    /* ── iframe ── */
    var frame = document.createElement('iframe');
    var fullUrl = url.startsWith('/') ? window.location.origin + url : url;
    frame.src   = fullUrl;
    frame.title = name || 'Document';
    frame.style.cssText = 'flex:1;border:none;width:100%;background:#fff;';

    card.appendChild(hdr);
    card.appendChild(frame);
    overlay.appendChild(card);
    document.body.appendChild(overlay);

    function close() { overlay.remove(); }

    closeBtn.onclick = close;
    overlay.addEventListener('click', function (e) { if (e.target === overlay) close(); });

    var escHandler = function (e) {
      if (e.key === 'Escape') { close(); document.removeEventListener('keydown', escHandler); }
    };
    document.addEventListener('keydown', escHandler);
  }

  window.openDocViewer = openDocViewer;
}());
