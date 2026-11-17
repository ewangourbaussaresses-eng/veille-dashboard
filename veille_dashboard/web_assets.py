"""HTML de veille-dashboard (séparé pour rester lisible)."""

INDEX_HTML = """<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Veille du jour</title>
<style>
  :root { --bg:#0f1115; --panel:#171a21; --line:#262b36; --text:#e6e8ee;
          --muted:#98a0b3; --accent:#6ea8fe; --ok:#3fb950; }
  * { box-sizing:border-box; }
  body { margin:0; font:15px/1.6 -apple-system,"Segoe UI",Roboto,sans-serif;
         background:var(--bg); color:var(--text); }
  header { max-width:860px; margin:0 auto; padding:28px 24px 6px; }
  h1 { font-size:25px; margin:0 0 4px; letter-spacing:-.02em; }
  .sub { color:var(--muted); font-size:14px; }
  main { max-width:860px; margin:0 auto; padding:10px 24px 64px; }
  .bar { display:flex; gap:10px; flex-wrap:wrap; align-items:center; margin:16px 0 22px; }
  button { background:var(--accent); color:#07101f; border:0; border-radius:8px;
           padding:9px 16px; font-weight:600; cursor:pointer; }
  button.ghost { background:transparent; color:var(--text); border:1px solid var(--line); }
  button:disabled { opacity:.5; cursor:progress; }
  .badge { font-size:12px; color:var(--muted); border:1px solid var(--line);
           border-radius:999px; padding:3px 10px; }
  article { background:var(--panel); border:1px solid var(--line); border-radius:12px;
            padding:16px 18px; margin-bottom:12px; }
  article h2 { font-size:16.5px; margin:0 0 6px; letter-spacing:-.01em; }
  article h2 a { color:var(--text); text-decoration:none; }
  article h2 a:hover { color:var(--accent); }
  .summary { color:#cfd4e0; }
  .why { color:var(--muted); font-size:13.5px; border-left:2px solid var(--accent);
         padding-left:10px; margin-top:8px; }
  .meta { color:var(--muted); font-size:12px; margin-top:8px; }
  .intro { color:var(--muted); margin-bottom:18px; }
  .hist { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:18px; }
  .hist button { background:transparent; color:var(--muted); border:1px solid var(--line);
                 font-weight:500; font-size:12.5px; padding:5px 10px; }
  .err { color:#f85149; }
  footer { color:var(--muted); font-size:12px; text-align:center; padding:24px; }
</style>
</head>
<body>
<header>
  <h1>Veille du jour</h1>
  <div class="sub">Les 5 actualités qui comptent, résumées pour votre profil. Flux RSS,
    tendances GitHub et Reddit — filtrés, dédupliqués, résumés.</div>
</header>
<main>
  <div class="bar">
    <button id="run">Générer le digest</button>
    <button class="ghost" id="reload">Historique</button>
    <span class="badge" id="engine">moteur : —</span>
  </div>
  <div class="hist" id="hist"></div>
  <div id="status" class="sub"></div>
  <div id="content"></div>
</main>
<footer>veille-dashboard · auto-hébergé, aucune donnée envoyée à un tiers sans votre clé</footer>
<script>
const runBtn = document.getElementById('run');
const statusEl = document.getElementById('status');
const contentEl = document.getElementById('content');
const engineEl = document.getElementById('engine');
const histEl = document.getElementById('hist');

fetch('/api/status').then(r => r.json()).then(s => {
  engineEl.textContent = 'moteur : ' + (s.available ? s.provider : 'règles locales');
  if (s.digests) loadHistory();
});

function esc(v) {
  return String(v ?? '').replace(/[&<>"]/g,
    c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
}

function render(digest) {
  contentEl.innerHTML = '';
  if (digest.intro) {
    const intro = document.createElement('p');
    intro.className = 'intro';
    intro.textContent = digest.intro;
    contentEl.appendChild(intro);
  }
  digest.articles.forEach((a, i) => {
    const el = document.createElement('article');
    el.innerHTML =
      '<h2><a href="' + esc(a.url) + '" target="_blank" rel="noopener">' +
        (i + 1) + '. ' + esc(a.title) + '</a></h2>' +
      (a.summary ? '<div class="summary">' + esc(a.summary) + '</div>' : '') +
      (a.why ? '<div class="why">' + esc(a.why) + '</div>' : '') +
      '<div class="meta">' + esc(a.source) +
        (a.published ? ' · ' + esc(a.published.slice(0, 10)) : '') +
        ' · score ' + esc(a.score) + '</div>';
    contentEl.appendChild(el);
  });
  if (!digest.articles.length) {
    contentEl.innerHTML = '<p class="sub">Aucune actualité retenue — vérifiez les flux ' +
                          'dans config.json.</p>';
  }
}

runBtn.addEventListener('click', async () => {
  runBtn.disabled = true;
  statusEl.textContent = 'collecte des flux et résumé…';
  try {
    const res = await fetch('/api/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({})
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'erreur serveur');
    render(data.digest);
    statusEl.textContent = data.selected + ' retenue(s) sur ' +
                           data.collected + ' collectée(s)';
    loadHistory();
  } catch (err) {
    statusEl.innerHTML = '<span class="err">' + esc(err.message) + '</span>';
  } finally {
    runBtn.disabled = false;
  }
});

document.getElementById('reload').addEventListener('click', loadHistory);

async function loadHistory() {
  const res = await fetch('/api/digests');
  const list = await res.json();
  histEl.innerHTML = '';
  list.forEach(d => {
    const b = document.createElement('button');
    b.textContent = d.date;
    b.addEventListener('click', () => render(d));
    histEl.appendChild(b);
  });
  if (list.length) render(list[0]);
}
</script>
</body>
</html>
"""
