(function ($) {
  'use strict';

  var $preview = null;

  function insertPreview() {
    // Insert preview div after the .field-user row
    var $userField = $('.field-user');
    if ($userField.length && !$('#customer-lookup-preview').length) {
      $userField.after(
        '<div id="customer-lookup-preview" style="margin:-4px 0 10px 170px;max-width:520px;font-size:13px;"></div>'
      );
    }
    $preview = $('#customer-lookup-preview');
  }

  function buildAddress(data) {
    var lines = [data.name.toUpperCase()];
    if (data.company)    lines.push(data.company);
    if (data.address)    lines.push(data.address);
    if (data.gst_number) lines.push('GSTIN/UIN : ' + data.gst_number);
    return lines.join('\n');
  }

  function fetchUser(userId, autoFill) {
    if (!userId) {
      if ($preview) $preview.html('');
      return;
    }
    if ($preview) {
      $preview.html('<div style="color:#6b7280;padding:4px 0;">Loading&hellip;</div>');
    }
    $.getJSON('/api/auth/admin/user-lookup/', { id: userId })
      .done(function (data) {
        if (!$preview) return;
        if (data.found) {
          var lines = ['<strong style="color:#166534;">&#10003; ' + data.name + '</strong>'];
          if (data.company)    lines.push(data.company);
          if (data.gst_number) lines.push('GSTIN: <strong>' + data.gst_number + '</strong>');
          if (data.address)    lines.push(data.address.replace(/\n/g, '<br>'));
          if (data.phone)      lines.push('&#128222; ' + data.phone);
          $preview.html(
            '<div style="background:#f0fdf4;border:1px solid #86efac;border-radius:6px;' +
            'padding:10px 14px;line-height:1.8;">' +
            lines.join('<br>') + '</div>'
          );

          if (autoFill) {
            var addr = buildAddress(data);
            // Fill ship_to / bill_to only if they are still empty
            if (!$('#id_ship_to').val().trim()) $('#id_ship_to').val(addr);
            if (!$('#id_bill_to').val().trim()) $('#id_bill_to').val(addr);
          }
        } else {
          $preview.html('');
        }
      })
      .fail(function () {
        if ($preview) $preview.html('');
      });
  }

  $(document).ready(function () {
    insertPreview();

    // Fired when admin selects or clears the user from the autocomplete dropdown
    $(document).on('select2:select', '#id_user', function () {
      fetchUser($(this).val(), true);
    });
    $(document).on('select2:clear', '#id_user', function () {
      if ($preview) $preview.html('');
    });

    // On the change form the user is already selected — show preview without overwriting saved addresses
    var initialUserId = $('#id_user').val();
    if (initialUserId) {
      fetchUser(initialUserId, false);
    }
  });
})(django.jQuery);
