(function () {
  function isStandalone() {
    return Boolean(navigator.standalone) ||
      window.matchMedia('(display-mode: standalone)').matches;
  }

  function viewportContentWithSafeArea(content) {
    if (/(^|,)\s*viewport-fit\s*=\s*[^,]+/i.test(content)) {
      return content.replace(
        /(^|,)\s*viewport-fit\s*=\s*[^,]+/i,
        '$1 viewport-fit=cover'
      );
    }
    return content + ', viewport-fit=cover';
  }

  function preserveSafeAreaViewport() {
    if (!isStandalone()) return;
    document.querySelectorAll('meta[name="viewport"]').forEach(function (meta) {
      var content = meta.getAttribute('content') || '';
      var safeAreaContent = viewportContentWithSafeArea(content);
      if (content !== safeAreaContent) {
        meta.setAttribute('content', safeAreaContent);
      }
    });
  }

  preserveSafeAreaViewport();
  new MutationObserver(preserveSafeAreaViewport).observe(document.head, {
    attributes: true,
    attributeFilter: ['content', 'name'],
    childList: true,
    subtree: true
  });
})();
