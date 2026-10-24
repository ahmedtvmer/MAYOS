(function () {
  'use strict';

  var config = window.MYOS_LANDING || {};
  var securePrefix = 'FlutterSecureStorage.';
  var languageKey = 'mayos.display_language';
  var firstTouchKey = 'mayos.first_touch';
  var analyticsQueue = [];
  var analyticsReady = false;

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
    document.title = language === 'ar' ? 'MYOS — تمرينك. مدروس.' : 'MYOS — Your training. Engineered.';
    document.querySelector('meta[name="description"]').content = language === 'ar'
      ? 'يبني ميوس برنامج تمرينك بالذكاء الاصطناعي حسب هدفك ووقتك والأدوات المتاحة لك. سجّل كل مجموعة وتابع قوتك وهي تزيد.'
      : 'MYOS uses AI to build your training program around your goal, schedule and equipment. Log every set and watch your strength grow.';
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
    document.querySelectorAll('[data-alt-' + language + ']').forEach(function (image) {
      image.alt = image.getAttribute('data-alt-' + language);
    });
  }

  function updateLanguageToggle(language) {
    var toggle = document.getElementById('language-toggle');
    toggle.textContent = language === 'ar' ? 'English' : 'العربية';
    toggle.setAttribute('aria-label', language === 'ar' ? 'Change language to English' : 'تغيير اللغة إلى العربية');
  }

  function setLanguage(language) {
    document.documentElement.lang = language;
    document.documentElement.dir = language === 'ar' ? 'rtl' : 'ltr';
    document.querySelector('nav').setAttribute('aria-label', language === 'ar' ? 'التنقل الرئيسي' : 'Main navigation');
    updatePageMetadata(language);
    updateCopy(language);
    updateLanguageToggle(language);
    try { localStorage.setItem(languageKey, language); } catch (_error) { /* Choice remains active until navigation. */ }
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
  var language = selectedLanguage();
  setLanguage(language);
  document.getElementById('language-toggle').addEventListener('click', function () {
    language = language === 'ar' ? 'en' : 'ar';
    setLanguage(language);
  });
  document.addEventListener('click', function (event) {
    var target = event.target.closest('[data-track]');
    if (target) track(target.dataset.track, {});
  });
  requestAnimationFrame(function () {
    requestAnimationFrame(loadAnalytics);
  });
}());
