(function () {
  'use strict';
  document.addEventListener('DOMContentLoaded', function () {
    var dark = document.documentElement.getAttribute('data-theme') === 'dark'
               || document.body.classList.contains('dark')
               || window.matchMedia('(prefers-color-scheme: dark)').matches;

    document.querySelectorAll('[data-doc-status]').forEach(function (el) {
      var status = el.getAttribute('data-doc-status');
      var row    = el.closest('tr');
      if (!row) return;

      if (status === 'rejected') {
        row.style.background  = dark ? '#3b0a0a' : '#fff1f2';
        row.style.borderLeft  = '3px solid #f43f5e';
        row.style.color       = dark ? '#fca5a5' : '';
      } else if (status === 'downloaded') {
        row.style.background  = dark ? '#052e16' : '#f0fdf4';
        row.style.borderLeft  = '3px solid #22c55e';
        row.style.color       = dark ? '#86efac' : '';
      }
    });

    /* also fix badge colours in dark mode */
    if (!dark) return;
    document.querySelectorAll('[data-badge-type]').forEach(function (badge) {
      var type = badge.getAttribute('data-badge-type');
      if (type === 'rejected') {
        badge.style.background = '#7f1d1d';
        badge.style.color      = '#fca5a5';
      } else if (type === 'downloaded') {
        badge.style.background = '#14532d';
        badge.style.color      = '#86efac';
      } else if (type === 'pending') {
        badge.style.background = '#1e1b4b';
        badge.style.color      = '#a5b4fc';
      }
    });
  });
}());
