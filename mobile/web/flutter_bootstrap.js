{{flutter_js}}
{{flutter_build_config}}

window.addEventListener('flutter-first-frame', () => {
  const loadingScreen = document.getElementById('mayos-loading');
  if (loadingScreen === null) return;

  loadingScreen.classList.add('is-hidden');
  window.setTimeout(() => loadingScreen.remove(), 320);
}, { once: true });

_flutter.loader.load();
