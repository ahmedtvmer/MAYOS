(function () {
  'use strict';

  var config = window.MYOS_LANDING || {};
  var securePrefix = 'FlutterSecureStorage.';
  var languageKey = 'mayos.display_language';
  var firstTouchKey = 'mayos.first_touch';
  var analyticsQueue = [];
  var analyticsReady = false;

  function bytesFromBase64(base64Text) {
    var binary = atob(base64Text);
    var bytes = new Uint8Array(binary.length);
    for (var i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
    return bytes;
  }

  function captureFirstTouch() {
    try {
      if (localStorage.getItem(firstTouchKey) !== null) return;
      var params = new URLSearchParams(location.search);
      var touch = {};
      ['utm_source', 'utm_medium', 'utm_campaign'].forEach(function (key) {
        if (params.has(key)) touch[key] = params.get(key);
      });
      var referrer = document.referrer ? new URL(document.referrer) : null;
      if (referrer && referrer.hostname && referrer.hostname.toLowerCase() !== location.hostname.toLowerCase()) {
        touch.referrer_host = referrer.hostname.toLowerCase();
      }
      if (Object.keys(touch).length) localStorage.setItem(firstTouchKey, JSON.stringify(touch));
    } catch (_error) { /* Storage and malformed referrers are best effort. */ }
  }

  function skipSignedIn() {
    try {
      if (Object.prototype.hasOwnProperty.call(localStorage, securePrefix + 'mayos.access_token')) {
        location.replace('/app/');
        return true;
      }
    } catch (_error) { /* A blocked storage API leaves the public page usable. */ }
    return false;
  }

  function readTheme() {
    try {
      var encryptedMode = localStorage.getItem(securePrefix + 'settings.theme_mode');
      var base64Key = localStorage.getItem('FlutterSecureStorage');
      if (!encryptedMode || !base64Key) return Promise.resolve(null);
      var encodedParts = encryptedMode.split('.');
      if (encodedParts.length !== 2) return Promise.resolve(null);
      var iv = bytesFromBase64(encodedParts[0]);
      var cipher = bytesFromBase64(encodedParts[1]);
      return crypto.subtle.importKey('raw', bytesFromBase64(base64Key), {name: 'AES-GCM'}, false, ['decrypt'])
        .then(function (cryptoKey) {
          return crypto.subtle.decrypt({name: 'AES-GCM', iv: iv}, cryptoKey, cipher);
        }).then(function (decryptedBytes) {
          var themeMode = new TextDecoder().decode(decryptedBytes);
          return ['light', 'dark', 'system'].indexOf(themeMode) >= 0 ? themeMode : null;
        }).catch(function () {
          return null; // The app falls back to ThemeMode.system for unreadable choices.
        });
    } catch (_error) {
      return Promise.resolve(null); // A blocked secure store uses the same system fallback.
    }
  }

  function applyTheme() {
    readTheme().then(function (mode) {
      if (mode === 'light' || mode === 'dark') document.documentElement.dataset.theme = mode;
      else document.documentElement.removeAttribute('data-theme');
      var dark = mode === 'dark' || (mode !== 'light' && matchMedia('(prefers-color-scheme: dark)').matches);
      var themeColor = document.querySelector('meta[name="theme-color"]:not([media])');
      var systemThemeColor = document.querySelector('meta[name="theme-color"][media]');
      if (themeColor) themeColor.content = dark ? '#0A1422' : '#F6F5F2';
      if (systemThemeColor) systemThemeColor.media = mode === 'system' || mode === null
        ? '(prefers-color-scheme: dark)' : 'not all';
    });
  }

  function selectedLanguage() {
    try {
      var storedLanguage = localStorage.getItem(languageKey);
      if (storedLanguage === 'ar' || storedLanguage === 'en') return storedLanguage;
    } catch (_error) { /* Continue with browser preference. */ }
    var browser = (navigator.languages && navigator.languages[0]) || navigator.language || '';
    if (/^en/i.test(browser)) return 'en';
    if (/^ar/i.test(browser)) return 'ar';
    return 'ar';
  }

  function updatePageMetadata(language) {
    document.title = language === 'ar' ? 'MYOS — تقدّمٌ مدروس.' : 'MYOS — Progress, Engineered.';
    document.querySelector('meta[name="description"]').content = language === 'ar'
      ? 'برامج تمرين، وتسجيل لكل مجموعة، وتدريب، في تطبيق واحد. ابدأ مجانًا على الويب.'
      : 'Training programs, set-by-set logging and coaching, in one app. Free to start on the web.';
    document.querySelector('meta[property="og:description"]').content = language === 'ar'
      ? 'برامج تمرين، وتسجيل لكل مجموعة، وتدريب، في تطبيق واحد.'
      : 'Training programs, set-by-set logging and coaching, in one app.';
  }

  function updateCopy(language) {
    document.querySelectorAll('[data-copy]').forEach(function (element) {
      var copyText = element.getAttribute('data-' + language);
      if (copyText !== null) {
        if (element.dataset.rich === 'true') element.innerHTML = copyText;
        else if (element.querySelector('svg')) {
          Array.prototype.slice.call(element.childNodes).forEach(function (child) {
            if (child.nodeType === Node.TEXT_NODE) child.remove();
          });
          element.appendChild(document.createTextNode(copyText));
        } else element.textContent = copyText;
      }
    });
  }

  function updateLanguageBadges(language) {
    document.querySelectorAll('[data-badge]').forEach(function (image) {
      image.src = '/' + (image.dataset.badge === 'google_play' ? 'google-play-' + language + '.png' : 'app-store-en.svg');
    });
    var toggle = document.getElementById('language-toggle');
    toggle.textContent = language === 'ar' ? 'English' : 'العربية';
    toggle.setAttribute('aria-label', language === 'ar' ? 'Change language to English' : 'تغيير اللغة إلى العربية');
    document.querySelectorAll('[data-store-badge]').forEach(function (badge) {
      var platform = badge.dataset.storeBadge;
      badge.setAttribute('aria-label', (platform === 'google_play' ? 'Google Play' : 'App Store') + ', ' +
        (language === 'ar' ? 'قريبًا' : 'Coming soon'));
    });
  }

  function updateContactLinks(language) {
    document.querySelectorAll('[data-contact="instagram"]').forEach(function (link) {
      if (link.closest('.coach-actions')) {
        link.textContent = language === 'ar' ? 'راسلنا على إنستغرام' : 'Message us on Instagram';
      }
    });
  }

  function setLanguage(language) {
    document.documentElement.lang = language;
    document.documentElement.dir = language === 'ar' ? 'rtl' : 'ltr';
    document.querySelector('nav').setAttribute('aria-label', language === 'ar' ? 'التنقل الرئيسي' : 'Main navigation');
    updatePageMetadata(language);
    updateCopy(language);
    updateLanguageBadges(language);
    updateContactLinks(language);
    try { localStorage.setItem(languageKey, language); } catch (_error) { /* Choice remains active until navigation. */ }
  }

  function configureBadges() {
    document.querySelectorAll('[data-store-badge]').forEach(function (badge) {
      var storeName = badge.dataset.storeBadge;
      var destination = storeName === 'google_play' ? config.googlePlayUrl : config.appStoreUrl;
      if (!destination) return;
      var link = document.createElement('a');
      link.className = 'badge-wrap';
      link.href = destination;
      link.dataset.track = 'landing_store_badge';
      link.dataset.store = storeName;
      link.setAttribute('aria-label', storeName === 'google_play' ? 'Google Play' : 'App Store');
      while (badge.firstChild) link.appendChild(badge.firstChild);
      var mark = link.querySelector('.badge-mark');
      if (mark) mark.remove();
      badge.replaceWith(link);
    });
  }

  function loadAnalytics() {
    if (!config.posthogKey) return;
    var script = document.createElement('script');
    script.src = '/app/posthog_init.js';
    script.async = true;
    script.onload = function () {
      window.myosInitializePosthog(config.posthogKey, '{}').then(function () {
        analyticsReady = true;
        flushAnalyticsQueue();
      }).catch(function (error) {
        console.error('MYOS analytics could not initialize.', error);
      });
    };
    document.head.appendChild(script);
  }

  function flushAnalyticsQueue() {
    if (!analyticsReady || !window.myosCapturePosthog) return;
    while (analyticsQueue.length) {
      var queuedEvent = analyticsQueue[0];
      try {
        window.myosCapturePosthog(queuedEvent.event, JSON.stringify(queuedEvent.properties));
        analyticsQueue.shift();
      } catch (error) {
        console.error('MYOS analytics event remains queued after capture failed.', error);
        return;
      }
    }
  }

  function track(event, properties) {
    if (!config.posthogKey) return;
    analyticsQueue.push({event: event, properties: properties || {}});
    flushAnalyticsQueue();
  }

  if (skipSignedIn()) return;
  captureFirstTouch();
  applyTheme();
  configureBadges();
  var language = selectedLanguage();
  setLanguage(language);
  document.getElementById('language-toggle').addEventListener('click', function () {
    language = language === 'ar' ? 'en' : 'ar';
    setLanguage(language);
  });
  document.addEventListener('click', function (event) {
    var target = event.target.closest('[data-track]');
    if (target) {
      var store = target.dataset.store || target.dataset.storeBadge;
      track(target.dataset.track, store ? {store: store} : {});
    }
  });
  document.addEventListener('keydown', function (event) {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    var badge = event.target.closest('[data-store-badge]');
    if (!badge) return;
    event.preventDefault();
    track(badge.dataset.track, {store: badge.dataset.storeBadge});
  });
  requestAnimationFrame(function () {
    requestAnimationFrame(loadAnalytics);
  });
}());
