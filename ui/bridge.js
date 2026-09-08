'use strict';
if (typeof qt !== 'undefined' && typeof QWebChannel !== 'undefined') {
  new QWebChannel(qt.webChannelTransport, channel => {
    const backend = channel.objects.revolution;
    window.pywebview = { api: {
      snapshot: () => new Promise(resolve => backend.snapshot(value => resolve(JSON.parse(value)))),
      command: (action, payload={}) => new Promise(resolve => backend.command(action, JSON.stringify(payload), value => resolve(JSON.parse(value))))
    }};
    window.dispatchEvent(new Event('pywebviewready'));
  });
}
document.addEventListener('pointerdown', event => {
  if (event.button === 0 && event.target.closest('.pywebview-drag-region')) window.pywebview?.api.command('drag');
});
