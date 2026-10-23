module.exports = {
  globDirectory: 'build/web/',
  globPatterns: [
    'flutter_bootstrap.js',
    'main.dart.js',
    'manifest.json',
    'favicon.png',
    'apple-touch-icon.png',
    'myos-icon-*.png',
    'myos-loading-wallpaper.jpg',
    'myos-lockup-white.png',
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
    'index.html',
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
  // Documents are fetched live; the precached fallback handles timeouts/errors.
  runtimeCaching: [
    {
      urlPattern: ({request}) => request.mode === 'navigate',
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
        }],
        precacheFallback: {fallbackURL: 'offline.html'},
      },
    },
  ],
};
