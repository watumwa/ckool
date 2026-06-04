/**
=========================================================================
=========================================================================
Template Name: Admindek - Admin Template
Author: DashboardPack
Support: https://dashboardpack.com/
File: themes.js
Description:  this file will contains overall theme setup and handle
              behavior of live custumizer like Dark/Light, LTR/RTL,
              preset color, theme layout, theme contarast etc.
=========================================================================
=========================================================================
*/

var rtl_flag = false;
var dark_flag = false;

// Calculate base path for assets based on current page location
function getBasePath() {
  var pathname = window.location.pathname;
  
  // For local file system (file://) just return empty
  if (window.location.protocol === 'file:') {
    return '';
  }
  
  // Remove filename to get directory
  var path = pathname.substring(0, pathname.lastIndexOf('/') + 1);
  
  // Count directory depth from root
  var depth = 0;
  var segments = path.split('/').filter(function(s) { return s.length > 0; });
  
  // If we're at root or index
  if (segments.length === 0 || (segments.length === 1 && segments[0].includes('.html'))) {
    return '';
  }
  
  // For nested pages, calculate relative path
  depth = segments.length;
  
  // If the last segment isn't a directory (has extension), reduce depth
  if (pathname.includes('.html') && pathname !== '/index.html') {
    var lastSegment = pathname.split('/').pop();
    if (lastSegment && lastSegment !== 'index.html') {
      depth = Math.max(0, segments.length);
    }
  }
  
  // Return appropriate relative path
  if (depth === 0) {
    return '';
  }
  return '../'.repeat(depth);
}


// dark switch mode
function dark_mode() {
  const darkModeToggle = document.getElementById('dark-mode');

  // Ensure the element exists before proceeding
  if (!darkModeToggle) return;

  // Toggle between dark and light modes based on the checkbox status
  const mode = darkModeToggle.checked ? 'dark' : 'light';
  layout_change(mode);
}

// preset color
document.addEventListener('DOMContentLoaded', function () {
  function addClickListeners(selector, changeFunction) {
    const elements = document.querySelectorAll(`${selector} > a, ${selector} > button`);
    elements.forEach((element) => {
      element.addEventListener('click', (event) => {
        event.preventDefault();
        let target = event.currentTarget; // Use currentTarget instead of target for better event handling
        const value = target.getAttribute('data-value'); // Get data-value attribute
        if (value !== null) {
          changeFunction(value); // Call the corresponding change function
        }
      });
    });
  }

  // Add event listeners for various UI elements using the reusable function
  addClickListeners('.preset-color', preset_change);
  addClickListeners('.header-color', header_change);
  addClickListeners('.navbar-color', navbar_change);
  addClickListeners('.logo-color', logo_change);
  addClickListeners('.caption-color', caption_change);
  addClickListeners('.drp-menu-icon', drp_menu_icon_change);
  addClickListeners('.drp-menu-link-icon', drp_menu_link_icon_change);

  // Initialize SimpleBar if .pct-body exists
  const pctBody = document.querySelector('.pct-body');
  if (pctBody) {
    new SimpleBar(pctBody);
  }

  // Add event listener to reset button to reset all theme settings
  const layoutReset = document.querySelector('#layoutreset');
  if (layoutReset) {
    layoutReset.addEventListener('click', () => resetAllThemeSettings());
  }

  // Add event listeners for color reset buttons
  const resetButtons = document.querySelectorAll('.reset-color-btn');
  resetButtons.forEach(button => {
    button.addEventListener('click', (event) => {
      event.preventDefault();
      const target = button.getAttribute('data-target');
      resetColorToDefault(target);
    });
  });

  // Initialize modern customizer search functionality
  const customizerSearch = document.querySelector('#customizer-search');
  if (customizerSearch) {
    customizerSearch.addEventListener('input', function(e) {
      const searchTerm = e.target.value.toLowerCase();
      const settingItems = document.querySelectorAll('.setting-item');
      
      settingItems.forEach(item => {
        const label = item.querySelector('.setting-label');
        const help = item.querySelector('.setting-help');
        const searchableText = (label?.textContent + ' ' + help?.textContent).toLowerCase();
        
        if (searchableText.includes(searchTerm) || searchTerm === '') {
          item.style.display = 'flex';
        } else {
          item.style.display = 'none';
        }
      });
      
      // Show/hide group headers based on visible items
      document.querySelectorAll('.settings-group').forEach(group => {
        const visibleItems = group.querySelectorAll('.setting-item[style="display: flex;"], .setting-item:not([style*="display: none"])');
        
        if (visibleItems.length === 0 && searchTerm !== '') {
          group.style.display = 'none';
        } else {
          group.style.display = 'block';
        }
      });
    });
  }
});

