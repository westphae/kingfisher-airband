(function () {
  const feed = document.getElementById('feed');
  const statusEl = document.getElementById('status');
  let since = 0;
  const seen = new Set();

  function fmtTime(tsNs) {
    const d = new Date(tsNs / 1e6);
    return d.toISOString().slice(11, 19) + 'Z';
  }

  function renderCard(t) {
    const key = `${t.ts_ns}:${t.text}`;
    if (seen.has(key)) return;
    seen.add(key);
    const div = document.createElement('div');
    div.className = `card ${t.direction || 'unknown'}`;
    div.innerHTML = `
      <div class="meta">${fmtTime(t.ts_ns)} · ${t.label} · ${t.freq_mhz.toFixed(3)} MHz · ${t.direction}</div>
      <div class="text"></div>
    `;
    div.querySelector('.text').textContent = t.text;
    if (t.audio_ref) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.textContent = 'Play';
      btn.addEventListener('click', () => {
        const a = new Audio(`/api/audio/${encodeURIComponent(t.audio_ref)}`);
        a.play();
      });
      div.appendChild(btn);
    }
    feed.prepend(div);
    while (feed.children.length > 80) feed.lastChild.remove();
  }

  async function poll() {
    try {
      const [h, t] = await Promise.all([
        fetch('/api/health').then((r) => r.json()),
        fetch(`/api/transcripts?since=${since}`).then((r) => r.json()),
      ]);
      const ch = (h.channels || []).map((c) => `${c.label} ${c.freq_mhz}`).join(' · ');
      statusEl.textContent = `SDR: ${h.sdr_running ? 'on' : 'off'} · KF: ${h.kingfisher_ok ? 'ok' : '—'} · ${ch || 'no channels'}`;
      for (const row of t.transcripts || []) {
        renderCard(row);
        since = Math.max(since, row.ts_ns);
      }
    } catch (e) {
      statusEl.textContent = 'Offline';
    }
  }

  setInterval(poll, 2000);
  poll();
})();
