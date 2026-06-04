/* Senior UI enhancements: safe, progressive, no dependency on business logic. */
(function () {
  'use strict';

  function ready(fn) {
    if (document.readyState !== 'loading') fn();
    else document.addEventListener('DOMContentLoaded', fn);
  }

  ready(function () {
    var path = window.location.pathname.replace(/\/$/, '') || '/';

    // Mark active sidebar links so the user always knows where they are.
    document.querySelectorAll('.pc-sidebar a.pc-link[href]').forEach(function (link) {
      var href = link.getAttribute('href');
      if (!href || href === '#!' || href === '#') return;
      var linkPath;
      try { linkPath = new URL(href, window.location.origin).pathname.replace(/\/$/, '') || '/'; }
      catch (e) { return; }
      if (linkPath === path) {
        var item = link.closest('.pc-item');
        if (item) item.classList.add('ui-active');
        var parent = link.closest('.pc-hasmenu');
        if (parent) parent.classList.add('pc-trigger', 'ui-active');
      }
    });

    // Make ordinary tables responsive without editing every template.
    document.querySelectorAll('table.table, table.datatable, table.dataTable').forEach(function (table) {
      if (!table.closest('.table-responsive')) {
        var wrapper = document.createElement('div');
        wrapper.className = 'table-responsive ui-table-wrap';
        table.parentNode.insertBefore(wrapper, table);
        wrapper.appendChild(table);
      }
    });

    // Add loading feedback to submit buttons; respects forms that opt out.
    document.querySelectorAll('form:not([data-no-loading])').forEach(function (form) {
      form.addEventListener('submit', function () {
        var button = form.querySelector('button[type="submit"], input[type="submit"]');
        if (!button || button.disabled) return;
        var text = button.tagName === 'INPUT' ? button.value : button.textContent;
        button.setAttribute('data-original-text', text || 'Submit');
        button.disabled = true;
        if (button.tagName === 'INPUT') button.value = 'Processing...';
        else button.innerHTML = '<span class="spinner-border spinner-border-sm" aria-hidden="true"></span><span>Processing...</span>';
      }, { capture: true });
    });

    // Lightweight confirmation for destructive links/buttons that do not already have a handler.
    document.querySelectorAll('a, button').forEach(function (el) {
      if (el.dataset.confirmBound || el.dataset.noConfirm === 'true') return;
      var label = (el.textContent || '').toLowerCase();
      var href = (el.getAttribute('href') || '').toLowerCase();
      var name = (el.getAttribute('name') || '').toLowerCase();
      var action = (el.getAttribute('formaction') || '').toLowerCase();
      var destructive = /delete|remove|trash/.test(label + ' ' + href + ' ' + name + ' ' + action);
      if (!destructive) return;
      el.dataset.confirmBound = 'true';
      el.addEventListener('click', function (event) {
        if (el.dataset.confirmed === 'true') return;
        var ok = window.confirm('Please confirm this action. It may affect saved school records.');
        if (!ok) {
          event.preventDefault();
          event.stopPropagation();
        }
      });
    });

    // Improve accessibility of icon-only buttons/links.
    document.querySelectorAll('a, button').forEach(function (el) {
      var hasText = (el.textContent || '').trim().length > 0;
      if (hasText || el.getAttribute('aria-label') || el.getAttribute('title')) return;
      var icon = el.querySelector('i');
      if (icon) el.setAttribute('aria-label', 'Action');
    });
  });
})();
