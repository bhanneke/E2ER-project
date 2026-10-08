// What every dashboard page shares: calls to the e2er server with plain error messages,
// and a notice when a button or the live panel cannot reach e2er (htmx), so nothing fails silently.
(function () {
  const UNREACHABLE = 'e2er is not reachable. Is the terminal window where e2er runs still open? Start it again with: e2er';

  // The sentence to show for a failed response: the server's own words when it sent some.
  function messageFor(status, text) {
    let detail = '';
    try { const d = JSON.parse(text); detail = typeof d.detail === 'string' ? d.detail : ''; } catch (e) { /* not JSON */ }
    if (!detail && text && /class="[^"]*error-sentence[^"]*">([^<]*)</.test(text)) detail = RegExp.$1;
    if (detail) return detail;
    if (status === 401 || status === 403) return 'This browser tab is not signed in to e2er. Run e2er in a terminal: it opens the dashboard signed in.';
    if (status === 404) return 'e2er could not find this study or file. Reload the page.';
    if (status >= 500) return 'Something went wrong inside e2er. The terminal window where e2er runs shows the details.';
    return 'That did not work (' + status + '). Reload the page and try again.';
  }

  async function call(method, url, body) {
    let r;
    try {
      r = await fetch(url, { method, credentials: 'same-origin', headers: { 'content-type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) });
    } catch (e) { throw new Error(UNREACHABLE); }
    const text = await r.text();
    if (!r.ok) throw new Error(messageFor(r.status, text));
    try { return JSON.parse(text); } catch (e) { return {}; }
  }

  function notice(text) {
    let box = document.getElementById('e2er-notice');
    if (!box) {
      box = document.createElement('div');
      box.id = 'e2er-notice';
      box.className = 'notice';
      box.setAttribute('role', 'alert');
      box.innerHTML = '<span class="notice-text"></span><button type="button" class="btn-ghost notice-close">Close</button>';
      box.querySelector('.notice-close').addEventListener('click', () => { box.hidden = true; });
      document.body.appendChild(box);
    }
    box.querySelector('.notice-text').textContent = text;
    box.hidden = false;
  }
  function clearNotice() { const box = document.getElementById('e2er-notice'); if (box && box.dataset.kind === 'poll') box.hidden = true; }

  document.addEventListener('htmx:responseError', (ev) => {
    const xhr = ev.detail.xhr;
    notice(messageFor(xhr.status, xhr.responseText));
  });
  document.addEventListener('htmx:sendError', () => {
    notice(UNREACHABLE);
    const box = document.getElementById('e2er-notice'); if (box) box.dataset.kind = 'poll';
  });
  document.addEventListener('htmx:afterRequest', (ev) => { if (ev.detail.successful) clearNotice(); });

  window.e2er = { call, notice, messageFor, UNREACHABLE };
})();
