{{flutter_js}}
{{flutter_build_config}}

window.addEventListener('flutter-first-frame', () => {
  const loadingScreen = document.getElementById('mayos-loading');
  if (loadingScreen === null) return;

  const removeLoadingScreen = () => {
    loadingScreen.removeEventListener('transitionend', onTransitionEnd);
    loadingScreen.remove();
  };
  const onTransitionEnd = (event) => {
    if (event.target === loadingScreen && event.propertyName === 'opacity') {
      removeLoadingScreen();
    }
  };
  const toMilliseconds = (value) => {
    const number = Number.parseFloat(value);
    return value.trim().endsWith('ms') ? number : number * 1000;
  };
  const style = window.getComputedStyle(loadingScreen);
  const duration = Math.max(
    ...style.transitionDuration.split(',').map(toMilliseconds),
  );
  const delay = Math.max(...style.transitionDelay.split(',').map(toMilliseconds));

  loadingScreen.addEventListener('transitionend', onTransitionEnd);
  loadingScreen.classList.add('is-hidden');
  window.setTimeout(removeLoadingScreen, duration + delay + 50);
}, { once: true });

_flutter.loader.load();
