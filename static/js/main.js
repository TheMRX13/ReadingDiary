/* ============================================================
   Reading Diary – Main JavaScript
   ============================================================ */

// ── Theme ──────────────────────────────────────────────────
function toggleTheme() {
  const isDark = document.documentElement.dataset.bsTheme === 'dark';
  apiFetch('/api/settings', {
    method: 'POST',
    body: JSON.stringify({ dark_mode: isDark ? 'false' : 'true' })
  }).then(() => location.reload());
}

// ── Sidebar ────────────────────────────────────────────────
function toggleSidebar() {
  document.getElementById('sidebar').classList.toggle('open');
  document.getElementById('sidebarOverlay').classList.toggle('show');
}

function closeSidebar() {
  document.getElementById('sidebar').classList.remove('open');
  document.getElementById('sidebarOverlay').classList.remove('show');
}

// ── Toast ──────────────────────────────────────────────────
function showToast(message, type = 'success') {
  const container = document.getElementById('toastContainer');
  if (!container) return;
  const id = 'toast-' + Date.now();
  const iconMap = {
    success: 'fa-check-circle',
    danger:  'fa-exclamation-circle',
    warning: 'fa-exclamation-triangle',
    info:    'fa-info-circle',
  };
  const icon = iconMap[type] || 'fa-info-circle';
  container.insertAdjacentHTML('beforeend', `
    <div id="${id}" class="toast align-items-center border-0" role="alert"
         style="background:var(--bg-card);border:1px solid var(--border)!important;color:var(--text)">
      <div class="d-flex">
        <div class="toast-body d-flex align-items-center gap-2">
          <i class="fas ${icon}" style="color:var(--accent)"></i>
          ${message}
        </div>
        <button type="button" class="btn-close me-2 m-auto" data-bs-dismiss="toast"></button>
      </div>
    </div>
  `);
  const el = document.getElementById(id);
  new bootstrap.Toast(el, { delay: 3500 }).show();
  el.addEventListener('hidden.bs.toast', () => el.remove());
}

// ── API Fetch ──────────────────────────────────────────────
async function apiFetch(url, options = {}) {
  const resp = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const msg = data.error || `Fehler ${resp.status}`;
    showToast(msg, 'danger');
    throw new Error(msg);
  }
  return data;
}

// ── ISBN Lookup ────────────────────────────────────────────
async function lookupISBN(isbn, prefix) {
  if (!isbn) return;
  const btn = document.getElementById((prefix || '') + 'isbn_search_btn');
  if (btn) { btn.disabled = true; btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>'; }
  try {
    const data = await apiFetch('/api/isbn-lookup', {
      method: 'POST',
      body: JSON.stringify({ isbn }),
    });
    fillFormFromISBN(data, prefix || '');
    showToast('Buchdaten geladen!', 'success');
  } catch (_) {
    showToast('Keine Daten gefunden', 'warning');
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = '<i class="fas fa-search"></i> Suchen'; }
  }
}

function fillFormFromISBN(data, prefix) {
  const set = (id, val) => {
    const el = document.getElementById(prefix + id);
    if (el && val !== undefined && val !== null && val !== '') el.value = val;
  };
  set('title', data.title);
  set('author', data.author);
  set('publisher', data.publisher);
  set('genre', data.genre);
  set('pages', data.pages);
  set('release_date', data.release_date);
  set('isbn', data.isbn);
  set('cover_url', data.cover_url);
  set('series', data.series);

  // Upload-Zone mit Cover befüllen
  if (data.cover_url) {
    const preview = document.getElementById(prefix + 'cover_preview');
    const content = document.getElementById(prefix + 'cover_upload_content');
    if (preview)  { preview.src = data.cover_url; preview.style.display = 'block'; }
    if (content)  content.style.display = 'none';
  }

  // Switch to manual tab to show filled data
  const manualTab = document.getElementById(prefix + 'manual-tab');
  if (manualTab) bootstrap.Tab.getOrCreateInstance(manualTab).show();
}

// ── Cover Upload ────────────────────────────────────────────
async function handleCoverFile(event, prefix) {
  const file = event.target.files[0];
  if (file) uploadCoverFile(file, prefix);
}

function handleCoverDrop(event, prefix) {
  event.preventDefault();
  document.getElementById(prefix + 'cover_zone')?.classList.remove('drag-over');
  const file = event.dataTransfer.files[0];
  if (!file || !file.type.startsWith('image/')) {
    showToast('Bitte eine Bilddatei hochladen', 'warning');
    return;
  }
  uploadCoverFile(file, prefix);
}

