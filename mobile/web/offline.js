let language;
try {
  language = localStorage.getItem('mayos.display_language');
} catch (_) {
  // Browser language remains available when storage is blocked.
}

const arabic =
  language === 'ar' ||
  (!language && navigator.language.toLowerCase().startsWith('ar'));

if (arabic) {
  document.documentElement.lang = 'ar';
  document.documentElement.dir = 'rtl';
  document.getElementById('message').textContent =
    'يحتاج MYOS إلى اتصال بالإنترنت. اتصل بالشبكة وحاول مرة أخرى.';
  document.getElementById('retry').textContent = 'إعادة المحاولة';
}

document.getElementById('retry').addEventListener('click', () => location.reload());
