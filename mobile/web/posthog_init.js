(function (window, document) {
  var posthog = window.posthog || [];
  var initPromise;

  if (!posthog.__SV) {
    window.posthog = posthog;
    posthog._i = [];
    posthog.init = function (projectToken, options, instanceName) {
      function stub(target, method) {
        var parts = method.split('.');
        if (parts.length === 2) {
          target = target[parts[0]];
          method = parts[1];
        }
        target[method] = function () {
          target.push([method].concat(Array.prototype.slice.call(arguments)));
        };
      }

      var script = document.createElement('script');
      script.type = 'text/javascript';
      script.crossOrigin = 'anonymous';
      script.async = true;
      script.src = options.api_host.replace('.i.posthog.com', '-assets.i.posthog.com') + '/static/array.js';
      script.onerror = function () {
        window.mayosPosthogFailed();
      };
      var firstScript = document.getElementsByTagName('script')[0];
      firstScript.parentNode.insertBefore(script, firstScript);

      var instance = posthog;
      if (instanceName) instance = posthog[instanceName] = [];
      instance.people = instance.people || [];
      instance.toString = function (loaded) {
        return 'posthog' + (instanceName ? '.' + instanceName : '') + (loaded ? '' : ' (stub)');
      };
      instance.people.toString = function () {
        return instance.toString(1) + '.people (stub)';
      };
      var methods = 'capture identify register register_once unregister unregister_all reset flush get_distinct_id get_session_id onFeatureFlags isFeatureEnabled'.split(' ');
      for (var index = 0; index < methods.length; index += 1) stub(instance, methods[index]);
      posthog._i.push([projectToken, options, instanceName || 'posthog']);
    };
    posthog.__SV = 1;
  }

  window.mayosInitializePosthog = function (clientKey, commonDimensionsJson) {
    if (initPromise) return initPromise;
    initPromise = new Promise(function (resolve, reject) {
      window.mayosPosthogLoaded = resolve;
      window.mayosPosthogFailed = function () {
        reject(new Error('PostHog web SDK failed to load.'));
      };
      posthog.init(clientKey, {
        api_host: 'https://eu.i.posthog.com',
        autocapture: false,
        capture_pageview: false,
        capture_pageleave: false,
        ip: false,
        capture_heatmaps: false,
        capture_dead_clicks: false,
        capture_exceptions: false,
        capture_performance: false,
        disable_surveys: true,
        rageclick: false,
        disable_session_recording: true,
        advanced_disable_feature_flags_on_first_load: true,
        person_profiles: 'identified_only',
        loaded: function (instance) {
          instance.register(JSON.parse(commonDimensionsJson));
          instance.register('$geoip_disable', true);
          window.mayosPosthogLoaded();
        },
      });
    });
    return initPromise;
  };

  window.mayosIdentifyPosthog = function (accountId, role, commonDimensionsJson) {
    window.posthog.register(JSON.parse(commonDimensionsJson));
    window.posthog.register('role', role);
    window.posthog.identify(accountId);
  };
  window.mayosCapturePosthog = function (eventName, propertiesJson) {
    window.posthog.capture(eventName, JSON.parse(propertiesJson));
  };
  window.mayosResetPosthog = function () {
    window.posthog.reset();
  };
})(window, document);
