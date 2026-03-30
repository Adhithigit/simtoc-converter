// ================================================
// SimToC — Frontend Script v4
// ================================================
const API = 'https://simtoc-converter.onrender.com';

let currentCode = '';
let selectedFile = null;
let zoomBehavior = null;

// ---- Init ----
document.addEventListener('DOMContentLoaded', () => {
  checkStatus();
  initParticles();
  setupDrop();
  document.getElementById('file-input').addEventListener('change', e => {
    if (e.target.files[0]) handleFile(e.target.files[0]);
  });
  // Check status every 60 seconds (not 30 — less noise)
  setInterval(checkStatus, 60000);
});

// ---- Status Check ----
// Render free tier cold starts take up to 50s — use longer timeout
async function checkStatus() {
  const dot  = document.getElementById('status-dot');
  const text = document.getElementById('status-text');

  dot.className    = 'status-dot';
  text.textContent = 'Checking...';

  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 60000); // 60s timeout

    const r = await fetch(`${API}/health`, {
      signal: controller.signal,
      method: 'GET',
      headers: { 'Accept': 'application/json' }
    });
    clearTimeout(timer);

    if (r.ok) {
      dot.className    = 'status-dot online';
      text.textContent = 'Backend Online';
    } else {
      throw new Error(`HTTP ${r.status}`);
    }
  } catch (e) {
    if (e.name === 'AbortError') {
      // Still waking up — show warning not error
      dot.className    = 'status-dot warning';
      text.textContent = 'Waking up...';
      // Retry after 15s
      setTimeout(checkStatus, 15000);
    } else {
      dot.className    = 'status-dot offline';
      text.textContent = 'Backend Offline';
    }
  }
}