async function uploadCoverFile(file, prefix) {
  const formData = new FormData();
  formData.append('file', file);
  try {
    const resp = await fetch('/api/upload-cover', { method: 'POST', body: formData });
    const data = await resp.json();
    if (!resp.ok) { showToast(data.error || 'Upload-Fehler', 'danger'); return; }
    const urlInput = document.getElementById(prefix + 'cover_url');
    const preview  = document.getElementById(prefix + 'cover_preview');
    const content  = document.getElementById(prefix + 'cover_upload_content');
    if (urlInput) urlInput.value = data.url;
    if (preview)  { preview.src = data.url; preview.style.display = 'block'; }
    if (content)  content.style.display = 'none';
    showToast('Cover hochgeladen!', 'success');
  } catch (_) {
    showToast('Fehler beim Hochladen', 'danger');
  }
}

// ── Form Validation ─────────────────────────────────────────
function validateBookForm(prefix, isWishlist) {
  const checks = [
    { id: prefix + 'title',        label: 'Titel' },
    { id: prefix + 'author',       label: 'Autor' },
    { id: prefix + 'genre',        label: 'Genre' },
    { id: prefix + 'pages',        label: 'Seiten', numeric: true },
    { id: prefix + 'publisher',    label: 'Verlag' },
    { id: prefix + 'release_date', label: 'Erscheinungsdatum' },
  ];
  if (!isWishlist) checks.push({ id: prefix + 'format', label: 'Format' });
  for (const c of checks) {
    const el = document.getElementById(c.id);
    if (!el) continue;
    const val = el.value.trim();
    const invalid = !val || (c.numeric && (isNaN(parseInt(val, 10)) || parseInt(val, 10) < 1));
    if (invalid) {
      showToast(`Pflichtfeld fehlt: ${c.label}`, 'warning');
      el.focus();
      el.classList.add('is-invalid');
      setTimeout(() => el.classList.remove('is-invalid'), 3000);
      return false;
    }
  }
  return true;
}

// ── Autocomplete ───────────────────────────────────────────
function setupAutocomplete(inputId, endpoint) {
  const input = document.getElementById(inputId);
  if (!input) return;

  let list = document.getElementById(inputId + '-ac');
  if (!list) {
    list = document.createElement('ul');
    list.id = inputId + '-ac';
    list.className = 'autocomplete-list';
    list.style.display = 'none';
    input.parentElement.style.position = 'relative';
    input.parentElement.appendChild(list);
  }

  let t;
  input.addEventListener('input', () => {
    clearTimeout(t);
    t = setTimeout(async () => {
      const q = input.value.trim();
      list.innerHTML = '';
      if (q.length < 1) { list.style.display = 'none'; return; }

      const items = await fetch(`${endpoint}?q=${encodeURIComponent(q)}`).then(r => r.json()).catch(() => []);

      const exact = items.find(i => i.name.toLowerCase() === q.toLowerCase());
      if (!exact) {
        const li = document.createElement('li');
        li.className = 'autocomplete-item autocomplete-new';
        li.innerHTML = `<i class="fas fa-plus-circle me-1"></i>Neu erstellen: „${q}"`;
        li.onclick = () => { input.value = q; list.style.display = 'none'; };
        list.appendChild(li);
      }

      items.forEach(item => {
        const li = document.createElement('li');
        li.className = 'autocomplete-item';
        li.textContent = item.name;
        li.onclick = () => { input.value = item.name; list.style.display = 'none'; };
        list.appendChild(li);
      });

      list.style.display = list.children.length ? 'block' : 'none';
    }, 220);
  });

  document.addEventListener('click', e => {
    if (!input.contains(e.target) && !list.contains(e.target)) list.style.display = 'none';
  });
}

// bindCoverPreview – nicht mehr verwendet (Upload-Zone ersetzt URL-Input)

// ── Star Rating ────────────────────────────────────────────
function initStarRating(containerId, inputId) {
  const c = document.getElementById(containerId);
  const inp = document.getElementById(inputId);
  if (!c || !inp) return;
  const btns = c.querySelectorAll('.star-btn');
  const update = val => {
    btns.forEach((b, i) => b.classList.toggle('active', i < val));
    inp.value = val;
  };
  btns.forEach((b, i) => {
    b.onclick = () => update(i + 1);
    b.onmouseenter = () => btns.forEach((bb, j) => bb.classList.toggle('hover', j <= i));
  });
  c.onmouseleave = () => btns.forEach(b => b.classList.remove('hover'));
  update(parseInt(inp.value) || 0);
}

