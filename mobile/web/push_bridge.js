/* Permission is requested only by MAYOS_PUSH_ENABLE, called from a Turn on tap. */
(() => {
  const supported = () => 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
  const deviceId = () => {
    let id = localStorage.getItem('mayos.push.device');
    if (!id) {
      id = crypto.randomUUID();
      localStorage.setItem('mayos.push.device', id);
    }
    return id;
  };
  const ios = () => /iPad|iPhone|iPod/.test(navigator.userAgent) ||
    (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  const installed = () => window.matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
  window.MAYOS_PUSH_STATE = () => JSON.stringify({
    supported: supported(), permission: supported() ? Notification.permission : 'unsupported',
    device_id: deviceId(), timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC',
    needs_install: ios() && !installed(),
  });
  const registration = async () => {
    // ready can stay pending indefinitely on unsupported or unregistered pages.
    const ready = navigator.serviceWorker.ready;
    let timer;
    try {
      return await Promise.race([ready, new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error('worker-unavailable')), 15000);
      })]);
    } finally { clearTimeout(timer); }
  };
  const encodeKey = key => Uint8Array.from(atob(key.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - key.length % 4) % 4)), c => c.charCodeAt(0));
  const subscribe = async key => {
    const worker = await registration();
    const subscription = await worker.pushManager.getSubscription() ||
      await worker.pushManager.subscribe({userVisibleOnly: true, applicationServerKey: encodeKey(key)});
    const json = subscription.toJSON();
    return JSON.stringify({device_id: deviceId(), endpoint: json.endpoint, keys: json.keys});
  };
  window.MAYOS_PUSH_ENABLE = async key => {
    if (!supported() || (ios() && !installed())) throw new Error('unsupported');
    // Start synchronously while the originating button still has user activation.
    const permission = await Notification.requestPermission();
    if (permission !== 'granted') return JSON.stringify({permission});
    return subscribe(key);
  };
  window.MAYOS_PUSH_REFRESH = async key => {
    if (!supported() || Notification.permission !== 'granted') return null;
    return subscribe(key);
  };
  window.MAYOS_PUSH_DISABLE = async () => {
    if (!supported()) return;
    const worker = await navigator.serviceWorker.getRegistration();
    if (!worker) return;
    const subscription = await worker.pushManager.getSubscription();
    if (subscription) await subscription.unsubscribe();
  };
})();
