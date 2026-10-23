// Small host API for Dart: window.MYOS_UPDATE_WAITING (boolean),
// window.MYOS_APPLY_UPDATE() (activate then reload once on controller change).
// Install bridge additions for #456 belong in the delimited section below.
(() => {
  let waiting = false;
  let applying = false;
  let registration = null;
  const watchedWaitingWorkers = new WeakSet();
  const notify = () => window.dispatchEvent(new Event('myos-update-waiting'));
  const setWaiting = value => {
    if (waiting === value) return;
    waiting = value;
    notify();
  };
  const reconcile = () => setWaiting(Boolean(registration?.waiting));
  const watchWaitingWorker = () => {
    const worker = registration?.waiting;
    if (!worker || watchedWaitingWorkers.has(worker)) return;
    watchedWaitingWorkers.add(worker);
    worker.addEventListener('statechange', () => {
      if (worker.state !== 'installed') reconcile();
    });
  };
  const apply = async () => {
    if (applying || !navigator.serviceWorker) return;
    registration = registration || await navigator.serviceWorker.getRegistration();
    const waitingWorker = registration?.waiting;
    reconcile();
    if (!waitingWorker) return;
    applying = true;
    navigator.serviceWorker.addEventListener('controllerchange', () => {
      applying = false;
      location.reload();
    }, {once: true});
    waitingWorker.postMessage({type: 'SKIP_WAITING'});
  };
  Object.defineProperty(window, 'MYOS_UPDATE_WAITING', {get: () => waiting});
  window.MYOS_APPLY_UPDATE = apply;
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.addEventListener('controllerchange', () => {
      reconcile();
      watchWaitingWorker();
    });
    navigator.serviceWorker.register('service-worker.js', {scope: '/app/'}).then(value => {
      registration = value;
      reconcile();
      watchWaitingWorker();
      const watchInstallingWorker = () => {
        const worker = registration.installing;
        worker?.addEventListener('statechange', () => {
          if (worker.state === 'installed' && navigator.serviceWorker.controller) {
            reconcile();
            watchWaitingWorker();
          }
        });
      };
      // An update may already be installing when registration resolves.
      watchInstallingWorker();
      registration.addEventListener('updatefound', watchInstallingWorker);
    }).catch(() => {});
  }
})();
// --- Install bridge reserved for #456 ---
(() => {
  let installPrompt = null;
  let installed = false;
  const notify = () => window.dispatchEvent(new Event('myos-install-state'));
  Object.defineProperty(window, 'MYOS_INSTALL_PROMPT_AVAILABLE', {
    get: () => installPrompt !== null,
  });
  Object.defineProperty(window, 'MYOS_APP_INSTALLED', {
    get: () => installed,
  });
  window.MYOS_CONSUME_APP_INSTALLED = () => {
    const wasInstalled = installed;
    installed = false;
    return wasInstalled;
  };
  window.MYOS_PROMPT_INSTALL = async () => {
    if (!installPrompt) return 'unavailable';
    const prompt = installPrompt;
    installPrompt = null;
    notify();
    await prompt.prompt();
    const result = await prompt.userChoice;
    return result?.outcome === 'accepted' ? 'accepted' : 'dismissed';
  };
  window.addEventListener('beforeinstallprompt', event => {
    event.preventDefault();
    installPrompt = event;
    notify();
  });
  window.addEventListener('appinstalled', () => {
    installed = true;
    installPrompt = null;
    notify();
    window.dispatchEvent(new Event('myos-app-installed'));
  });
})();
