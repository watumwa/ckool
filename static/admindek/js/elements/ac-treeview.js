'use strict';
(function () {
  // Check if VanillaTree is loaded
  if (typeof VanillaTree === 'undefined') {
    return;
  }

  // [ html-demo ]
  const main = document.querySelector('#tree-demo');
  const info = document.querySelector('#tree-msg');

  if (!main || !info) {
    return;
  }

  const tree = new VanillaTree(main, {
    contextmenu: [
      {
        label: 'View Details',
        action: function (id) {
          info.innerHTML = 'Viewing details for: ' + id;
        }
      },
      {
        label: 'Copy ID',
        action: function (id) {
          navigator.clipboard.writeText(id).then(() => {
            info.innerHTML = 'ID copied to clipboard: ' + id;
          });
        }
      }
    ]
  });

  // Add root level items
  tree.add({
    label: 'Documents',
    id: 'documents',
    opened: true
  });

  tree.add({
    label: 'Projects',
    id: 'projects',
    opened: true
  });

  tree.add({
    label: 'Settings',
    id: 'settings'
  });

  // Add sub-items under Documents
  tree.add({
    label: 'Reports',
    parent: 'documents',
    id: 'reports',
    opened: true,
    selected: true
  });

  tree.add({
    label: 'Archives',
    parent: 'documents',
    id: 'archives'
  });

  // Add sub-items under Reports
  tree.add({
    label: 'Monthly Report.pdf',
    parent: 'reports',
    id: 'monthly-report'
  });

  tree.add({
    label: 'Quarterly Report.pdf',
    parent: 'reports',
    id: 'quarterly-report'
  });

  // Add sub-items under Projects
  tree.add({
    label: 'Dashboard Project',
    parent: 'projects',
    id: 'dashboard-project'
  });

  tree.add({
    label: 'Website Redesign',
    parent: 'projects',
    id: 'website-redesign'
  });

  // Add sub-items under Settings
  tree.add({
    label: 'User Preferences',
    parent: 'settings',
    id: 'user-preferences'
  });

  tree.add({
    label: 'Security Settings',
    parent: 'settings',
    id: 'security-settings'
  });

  main.addEventListener('vtree-open', function (evt) {
    info.innerHTML = '<span class="text-success">✓</span> Expanded: ' + evt.detail.id;
  });

  main.addEventListener('vtree-close', function (evt) {
    info.innerHTML = '<span class="text-warning">−</span> Collapsed: ' + evt.detail.id;
  });

  main.addEventListener('vtree-select', function (evt) {
    info.innerHTML = '<span class="text-primary">▶</span> Selected: ' + evt.detail.id;
  });

  // Initialize with a welcome message
  info.innerHTML = '<span class="text-muted">Ready. Click on tree items to interact.</span>';
})();