function layout_theme_sidebar_change(value) {
  // Set the sidebar theme attribute on the <body> element
  document.body.setAttribute('data-pc-sidebar_theme', value);

  // Select the sidebar logo and update its source based on the selected theme
  // Logo updates handled by templates
  // const logo = document.querySelector('.pc-sidebar .m-header .logo-lg');
  // if (logo) {
  //   const logoSrc = value === 'true' ? getBasePath() + 'assets/images/logo-dark.svg' : getBasePath() + 'assets/images/logo-white.svg';
  //   logo.setAttribute('src', logoSrc);
  // }

  // Remove 'active' class from the currently active button, if it exists
  const activeBtn = document.querySelector('.sidebar-theme .btn.active');
  if (activeBtn) {
    activeBtn.classList.remove('active');
  }

  // Add 'active' class to the button corresponding to the selected value
  const newActiveBtn = document.querySelector(`.sidebar-theme .btn[data-value='${value}']`);
  if (newActiveBtn) {
    newActiveBtn.classList.add('active');
  }
}

function layout_caption_change(value) {
  // Set the sidebar caption attribute on the <body> element based on the provided value
  document.body.setAttribute('data-pc-sidebar-caption', value);

  // Select the active button if it exists
  const activeBtn = document.querySelector('.theme-nav-caption .btn.active');
  if (activeBtn) {
    activeBtn.classList.remove('active'); // Remove 'active' from the current button
  }

  // Add 'active' class to the button corresponding to the selected value
  const newActiveBtn = document.querySelector(`.theme-nav-caption .btn[data-value='${value}']`);
  if (newActiveBtn) {
    newActiveBtn.classList.add('active');
  }
}

function layout_sidebar_icons_change(value) {
  // Set the sidebar icons attribute on the <body> element based on the provided value
  document.body.setAttribute('data-pc-sidebar-icons', value);

  // Select the active button if it exists
  const activeBtn = document.querySelector('.sidebar-icons .toggle-option.active');
  if (activeBtn) {
    activeBtn.classList.remove('active'); // Remove 'active' from the current button
  }

  // Add 'active' class to the button corresponding to the selected value
  const newActiveBtn = document.querySelector(`.sidebar-icons .toggle-option[data-value='${value}']`);
  if (newActiveBtn) {
    newActiveBtn.classList.add('active');
  }
}

function change_attribute(type, value, selector) {
  // Set the relevant data attribute on the <body> element
  document.body.setAttribute(`data-pc-${type}`, value);

  // Check if the off-canvas control exists
  const control = document.querySelector('.pct-offcanvas, .pct-offcanvas-modern');
  if (control) {
    // Remove 'active' class from the currently active element
    const activeElement = document.querySelector(`${selector} > a.active, ${selector} > button.active`);
    if (activeElement) {
      activeElement.classList.remove('active');
    }

    // Add 'active' class to the newly selected element
    const newActiveElement = document.querySelector(`${selector} > a[data-value='${value}'], ${selector} > button[data-value='${value}']`);
    if (newActiveElement) {
      newActiveElement.classList.add('active');
    }
  }
}

// Specific functions that call the generic change_attribute function
function preset_change(value) {
  change_attribute('preset', value, '.preset-color');
}
function header_change(value) {
  change_attribute('header', value, '.header-color');
}
function navbar_change(value) {
  change_attribute('navbar', value, '.navbar-color');
}
function logo_change(value) {
  change_attribute('logo', value, '.logo-color');
}
function caption_change(value) {
  change_attribute('caption', value, '.caption-color');
}