// ---- Drag & Drop ----
function setupDrop() {
  const zone = document.getElementById('drop-zone');
  zone.addEventListener('dragover',  e => { e.preventDefault(); zone.classList.add('drag-over'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('drag-over'));
  zone.addEventListener('drop', e => {
    e.preventDefault();
    zone.classList.remove('drag-over');
    if (e.dataTransfer.files[0]) handleFile(e.dataTransfer.files[0]);
  });
}

// ---- File Handling ----
function handleFile(file) {
  const allowed = ['slx','mdl','pdf','png','jpg','jpeg','bmp'];
  const ext = file.name.split('.').pop().toLowerCase();
  if (!allowed.includes(ext)) { showToast('Unsupported file type!', true); return; }
  selectedFile = file;
  document.getElementById('drop-zone').style.display = 'none';
  document.getElementById('file-info').style.display = 'flex';
  document.getElementById('file-name').textContent   = file.name;
  document.getElementById('file-size').textContent   = formatSize(file.size);
  document.getElementById('btn-convert').disabled    = false;
}

function clearFile() {
  selectedFile = null;
  document.getElementById('drop-zone').style.display = 'block';
  document.getElementById('file-info').style.display = 'none';
  document.getElementById('btn-convert').disabled    = true;
  document.getElementById('file-input').value        = '';
}

function formatSize(b) {
  if (b < 1024) return b + ' B';
  if (b < 1048576) return (b/1024).toFixed(1) + ' KB';
  return (b/1048576).toFixed(1) + ' MB';
}

// ---- Convert ----
async function convertFile() {
  if (!selectedFile) return;

  const btn  = document.getElementById('btn-convert');
  const txt  = document.getElementById('btn-text');
  btn.disabled = true;
  btn.classList.add('loading');
  txt.textContent = '⏳ Converting...';

  // Reset results
  document.getElementById('diagram-empty').style.display = 'flex';
  document.getElementById('diagram-svg').style.display   = 'none';
  document.getElementById('code-empty').style.display    = 'flex';
  document.getElementById('code-output').style.display   = 'none';
  document.getElementById('stats-grid').style.display    = 'none';

  try {
    const fd = new FormData();
    fd.append('file', selectedFile);

    // Long timeout — Render free tier cold start can be 50s+
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 120000); // 2 min

    const r = await fetch(`${API}/convert`, {
      method: 'POST',
      body: fd,
      signal: controller.signal
    });
    clearTimeout(timer);

    if (!r.ok) {
      const err = await r.json().catch(() => ({ error: `HTTP ${r.status}` }));
      throw new Error(err.error || `HTTP ${r.status}`);
    }

    const data = await r.json();
    if (data.error) throw new Error(data.error);

    displayResults(data);
    showToast('✅ Conversion successful!');

    // Update status dot to online after successful call
    document.getElementById('status-dot').className    = 'status-dot online';
    document.getElementById('status-text').textContent = 'Backend Online';

  } catch (e) {
    if (e.name === 'AbortError') {
      showToast('❌ Request timed out. Backend may be waking up — try again in 30s.', true);
    } else {
      showToast(`❌ ${e.message}`, true);
    }
    console.error(e);
  } finally {
    btn.disabled = false;
    btn.classList.remove('loading');
    txt.textContent = '⚡ Convert to C';
  }
}

// ---- Display Results ----
function displayResults(data) {
  currentCode = data.c_code || '';
  const blocks = data.blocks || [];
  const conns  = data.connections || [];

  document.getElementById('stat-blocks').textContent = blocks.length;
  document.getElementById('stat-conns').textContent  = conns.length;
  document.getElementById('stat-lines').textContent  = currentCode.split('\n').length;
  document.getElementById('stats-grid').style.display = 'grid';

  if (currentCode) {
    document.getElementById('code-empty').style.display  = 'none';
    document.getElementById('code-output').style.display = 'block';
    const el = document.getElementById('code-content');
    el.textContent = currentCode;
    hljs.highlightElement(el);
  }

  if (blocks.length > 0) {
    document.getElementById('diagram-empty').style.display = 'none';
    document.getElementById('diagram-svg').style.display   = 'block';
    renderDiagram(blocks, conns);
  }
}

// ================================================================
// D3 Diagram — non-overlapping Sugiyama layout
// ================================================================

function renderDiagram(blocks, connections) {
  const svg = d3.select('#diagram-svg');
  svg.selectAll('*').remove();

  const NODE_W = 110, NODE_H = 38, PAD_X = 60, PAD_Y = 16;

  svg.append('defs').append('marker')
    .attr('id', 'arr')
    .attr('viewBox', '0 -4 8 8')
    .attr('refX', 8).attr('refY', 0)
    .attr('markerWidth', 5).attr('markerHeight', 5)
    .attr('orient', 'auto')
    .append('path')
    .attr('d', 'M0,-4L8,0L0,4')
    .attr('fill', 'rgba(0,212,255,0.8)');

  const g = svg.append('g').attr('class', 'zoom-group');

  zoomBehavior = d3.zoom()
    .scaleExtent([0.05, 4])
    .on('zoom', e => g.attr('transform', e.transform));
  svg.call(zoomBehavior);

  // Assign layers via topological sort
  const inDeg = {};
  const outEdges = {};
  blocks.forEach(b => { inDeg[String(b.id)] = 0; outEdges[String(b.id)] = []; });
  connections.forEach(c => {
    const s = String(c.from), d = String(c.to);
    if (outEdges[s] !== undefined && inDeg[d] !== undefined) {
      outEdges[s].push(d);
      inDeg[d]++;
    }
  });

  const layer = {};
  const queue = Object.keys(inDeg).filter(id => inDeg[id] === 0);
  const visited = new Set(queue);
  queue.forEach(id => { layer[id] = 0; });

  let qi = 0;
  while (qi < queue.length) {
    const cur = queue[qi++];
    (outEdges[cur] || []).forEach(nb => {
      layer[nb] = Math.max(layer[nb] || 0, (layer[cur] || 0) + 1);
      if (!visited.has(nb)) { visited.add(nb); queue.push(nb); }
    });
  }

  blocks.forEach(b => { if (layer[String(b.id)] === undefined) layer[String(b.id)] = 0; });

  // Group by layer
  const layerGroups = {};
  blocks.forEach(b => {
    const l = layer[String(b.id)] || 0;
    if (!layerGroups[l]) layerGroups[l] = [];
    layerGroups[l].push(b);
  });

  // Barycenter sort within layers
  Object.keys(layerGroups).forEach(li => {
    const l = Number(li);
    if (l === 0) return;
    layerGroups[li].sort((a, b) => {
      const aid = String(a.id), bid = String(b.id);
      const ap = connections.filter(c => String(c.to) === aid).map(c => {
        const pi = (layerGroups[l-1] || []).findIndex(n => String(n.id) === String(c.from));
        return pi >= 0 ? pi : 0;
      });
      const bp = connections.filter(c => String(c.to) === bid).map(c => {
        const pi = (layerGroups[l-1] || []).findIndex(n => String(n.id) === String(c.from));
        return pi >= 0 ? pi : 0;
      });
      const am = ap.length ? ap.reduce((s,v)=>s+v,0)/ap.length : 0;
      const bm = bp.length ? bp.reduce((s,v)=>s+v,0)/bp.length : 0;
      return am - bm;
    });
  });

  // Pixel positions
  const pos = {};
  Object.keys(layerGroups).forEach(li => {
    const nodes = layerGroups[li];
    nodes.forEach((b, i) => {
      pos[String(b.id)] = {
        x: 40 + Number(li) * (NODE_W + PAD_X),
        y: 40 + i * (NODE_H + PAD_Y)
      };
    });
  });

  function fillColor(type) {
    const t = (type||'').toLowerCase();
    if (['inport','in'].includes(t))               return '#0d3320';
    if (['outport','out'].includes(t))              return '#1e0d33';
    if (['gain','product','sum'].includes(t))       return '#0d1e33';
    if (t.includes('integrator')||t.includes('delay')||t.includes('memory')) return '#2e2008';
    if (t.includes('subsystem'))                    return '#0a1e2e';
    if (t.includes('sfunction'))                    return '#2e0808';
    if (t.includes('reference'))                    return '#2a1008';
    if (['constant','step','sinewave'].includes(t)) return '#0d2a1a';
    if (t.includes('pid'))                          return '#1a0d2e';
    if (t.includes('transfer')||t.includes('filter')) return '#1a1a2e';
    if (t.includes('saturat'))                      return '#1a2a0a';
    if (t.includes('scope')||t.includes('display')) return '#1a1a1a';
    return '#111827';
  }
  function strokeColor(type) {
    const t = (type||'').toLowerCase();
    if (['inport','in'].includes(t))    return '#00ff88';
    if (['outport','out'].includes(t))  return '#aa44ff';
    if (t.includes('sfunction'))        return '#ff4466';
    if (t.includes('reference'))        return '#ff8844';
    if (t.includes('subsystem'))        return '#00aaff';
    if (t.includes('pid'))              return '#ff88ff';
    if (t.includes('transfer')||t.includes('filter')) return '#ffcc44';
    if (t.includes('saturat'))          return '#88ff44';
    return '#1e3a5a';
  }

  // Draw edges
  const edgeG = g.append('g');
  connections.forEach(c => {
    const sp = pos[String(c.from)];
    const dp = pos[String(c.to)];
    if (!sp || !dp) return;
    const x1 = sp.x + NODE_W, y1 = sp.y + NODE_H/2;
    const x2 = dp.x - 2,      y2 = dp.y + NODE_H/2;
    const mx = (x1+x2)/2;
    edgeG.append('path')
      .attr('d', `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`)
      .attr('fill', 'none')
      .attr('stroke', 'rgba(0,212,255,0.35)')
      .attr('stroke-width', 1.5)
      .attr('marker-end', 'url(#arr)');
  });

  // Draw nodes
  const nodeG = g.append('g');
  blocks.forEach(b => {
    const p = pos[String(b.id)];
    if (!p) return;
    const node = nodeG.append('g')
      .attr('transform', `translate(${p.x},${p.y})`);

    node.append('rect')
      .attr('width', NODE_W).attr('height', NODE_H).attr('rx', 5)
      .attr('fill', fillColor(b.type))
      .attr('stroke', strokeColor(b.type))
      .attr('stroke-width', 1.5);

    node.append('text')
      .attr('x', NODE_W/2).attr('y', 12)
      .attr('text-anchor', 'middle')
      .attr('fill', '#556688')
      .attr('font-size', '7.5px')
      .attr('font-family', 'JetBrains Mono, monospace')
      .text((b.type||'').slice(0,16));

    const name = (b.name||'').replace(/\\n|\n/g,' ').trim();
    node.append('text')
      .attr('x', NODE_W/2).attr('y', 26)
      .attr('text-anchor', 'middle')
      .attr('fill', '#d0e8ff')
      .attr('font-size', '9px')
      .attr('font-weight', '600')
      .attr('font-family', 'JetBrains Mono, monospace')
      .text(name.length > 15 ? name.slice(0,14)+'…' : name);

    node.append('title').text(`[${b.type}]\n${b.name}`);
  });

  setTimeout(fitDiagram, 120);
}

function fitDiagram() {
  const svgEl = document.getElementById('diagram-svg');
  const gEl   = svgEl.querySelector('.zoom-group');
  if (!gEl || !zoomBehavior) return;
  const svgR = svgEl.getBoundingClientRect();
  const gR   = gEl.getBoundingClientRect();
  if (gR.width < 1 || gR.height < 1) return;
  const scale = Math.min((svgR.width-80)/gR.width, (svgR.height-80)/gR.height, 1.5);
  const tx = (svgR.width  - gR.width  * scale) / 2 - gR.left  * scale + svgR.left  * scale;
  const ty = (svgR.height - gR.height * scale) / 2 - gR.top   * scale + svgR.top   * scale;
  d3.select('#diagram-svg').transition().duration(500)
    .call(zoomBehavior.transform, d3.zoomIdentity.translate(tx,ty).scale(scale));
}

function resetZoom() {
  if (!zoomBehavior) return;
  d3.select('#diagram-svg').transition().duration(400)
    .call(zoomBehavior.transform, d3.zoomIdentity.translate(40,40).scale(1));
}

// ---- Copy & Download ----
async function copyCode() {
  if (!currentCode) return;
  try {
    await navigator.clipboard.writeText(currentCode);
    showToast('📋 Copied to clipboard!');
  } catch { showToast('❌ Copy failed', true); }
}

function downloadCode() {
  if (!currentCode) return;
  const name = selectedFile ? selectedFile.name.replace(/\.[^.]+$/,'') : 'model';
  const blob = new Blob([currentCode], { type: 'text/plain' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `${name}_output.c`;
  a.click();
  URL.revokeObjectURL(a.href);
  showToast('⬇ Downloading...');
}

// ---- Toast ----
function showToast(msg, isError=false) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.style.borderColor = isError ? 'var(--red)' : 'var(--cyan)';
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 4000);
}

// ---- Particles ----
function initParticles() {
  const canvas = document.getElementById('bg-canvas');
  const ctx    = canvas.getContext('2d');
  function resize() { canvas.width = window.innerWidth; canvas.height = window.innerHeight; }
  resize();
  window.addEventListener('resize', resize);
  const pts = Array.from({length:55}, () => ({
    x: Math.random()*canvas.width,  y: Math.random()*canvas.height,
    vx:(Math.random()-.5)*.25,       vy:(Math.random()-.5)*.25,
    r: Math.random()*1.4+.4,         a: Math.random()*.5+.1
  }));
  (function draw() {
    ctx.clearRect(0,0,canvas.width,canvas.height);
    pts.forEach(p => {
      p.x+=p.vx; p.y+=p.vy;
      if(p.x<0) p.x=canvas.width;  if(p.x>canvas.width)  p.x=0;
      if(p.y<0) p.y=canvas.height; if(p.y>canvas.height) p.y=0;
      ctx.beginPath(); ctx.arc(p.x,p.y,p.r,0,Math.PI*2);
      ctx.fillStyle=`rgba(0,212,255,${p.a*.35})`; ctx.fill();
    });
    requestAnimationFrame(draw);
  })();
}