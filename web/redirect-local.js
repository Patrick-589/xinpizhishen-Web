if (window.location.protocol === 'file:') {
  window.location.replace(`http://127.0.0.1:8767/index.html${window.location.hash || '#tasks'}`);
}