function drp_menu_icon_change(value) {
  // Set the 'data-pc-drp-menu-icon' attribute on the <body> to the selected value
  document.body.setAttribute('data-pc-drp-menu-icon', value);

  // Select the off-canvas menu element, if it exists
  const control = document.querySelector('.pct-offcanvas, .pct-offcanvas-modern');

  if (control) {
    // Remove the 'active' class from the currently active menu icon
    const activeIcon = document.querySelector('.drp-menu-icon > a.active, .drp-menu-icon > button.active');
    if (activeIcon) {
      activeIcon.classList.remove('active');
    }

    // Add the 'active' class to the newly selected icon based on the value
    const newActiveIcon = document.querySelector(`.drp-menu-icon > a[data-value='${value}'], .drp-menu-icon > button[data-value='${value}']`);
    if (newActiveIcon) {
      newActiveIcon.classList.add('active');
    }
  }
}
function drp_menu_link_icon_change(value) {
  const body = document.body;
  body.setAttribute('data-pc-drp-menu-link-icon', value); // Update dropdown menu icon attribute

  const activeIcon = document.querySelector('.drp-menu-link-icon > a.active, .drp-menu-link-icon > button.active');
  const targetIcon = document.querySelector(`.drp-menu-link-icon > a[data-value='${value}'], .drp-menu-link-icon > button[data-value='${value}']`);

  // Safely remove the active class from the current element, if any
  if (activeIcon) activeIcon.classList.remove('active');

  // Add the active class to the target element, if it exists
  if (targetIcon) targetIcon.classList.add('active');
}


function layout_rtl_change(value) {
  const body = document.querySelector('body');
  const html = document.querySelector('html');
  const directionControl = document.querySelector('.theme-direction .btn.active');
  const rtlBtn = document.querySelector(".theme-direction .btn[data-value='true']");
  const ltrBtn = document.querySelector(".theme-direction .btn[data-value='false']");

  if (value === 'true') {
    rtl_flag = true;
    body.setAttribute('data-pc-direction', 'rtl');
    html.setAttribute('dir', 'rtl');
    html.setAttribute('lang', 'ar');

    // Update active button state for RTL
    if (directionControl) directionControl.classList.remove('active');
    if (rtlBtn) rtlBtn.classList.add('active');
  } else {
    rtl_flag = false;
    body.setAttribute('data-pc-direction', 'ltr');
    html.removeAttribute('dir');
    html.removeAttribute('lang');

    // Update active button state for LTR
    if (directionControl) directionControl.classList.remove('active');
    if (ltrBtn) ltrBtn.classList.add('active');
  }
}

function updateLogo(selector, logoPath) {
  const element = document.querySelector(selector);
  if (element) {
    element.setAttribute('src', logoPath);
  }
}

// Helper function to toggle button states
function updateActiveButton(layout) {
  const activeBtn = document.querySelector('.theme-layout .btn.active');
  const targetBtn = document.querySelector(`.theme-layout .btn[data-value='${layout === 'dark' ? 'false' : 'true'}']`);

  if (activeBtn) activeBtn.classList.remove('active');
  if (targetBtn) targetBtn.classList.add('active');
}

// Main function to change the layout theme (dark or light)
function layout_change(layout) {
  const body = document.body;
  body.setAttribute('data-pc-theme', layout); // Set the theme attribute

  dark_flag = layout === 'dark'; // Set the dark mode flag

  // Logo paths handled by templates
  // const logoPath = getBasePath() + `assets/images/logo-${layout === 'dark' ? 'white' : 'dark'}.svg`;

  // Update logos across multiple locations
  updateLogo('.footer-top .footer-logo', logoPath);
  updateLogo('.brand-logo', logoPath);
  updateLogo('.invoice-logo', logoPath);
  updateLogo('.auth-wrapper:not(.v3) a>img', logoPath);
  updateLogo('[data-pc-layout="horizontal"] .pc-sidebar .m-header .logo-lg', logoPath);

  // Update active button state
  updateActiveButton(layout);
}

