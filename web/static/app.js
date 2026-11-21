(function () {
  const feed = document.getElementById('feed');
  const statusEl = document.getElementById('status');
  const channelListEl = document.getElementById('channelList');
  const autoSourcesEl = document.getElementById('autoSources');
  const planModeEl = document.getElementById('planMode');
  const liveAudioCheck = document.getElementById('liveAudioCheck');
  const liveAudioStatus = document.getElementById('liveAudioStatus');
  const liveAudioLabel = document.getElementById('liveAudioLabel');
  const channelsPanel = document.getElementById('channelsPanel');
  let since = 0;
  const seen = new Set();
  let catalog = null;
  let patchInFlight = false;
  /** @type {{ channel?: { freq_mhz: number, enabled: boolean }, planner?: { key: string, value: boolean }, liveAudio?: boolean }} */
  const pending = {};
  let liveWs = null;
  let audioCtx = null;
  let nextPlayTime = 0;
  const LIVE_SAMPLE_RATE = 8000;

  function fmtTime(tsNs) {
    const d = new Date(tsNs / 1e6);
    return d.toISOString().slice(11, 19) + 'Z';
  }

  function fmtFreq(mhz) {
    return Number(mhz).toFixed(3);
  }

  function freqKey(mhz) {
    return Number(mhz).toFixed(3);
  }

  function clearPending() {
    delete pending.channel;
    delete pending.planner;
    delete pending.liveAudio;
  }

  function setPanelBusy(busy) {
    channelsPanel.classList.toggle('busy', busy);
    channelsPanel.setAttribute('aria-busy', busy ? 'true' : 'false');
  }

  function showPendingUI() {
    if (catalog) renderCatalog(catalog);
    setPanelBusy(true);
  }

  function channelPending(ch) {
    return pending.channel && freqKey(pending.channel.freq_mhz) === freqKey(ch.freq_mhz);
  }

  function plannerPending(key) {
    return pending.planner && pending.planner.key === key;
  }

  function fmtDur(sec) {
    if (sec == null || Number.isNaN(sec)) return '?';
    return `${Number(sec).toFixed(1)}s`;
  }

  function renderCard(t) {
    const key = `${t.ts_ns}:${t.text}`;
    if (seen.has(key)) return;
    seen.add(key);
    const div = document.createElement('div');
    div.className = `card ${t.direction || 'unknown'}`;
    const freq = t.freq_mhz > 0 ? `${fmtFreq(t.freq_mhz)} MHz · ` : '';
    div.innerHTML = `
      <div class="meta">${fmtTime(t.ts_ns)} · ${fmtDur(t.duration_s)} · ${freq}${t.label} · ${t.direction}</div>
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

  function setLiveStatus(text, cls) {
    liveAudioStatus.textContent = text;
    liveAudioStatus.className = `live-audio-status${cls ? ` ${cls}` : ''}`;
  }

  function liveWsOpen() {
    return liveWs && liveWs.readyState === WebSocket.OPEN;
  }

  function liveOutputNeedsAttention() {
    if (!catalog?.debug?.live_audio) return false;
    if (!liveWsOpen()) return true;
    if (!audioCtx || audioCtx.state === 'suspended') return true;
    return false;
  }

  async function resumeLiveOutput() {
    if (audioCtx && audioCtx.state === 'suspended') {
      try {
        await audioCtx.resume();
      } catch (_) {
        /* autoplay policy */
      }
    }
    if (audioCtx?.state === 'running') {
      const cont = catalog?.debug?.live_audio_continuous;
      setLiveStatus(cont ? 'live · continuous' : 'live · squelch', 'on');
    } else {
      updateLiveStatusFromState();
    }
  }

  function updateLiveStatusFromState() {
    if (!catalog?.debug?.live_audio) {
      setLiveStatus('off', '');
      return;
    }
    if (!liveWsOpen()) {
      setLiveStatus('reconnecting…', '');
      return;
    }
    if (!audioCtx || audioCtx.state === 'suspended') {
      setLiveStatus('click to unmute', 'pending');
      return;
    }
  }

  /** Keep WebSocket + AudioContext aligned with catalog.debug.live_audio. */
  async function ensureLiveAudio(userGesture = false) {
    if (!catalog?.debug?.live_audio) {
      if (liveWs) stopLiveAudio();
      return;
    }
    if (!liveWsOpen()) {
      startLiveAudio();
      return;
    }
    if (userGesture) {
      await resumeLiveOutput();
    } else if (audioCtx?.state === 'suspended') {
      setLiveStatus('click to unmute', 'pending');
    }
  }

  function stopLiveAudio() {
    if (liveWs) {
      liveWs.close();
      liveWs = null;
    }
    if (audioCtx) {
      audioCtx.close().catch(() => {});
      audioCtx = null;
    }
    nextPlayTime = 0;
    setLiveStatus('off', '');
  }

  function scheduleLiveChunk(arrayBuffer) {
    if (!audioCtx) return;
    const f32 = new Float32Array(arrayBuffer);
    if (!f32.length) return;
    const buf = audioCtx.createBuffer(1, f32.length, LIVE_SAMPLE_RATE);
    buf.copyToChannel(f32, 0);
    const src = audioCtx.createBufferSource();
    src.buffer = buf;
    src.connect(audioCtx.destination);
    const lead = 0.08;
    const startAt = Math.max(audioCtx.currentTime + lead, nextPlayTime || audioCtx.currentTime + lead);
    src.start(startAt);
    nextPlayTime = startAt + buf.duration;
  }

  function startLiveAudio() {
    if (liveWs) {
      const st = liveWs.readyState;
      if (st === WebSocket.OPEN || st === WebSocket.CONNECTING) return;
      stopLiveAudio();
    }
    if (!catalog?.debug?.live_audio) {
      setLiveStatus('enable in config', 'err');
      liveAudioCheck.checked = false;
      return;
    }
    setLiveStatus('connecting…', '');
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${proto}//${location.host}/ws/live-audio`);
    liveWs = ws;
    ws.binaryType = 'arraybuffer';
    ws.onopen = () => {
      if (audioCtx?.state === 'suspended') setLiveStatus('click to unmute', 'pending');
      else setLiveStatus('connected', 'on');
    };
    ws.onclose = () => {
      liveWs = null;
      if (catalog?.debug?.live_audio) setLiveStatus('disconnected', 'err');
      else setLiveStatus('off', '');
    };
    ws.onerror = () => setLiveStatus('error', 'err');
    ws.onmessage = (ev) => {
      if (typeof ev.data === 'string') {
        const meta = JSON.parse(ev.data);
        if (!audioCtx) {
          audioCtx = new AudioContext({ sampleRate: meta.sample_rate || LIVE_SAMPLE_RATE });
          nextPlayTime = audioCtx.currentTime;
        }
        if (audioCtx.state === 'suspended') {
          setLiveStatus('click to unmute', 'pending');
        } else {
          setLiveStatus(meta.continuous ? 'live · continuous' : 'live · squelch', 'on');
        }
        return;
      }
      if (audioCtx?.state === 'suspended') return;
      scheduleLiveChunk(ev.data);
    };
  }

  function chipLabel(ch) {
    const name = ch.label || fmtFreq(ch.freq_mhz);
    const tag = ch.via_howgozit ? '<span class="chip-tag">HGZ</span>' : '';
    return `<span>${name} ${fmtFreq(ch.freq_mhz)}</span>${tag}`;
  }

  function onChipClick(ch) {
    if (ch.source === 'howgozit') {
      void patchPlanner({ include_active_com: false });
      return;
    }
    if (ch.via_howgozit && !ch.enabled && ch.active) {
      void patchPlanner({ include_active_com: false });
      return;
    }
    void toggleChannel(ch.freq_mhz, !ch.enabled);
  }

  function renderCatalog(data) {
    if (!data) return;
    catalog = data;
    planModeEl.textContent = data.plan_mode ? `mode: ${data.plan_mode}` : '';

    channelListEl.innerHTML = '';
    for (const ch of data.channels || []) {
      const isPending = channelPending(ch);
      const chip = document.createElement('label');
      const classes = ['channel-chip'];
      const live = ch.active ?? ch.monitored;
      if (isPending) {
        classes.push('pending');
      } else {
        classes.push(live ? 'on' : 'off');
        if (ch.monitored) classes.push('monitored');
        if (ch.via_howgozit) classes.push('via-hgz');
      }
      chip.className = classes.join(' ');
      const checked = isPending ? pending.channel.enabled : live;
      chip.innerHTML = `<input type="checkbox" ${checked ? 'checked' : ''} disabled>${chipLabel(ch)}`;
      chip.addEventListener('click', (e) => {
        e.preventDefault();
        if (patchInFlight) return;
        onChipClick(ch);
      });
      channelListEl.appendChild(chip);
    }

    autoSourcesEl.innerHTML = '';
    const pl = data.planner || {};
    const gpsPending = plannerPending('include_gps_airport');
    const gpsLabel = document.createElement('label');
    gpsLabel.className = gpsPending ? 'pending' : '';
    const gpsChecked = gpsPending ? pending.planner.value : pl.include_gps_airport;
    gpsLabel.innerHTML = `<input type="checkbox" ${gpsChecked ? 'checked' : ''} disabled> GPS airport freqs`;
    gpsLabel.addEventListener('click', (e) => {
      e.preventDefault();
      if (patchInFlight) return;
      void patchPlanner({ include_gps_airport: !pl.include_gps_airport });
    });
    autoSourcesEl.appendChild(gpsLabel);

    const comPending = plannerPending('include_active_com');
    const comLabel = document.createElement('label');
    comLabel.className = comPending ? 'pending' : '';
    const comChecked = comPending ? pending.planner.value : pl.include_active_com;
    comLabel.innerHTML = `<input type="checkbox" ${comChecked ? 'checked' : ''} disabled> Howgozit active COM`;
    comLabel.addEventListener('click', (e) => {
      e.preventDefault();
      if (patchInFlight) return;
      void patchPlanner({ include_active_com: !pl.include_active_com });
    });
    autoSourcesEl.appendChild(comLabel);

    for (const row of data.auto || []) {
      const el = document.createElement('div');
      el.className = 'auto-row';
      const live = row.monitored ? ' · live' : '';
      if (row.matched_static_label) {
        el.textContent = `Active COM ${fmtFreq(row.freq_mhz)} MHz → ${row.matched_static_label}${live}`;
      } else {
        el.textContent = `${row.label} ${fmtFreq(row.freq_mhz)} MHz${live}`;
      }
      autoSourcesEl.appendChild(el);
    }

    const dbg = data.debug || {};
    const livePending = pending.liveAudio !== undefined;
    liveAudioLabel.classList.toggle('pending', livePending);
    liveAudioCheck.disabled = patchInFlight;
    liveAudioCheck.checked = livePending ? pending.liveAudio : !!dbg.live_audio;
    if (livePending) {
      setLiveStatus('reconfiguring…', 'pending');
    } else if (!dbg.live_audio && liveWs) {
      stopLiveAudio();
    } else if (dbg.live_audio && !patchInFlight) {
      void ensureLiveAudio(false);
    }
  }

  async function loadCatalog() {
    const r = await fetch('/api/channels/catalog');
    if (!r.ok) return;
    renderCatalog(await r.json());
  }

  async function toggleChannel(freqMhz, enabled) {
    if (patchInFlight) return;
    pending.channel = { freq_mhz: freqMhz, enabled };
    patchInFlight = true;
    showPendingUI();
    let nextCatalog = null;
    try {
      const r = await fetch('/api/channels', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ freq_mhz: freqMhz, enabled }),
      });
      if (!r.ok) {
        statusEl.textContent = `Channel update failed: ${await r.text()}`;
        clearPending();
        nextCatalog = catalog;
      } else {
        clearPending();
        nextCatalog = await r.json();
      }
    } finally {
      patchInFlight = false;
      setPanelBusy(false);
      if (nextCatalog) renderCatalog(nextCatalog);
    }
  }

  async function patchPlanner(body) {
    if (patchInFlight) return;
    const key = Object.keys(body)[0];
    pending.planner = { key, value: body[key] };
    patchInFlight = true;
    showPendingUI();
    let nextCatalog = null;
    try {
      const r = await fetch('/api/planner', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!r.ok) {
        statusEl.textContent = `Planner update failed: ${await r.text()}`;
        clearPending();
        nextCatalog = catalog;
      } else {
        clearPending();
        nextCatalog = await r.json();
      }
    } finally {
      patchInFlight = false;
      setPanelBusy(false);
      if (nextCatalog) renderCatalog(nextCatalog);
    }
  }

  async function toggleLiveAudio(enabled) {
    if (patchInFlight) return;
    pending.liveAudio = enabled;
    patchInFlight = true;
    showPendingUI();
    let nextCatalog = null;
    let ok = false;
    try {
      const r = await fetch('/api/debug', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ live_audio: enabled }),
      });
      if (!r.ok) {
        setLiveStatus('toggle failed', 'err');
        clearPending();
        nextCatalog = catalog;
      } else {
        clearPending();
        nextCatalog = await r.json();
        ok = true;
      }
    } finally {
      patchInFlight = false;
      setPanelBusy(false);
      if (nextCatalog) renderCatalog(nextCatalog);
      if (ok) {
        if (enabled) void ensureLiveAudio(true);
        else stopLiveAudio();
      }
    }
  }

  liveAudioLabel.addEventListener('click', (e) => {
    e.preventDefault();
    if (patchInFlight) return;
    if (liveAudioCheck.checked && liveOutputNeedsAttention()) {
      void ensureLiveAudio(true);
      return;
    }
    void toggleLiveAudio(!liveAudioCheck.checked);
  });

  let wasOffline = false;

  async function poll() {
    try {
      const [h, t] = await Promise.all([
        fetch('/api/health').then((r) => r.json()),
        fetch(`/api/transcripts?since=${since}`).then((r) => r.json()),
      ]);
      if (wasOffline) {
        wasOffline = false;
        void loadCatalog();
      }
      const ch = (h.channels || []).map((c) => `${c.label} ${fmtFreq(c.freq_mhz)}`).join(' · ');
      const err = h.sdr_error ? ` · ERR: ${h.sdr_error.slice(0, 60)}` : '';
      const ing = h.ingest || {};
      const udpAge = ing.last_packet_ts_ns
        ? `${Math.round((Date.now() * 1e6 - ing.last_packet_ts_ns) / 1e9)}s ago`
        : 'never';
      const udp = `UDP: ${ing.udp_packets || 0} pkts · peak ${ing.last_peak || 0} · ${udpAge}`;
      statusEl.textContent = `${udp} · STT: ${h.stt_ready ? 'ready' : 'loading'} · SDR: ${h.sdr_running ? 'on' : 'off'} · KF: ${h.kingfisher_ok ? 'ok' : '—'} · ${h.plan_mode || '—'} · ${ch || 'no channels'}${err}`;
      if (catalog && h.plan_mode && catalog.plan_mode !== h.plan_mode) {
        void loadCatalog();
      }
      if (catalog?.debug?.live_audio && !patchInFlight) {
        void ensureLiveAudio(false);
      }
      for (const row of t.transcripts || []) {
        renderCard(row);
        since = Math.max(since, row.ts_ns);
      }
    } catch (e) {
      statusEl.textContent = 'Offline';
      wasOffline = true;
    }
  }

  setInterval(poll, 2000);
  loadCatalog().then(() => {
    void ensureLiveAudio(false);
  });
  poll();
})();
