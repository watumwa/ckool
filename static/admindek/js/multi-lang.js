/**
=========================================================================
=========================================================================
Template Name: Datta - Admin Template
Author: DashboardPack
Support: https://dashboardpack.com/
File: multi-lang.js
Description:  this file will contains snippet code
              about handling language change of the page.
=========================================================================
=========================================================================
*/
'use strict';

// Calculate base path for assets based on current page location
function getBasePath() {
  var pathname = window.location.pathname;
  
  // Get the directory path (remove filename)
  var lastSlash = pathname.lastIndexOf('/');
  var directory = pathname.substring(0, lastSlash + 1); // Keep the trailing slash
  
  // Count the depth from the root by counting forward slashes after the domain
  // This works regardless of subfolder deployment
  var pathAfterDomain = directory.replace(/^\/+/, ''); // Remove leading slashes
  
  // If we're at the root (no path after domain or just the subfolder)
  if (!pathAfterDomain || pathAfterDomain === '' || pathAfterDomain.match(/^[^\/]+\/$/)) {
    // Check if we're in a nested directory within the app
    var htmlFileName = pathname.substring(lastSlash + 1);
    if (htmlFileName && htmlFileName !== 'index.html') {
      // We're at root level of the app
      return './';
    }
    return './'; // Root level - use relative path
  }
  
  // Count the directory depth to determine how many levels up we need to go
  var depth = pathAfterDomain.split('/').filter(segment => segment.length > 0).length;
  
  // If the last segment is a filename, reduce depth by 1
  if (pathname.match(/\.html$/)) {
    depth = Math.max(0, depth - 1);
  }
  
  // Return the appropriate number of parent directory references
  if (depth === 0) {
    return './';
  }
  return '../'.repeat(depth);
}

const DEFAULT_OPTIONS = {
  flagList: {
    en: 'flag-united-kingdom',
    pl: 'flag-poland',
    ja: 'flag-japan',
    de: 'flag-germany'
  },
  preloadLngs: ['en'],
  fallbackLng: 'en',
  loadPath: getBasePath() + 'assets/json/locales/{{lng}}.json'
};

class Translator {
  constructor(options = {}) {
    this._options = { ...DEFAULT_OPTIONS, ...options };
    this._currentLng = this._options.fallbackLng;

    this._i18nextInit();
    this._listenToLangChange();
  }

  _i18nextInit() {
    i18next
      .use(i18nextHttpBackend)
      .init({
        fallbackLng: this._options.fallbackLng,
        preload: this._options.preloadLngs,
        backend: {
          loadPath: this._options.loadPath,
          stringify: JSON.stringify
        }
      })
      .then(() => {
        this._translateAll();
      });
  }

  _listenToLangChange = () => {
    const langSwitchers = document.querySelectorAll('[data-lng]');

    langSwitchers.forEach((langSwitcher) => {
      langSwitcher.addEventListener('click', () => {
        this._currentLng = langSwitcher.getAttribute('data-lng');

        i18next.changeLanguage(this._currentLng).then(() => {
          this._translateAll();
        });
      });
    });
  };

  _translateAll = () => {
    const elementsToTranslate = document.querySelectorAll('[data-i18n]');

    elementsToTranslate.forEach((el) => {
      const key = el.dataset.i18n;

      el.innerHTML = i18next.t(key);
    });
  };
}

new Translator();