function change_box_container(value) {
  // Check if the .pc-content element exists
  if (document.querySelector('.pc-content')) {
    // If value is 'true', switch to boxed layout
    if (value == 'true') {
      // Add 'container' class to the content and footer, remove 'container-fluid' from the footer
      document.querySelector('.pc-content').classList.add('container');
      document.querySelector('.footer-wrapper').classList.add('container');
      document.querySelector('.footer-wrapper').classList.remove('container-fluid');

      // Update the active button for the boxed layout option
      var control = document.querySelector('.theme-container .btn.active');
      if (control) {
        control.classList.remove('active');
        document.querySelector(".theme-container .btn[data-value='true']").classList.add('active');
      }
    }
    // If value is not 'true', switch to full-width layout
    else {
      // Remove 'container' class and add 'container-fluid' to the footer
      document.querySelector('.pc-content').classList.remove('container');
      document.querySelector('.footer-wrapper').classList.remove('container');
      document.querySelector('.footer-wrapper').classList.add('container-fluid');

      // Update the active button for the full-width layout option
      var control = document.querySelector('.theme-container .btn.active');
      if (control) {
        control.classList.remove('active');
        document.querySelector(".theme-container .btn[data-value='false']").classList.add('active');
      }
    }
  }
}

function resetColorToDefault(target) {
  // Remove current color attributes from body
  switch(target) {
    case 'preset-color':
      document.body.removeAttribute('data-pc-preset');
      // Reset to first preset (Ocean Blue)
      preset_change('preset-1');
      break;
    case 'header-color':
      document.body.removeAttribute('data-pc-header');
      // Clear active state from all header color buttons
      const headerButtons = document.querySelectorAll('.header-color .color-swatch-small');
      headerButtons.forEach(btn => btn.classList.remove('active'));
      break;
    case 'navbar-color':
      document.body.removeAttribute('data-pc-navbar');
      // Clear active state from all navbar color buttons
      const navbarButtons = document.querySelectorAll('.navbar-color .color-swatch-small');
      navbarButtons.forEach(btn => btn.classList.remove('active'));
      break;
    case 'logo-color':
      document.body.removeAttribute('data-pc-logo');
      // Clear active state from all logo color buttons
      const logoButtons = document.querySelectorAll('.logo-color .color-swatch-small');
      logoButtons.forEach(btn => btn.classList.remove('active'));
      break;
    case 'caption-color':
      document.body.removeAttribute('data-pc-caption');
      // Clear active state from all caption color buttons
      const captionButtons = document.querySelectorAll('.caption-color .color-swatch-small');
      captionButtons.forEach(btn => btn.classList.remove('active'));
      break;
  }
}

function resetAllThemeSettings() {
  // Reset all theme attributes to defaults
  document.body.removeAttribute('data-pc-preset');
  document.body.removeAttribute('data-pc-header');
  document.body.removeAttribute('data-pc-navbar');
  document.body.removeAttribute('data-pc-logo');
  document.body.removeAttribute('data-pc-caption');
  document.body.removeAttribute('data-pc-drp-menu-icon');
  document.body.removeAttribute('data-pc-drp-menu-link-icon');
  document.body.setAttribute('data-pc-theme', 'light');
  document.body.setAttribute('data-pc-sidebar_theme', 'false');
  document.body.setAttribute('data-pc-sidebar-caption', 'true');
  document.body.setAttribute('data-pc-sidebar-icons', 'true');
  document.body.setAttribute('data-pc-direction', 'ltr');
  
  // Reset HTML attributes
  const html = document.querySelector('html');
  html.removeAttribute('dir');
  html.removeAttribute('lang');
  
  // Reset logos - Commented out as paths are handled by templates
  // updateLogo('.footer-top .footer-logo', getBasePath() + 'assets/images/logo-dark.svg');
  // updateLogo('.brand-logo', getBasePath() + 'assets/images/logo-dark.svg');
  // updateLogo('.invoice-logo', getBasePath() + 'assets/images/logo-dark.svg');
  // updateLogo('.auth-wrapper:not(.v3) a>img', getBasePath() + 'assets/images/logo-dark.svg');
  // updateLogo('[data-pc-layout="horizontal"] .pc-sidebar .m-header .logo-lg', getBasePath() + 'assets/images/logo-dark.svg');
  // updateLogo('.pc-sidebar .m-header .logo-lg', getBasePath() + 'assets/images/logo-white.svg');
  
  // Reset box container to full width
  const pcContent = document.querySelector('.pc-content');
  if (pcContent) {
    pcContent.classList.remove('container');
    const footerWrapper = document.querySelector('.footer-wrapper');
    if (footerWrapper) {
      footerWrapper.classList.remove('container');
      footerWrapper.classList.add('container-fluid');
    }
  }
  
  // Reset all UI states
  resetUIStates();
}