// ── Custom confirm dialog ──────────────────────────────────
function showConfirm(opts) {
  // Accept plain string for backward compat
  if (typeof opts === 'string') opts = { message: opts };
  const {
    title       = 'Bestätigen',
    message     = '',
    confirmText = 'Bestätigen',
    cancelText  = 'Abbrechen',
    type        = 'danger',
  } = opts;

  const styles = {
    danger:  { bg: 'rgba(239,68,68,.18)',  color: '#f87171', icon: 'fa-triangle-exclamation', btn: '#dc2626' },
    warning: { bg: 'rgba(245,158,11,.18)', color: '#fbbf24', icon: 'fa-triangle-exclamation', btn: '#b45309' },
    primary: { bg: 'rgba(59,130,246,.18)', color: '#60a5fa', icon: 'fa-circle-info',           btn: '#2563eb' },
  };
  const s = styles[type] || styles.danger;

  const modal      = document.getElementById('confirmModal');
  const iconWrap   = document.getElementById('cm-icon-wrap');
  const icon       = document.getElementById('cm-icon');
  const titleEl    = document.getElementById('cm-title');
  const msgEl      = document.getElementById('cm-message');
  const confirmBtn = document.getElementById('cm-confirm');
  const cancelBtn  = document.getElementById('cm-cancel');

  iconWrap.style.background  = s.bg;
  iconWrap.style.color       = s.color;
  icon.className             = `fas ${s.icon}`;
  titleEl.textContent        = title;
  msgEl.textContent          = message;
  confirmBtn.textContent     = confirmText;
  confirmBtn.style.background = s.btn;
  cancelBtn.textContent      = cancelText;

  modal.style.display        = 'flex';
  document.body.style.overflow = 'hidden';

  return new Promise((resolve, reject) => {
    function cleanup(ok) {
      modal.style.display          = 'none';
      document.body.style.overflow = '';
      confirmBtn.removeEventListener('click',   onConfirm);
      cancelBtn.removeEventListener('click',    onCancel);
      document.removeEventListener('keydown',   onKey);
      modal.removeEventListener('click',        onBackdrop);
      ok ? resolve() : reject();
    }
    function onConfirm()  { cleanup(true);  }
    function onCancel()   { cleanup(false); }
    function onKey(e)     { if (e.key === 'Escape') cleanup(false); }
    function onBackdrop(e){ if (e.target === modal) cleanup(false); }

    confirmBtn.addEventListener('click',  onConfirm);
    cancelBtn.addEventListener('click',   onCancel);
    document.addEventListener('keydown',  onKey, { once: true });
    modal.addEventListener('click',       onBackdrop);
  });
}

// ── Confirm delete ─────────────────────────────────────────
async function confirmDelete(message, url, redirectUrl) {
  try { await showConfirm({ message, title: 'Löschen bestätigen', confirmText: 'Löschen', type: 'danger' }); }
  catch { return; }
  try {
    await apiFetch(url, { method: 'DELETE' });
    showToast('Erfolgreich gelöscht!', 'success');
    if (redirectUrl) setTimeout(() => { window.location.href = redirectUrl; }, 900);
    else             setTimeout(() => location.reload(), 900);
  } catch (_) {}
}

// ── ISBN Scanner (html5-qrcode) ────────────────────────────
let _scanner = null;

function startScanner(isbnInputId, prefix) {
  const wrap = document.getElementById('qr-reader');
  if (!wrap || typeof Html5Qrcode === 'undefined') {
    showToast('Scanner nicht verfügbar', 'warning');
    return;
  }
  stopScanner();
  _scanner = new Html5Qrcode('qr-reader');
  _scanner.start(
    { facingMode: 'environment' },
    { fps: 12, qrbox: { width: 240, height: 120 } },
    decoded => {
      const isbn = decoded.replace(/[^0-9Xx]/g, '');
      if (isbn.length >= 10) {
        const el = document.getElementById(isbnInputId);
        if (el) el.value = isbn;
        stopScanner();
        lookupISBN(isbn, prefix);
      }
    },
    () => {}
  ).catch(err => {
    showToast('Kamera konnte nicht gestartet werden: ' + err, 'danger');
  });
}

function stopScanner() {
  if (_scanner) {
    _scanner.stop().catch(() => {});
    _scanner = null;
  }
}

// Stop scanner when modal closes
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.modal').forEach(m => {
    m.addEventListener('hidden.bs.modal', () => stopScanner());
  });
});
