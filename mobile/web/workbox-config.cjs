module.exports = {
  globDirectory: 'build/web/',
  globPatterns: [
    'index.html',
    'flutter_bootstrap.js',
    'main.dart.js',
    'manifest.json',
    'favicon.png',
    'apple-touch-icon.png',
    'mayos-icon-*.png',
    'mayos-loading-wallpaper.jpg',
    'mayos-lockup-white.png',
    'safe_area.js',
    'posthog_init.js',
    'pwa_bridge.js',
    'offline.html',
    'offline.js',
    'canvaskit/canvaskit.js',
    'canvaskit/canvaskit.wasm',
    'canvaskit/chromium/canvaskit.js',
    'canvaskit/chromium/canvaskit.wasm',
    'assets/AssetManifest.bin.json',
    'assets/FontManifest.json',
    'assets/**/*.{ttf,otf,woff,woff2,png,jpg,jpeg,webp,svg}',
  ],
  globIgnores: [
    'service-worker.js',
    'workbox-*.js',
    '**/*.symbols',
    'assets/NOTICES',
    'canvaskit/skwasm*',
    'canvaskit/wimp*',
    'canvaskit/webparagraph/**',
  ],
  swDest: 'build/web/service-worker.js',
  maximumFileSizeToCacheInBytes: 20 * 1024 * 1024,
  clientsClaim: true,
  skipWaiting: false,
  cleanupOutdatedCaches: true,
  // Keep navigations live-first while allowing a closed app to cold-start offline.
  runtimeCaching: [
    {
      urlPattern: ({url, request}) =>
        request.mode === 'navigate' &&
        url.origin === self.location.origin &&
        url.pathname.startsWith('/app/'),
      handler: 'NetworkOnly',
      options: {
        // Workbox 7.3's generateSW validator rejects networkTimeoutSeconds for
        // NetworkOnly, so abort the live fetch after the same 10-second limit.
        // Workbox hands later hooks a cloned request, so the timer lives in the
        // per-request plugin state rather than being keyed by the request.
        plugins: [{
          requestWillFetch: async ({request, state}) => {
            const controller = new AbortController();
            state.navigationTimeout = setTimeout(() => controller.abort(), 10000);
            return new Request(request, {signal: controller.signal});
          },
          fetchDidSucceed: async ({response, state}) => {
            clearTimeout(state.navigationTimeout);
            return response;
          },
          fetchDidFail: async ({state}) => {
            clearTimeout(state.navigationTimeout);
          },
          handlerDidError: async () => {
            const precacheName = (await caches.keys()).find(name => name.includes('precache'));
            if (!precacheName) return;

            const precache = await caches.open(precacheName);
            const appDocumentUrl = new URL('index.html', self.registration.scope);
            const appDocument = await precache.match(appDocumentUrl.href, {ignoreSearch: true});
            if (appDocument) return appDocument;

            const offlinePageUrl = new URL('offline.html', self.registration.scope);
            return precache.match(offlinePageUrl.href, {ignoreSearch: true});
          },
        }],
      },
    },
  ],
};