function resetUIStates() {
  // Reset theme mode buttons
  const themeModeButtons = document.querySelectorAll('.theme-mode-btn');
  themeModeButtons.forEach(btn => btn.classList.remove('active'));
  const lightModeBtn = document.querySelector('.theme-mode-btn[data-mode="light"]');
  if (lightModeBtn) lightModeBtn.classList.add('active');
  
  // Reset sidebar theme buttons
  const sidebarButtons = document.querySelectorAll('.sidebar-theme .btn, .toggle-group .toggle-option');
  sidebarButtons.forEach(btn => btn.classList.remove('active'));
  const darkSidebarBtn = document.querySelector('.toggle-group .toggle-option[data-value="false"]');
  if (darkSidebarBtn) darkSidebarBtn.classList.add('active');
  
  // Reset sidebar icons buttons
  const sidebarIconButtons = document.querySelectorAll('.sidebar-icons .toggle-option');
  sidebarIconButtons.forEach(btn => btn.classList.remove('active'));
  const showIconsBtn = document.querySelector('.sidebar-icons .toggle-option[data-value="true"]');
  if (showIconsBtn) showIconsBtn.classList.add('active');
  
  // Reset caption buttons
  const captionButtons = document.querySelectorAll('.image-toggle-group .image-toggle');
  captionButtons.forEach(btn => btn.classList.remove('active'));
  const showCaptionBtn = document.querySelector('.image-toggle[data-value="true"]');
  if (showCaptionBtn) showCaptionBtn.classList.add('active');
  
  // Reset RTL buttons
  const rtlButtons = document.querySelectorAll('.pc-rtl .image-toggle');
  rtlButtons.forEach(btn => btn.classList.remove('active'));
  const ltrBtn = document.querySelector('.pc-rtl .image-toggle[data-value="false"]');
  if (ltrBtn) ltrBtn.classList.add('active');
  
  // Reset box width buttons
  const boxWidthButtons = document.querySelectorAll('.pc-box-width .image-toggle');
  boxWidthButtons.forEach(btn => btn.classList.remove('active'));
  const fullWidthBtn = document.querySelector('.pc-box-width .image-toggle[data-value="false"]');
  if (fullWidthBtn) fullWidthBtn.classList.add('active');
  
  // Reset all color buttons
  const allColorButtons = document.querySelectorAll('.color-swatch, .color-swatch-small');
  allColorButtons.forEach(btn => btn.classList.remove('active'));
  
  // Set default preset color (Ocean Blue)
  const defaultPresetBtn = document.querySelector('.preset-color .color-swatch[data-value="preset-1"]');
  if (defaultPresetBtn) defaultPresetBtn.classList.add('active');
  
  // Reset icon selectors
  const iconButtons = document.querySelectorAll('.icon-selector .icon-option');
  iconButtons.forEach(btn => btn.classList.remove('active'));
  const defaultMenuIcon = document.querySelector('.drp-menu-icon .icon-option[data-value="preset-1"]');
  if (defaultMenuIcon) defaultMenuIcon.classList.add('active');
  const defaultLinkIcon = document.querySelector('.drp-menu-link-icon .icon-option[data-value="preset-1"]');
  if (defaultLinkIcon) defaultLinkIcon.classList.add('active');
}

// =======================================================
// =======================================================