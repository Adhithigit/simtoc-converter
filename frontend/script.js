// ================================================
// SimToC — Frontend Script v3
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
  setInterval(checkStatus, 30000);
});

// ---- Status ----
async function checkStatus() {
  const dot  = document.getElementById('status-dot');
  const text = document.getElementById('status-text');
  try {
    const r = await fetch(`${API}/health`, { signal: AbortSignal.timeout(8000) });
    if (r.ok) {
      dot.className    = 'status-dot online';
      text.textContent = 'Backend Online';
    } else throw new Error();
  } catch {
    dot.className    = 'status-dot offline';
    text.textContent = 'Backend Offline';
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

  document.getElementById('diagram-empty').style.display = 'flex';
  document.getElementById('diagram-svg').style.display   = 'none';
  document.getElementById('code-empty').style.display    = 'flex';
  document.getElementById('code-output').style.display   = 'none';
  document.getElementById('stats-grid').style.display    = 'none';

  try {
    const fd = new FormData();
    fd.append('file', selectedFile);
    const r = await fetch(`${API}/convert`, { method: 'POST', body: fd });
    if (!r.ok) {
      const err = await r.json().catch(() => ({ error: 'Server error' }));
      throw new Error(err.error || `HTTP ${r.status}`);
    }
    const data = await r.json();
    if (data.error) throw new Error(data.error);
    displayResults(data);
    showToast('✅ Conversion successful!');
  } catch (e) {
    showToast(`❌ ${e.message}`, true);
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

  // Stats
  document.getElementById('stat-blocks').textContent = blocks.length;
  document.getElementById('stat-conns').textContent  = conns.length;
  document.getElementById('stat-lines').textContent  = currentCode.split('\n').length;
  document.getElementById('stats-grid').style.display = 'grid';

  // Code
  if (currentCode) {
    document.getElementById('code-empty').style.display  = 'none';
    document.getElementById('code-output').style.display = 'block';
    const el = document.getElementById('code-content');
    el.textContent = currentCode;
    hljs.highlightElement(el);
  }

  // Diagram
  if (blocks.length > 0) {
    document.getElementById('diagram-empty').style.display = 'none';
    document.getElementById('diagram-svg').style.display   = 'block';
    renderDiagram(blocks, conns);
  }
}

// ================================================================
// D3 Diagram — non-overlapping layout
// ================================================================

function renderDiagram(blocks, connections) {
  const svg = d3.select('#diagram-svg');
  svg.selectAll('*').remove();

  const NODE_W  = 110;
  const NODE_H  = 38;
  const PAD_X   = 60;   // horizontal gap between layers
  const PAD_Y   = 16;   // vertical gap between nodes in same layer

  // ---- Arrow marker ----
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

  // ---- Compute layers (Sugiyama-style) ----
  const idMap = {};
  blocks.forEach(b => { idMap[String(b.id)] = b; });

  // Build adjacency
  const outEdges = {};
  const inCount  = {};
  blocks.forEach(b => { outEdges[String(b.id)] = []; inCount[String(b.id)] = 0; });
  connections.forEach(c => {
    const s = String(c.from), d = String(c.to);
    if (outEdges[s] && inCount[d] !== undefined) {
      outEdges[s].push(d);
      inCount[d]++;
    }
  });

  // Topological sort → assign layers
  const layer = {};
  const queue = Object.keys(inCount).filter(id => inCount[id] === 0);
  const visited = new Set(queue);
  queue.forEach(id => { layer[id] = 0; });

  let qi = 0;
  while (qi < queue.length) {
    const cur = queue[qi++];
    const curLayer = layer[cur] || 0;
    (outEdges[cur] || []).forEach(nb => {
      layer[nb] = Math.max(layer[nb] || 0, curLayer + 1);
      if (!visited.has(nb)) {
        visited.add(nb);
        queue.push(nb);
      }
    });
  }

  // Unvisited nodes (disconnected) — put at end
  blocks.forEach(b => {
    const id = String(b.id);
    if (layer[id] === undefined) layer[id] = 0;
  });

  // Group nodes by layer
  const layerGroups = {};
  blocks.forEach(b => {
    const l = layer[String(b.id)] || 0;
    if (!layerGroups[l]) layerGroups[l] = [];
    layerGroups[l].push(b);
  });

  const numLayers = Math.max(...Object.keys(layerGroups).map(Number)) + 1;

  // ---- Sort nodes within each layer to minimise crossings ----
  // Simple barycenter heuristic
  Object.keys(layerGroups).forEach(li => {
    const l = Number(li);
    if (l === 0) return;
    layerGroups[li].sort((a, b) => {
      const aid = String(a.id), bid = String(b.id);
      const aParents = connections.filter(c => String(c.to) === aid).map(c => String(c.from));
      const bParents = connections.filter(c => String(c.to) === bid).map(c => String(c.from));
      const aPos = aParents.length
        ? aParents.reduce((s, pid) => s + (layerGroups[l-1]?.findIndex(n => String(n.id) === pid) || 0), 0) / aParents.length
        : 0;
      const bPos = bParents.length
        ? bParents.reduce((s, pid) => s + (layerGroups[l-1]?.findIndex(n => String(n.id) === pid) || 0), 0) / bParents.length
        : 0;
      return aPos - bPos;
    });
  });

  // ---- Assign pixel positions ----
  const pos = {};
  Object.keys(layerGroups).forEach(li => {
    const l     = Number(li);
    const nodes = layerGroups[li];
    const totalH = nodes.length * NODE_H + (nodes.length - 1) * PAD_Y;
    nodes.forEach((b, i) => {
      pos[String(b.id)] = {
        x: 40 + l * (NODE_W + PAD_X),
        y: 40 + i * (NODE_H + PAD_Y)
      };
    });
  });

  // ---- Block colours by type ----
  function fillColor(type) {
    const t = (type || '').toLowerCase();
    if (['inport','in'].includes(t))             return '#0d3320';
    if (['outport','out'].includes(t))            return '#1e0d33';
    if (['gain','product','sum','dotproduct'].includes(t)) return '#0d1e33';
    if (t.includes('integrator') || t.includes('derivative') ||
        t.includes('delay') || t.includes('memory') ||
        t.includes('zeroorderr'))                 return '#2e2008';
    if (t.includes('subsystem'))                  return '#0a1e2e';
    if (t.includes('sfunction') || t === 'sfunction') return '#2e0808';
    if (t.includes('reference'))                  return '#2a1008';
    if (['constant','step','sinewave','chirp',
         'discretepulsegenerator'].includes(t))   return '#0d2a1a';
    if (t.includes('pid'))                        return '#1a0d2e';
    if (t.includes('transfer') || t.includes('filter')) return '#1a1a2e';
    if (t.includes('scope') || t.includes('display') ||
        t.includes('toworkspace'))                return '#1a1a1a';
    return '#111827';
  }
  function strokeColor(type) {
    const t = (type || '').toLowerCase();
    if (['inport','in'].includes(t))  return '#00ff88';
    if (['outport','out'].includes(t)) return '#aa44ff';
    if (t.includes('sfunction'))      return '#ff4466';
    if (t.includes('reference'))      return '#ff8844';
    if (t.includes('subsystem'))      return '#00aaff';
    if (t.includes('pid'))            return '#ff88ff';
    if (t.includes('transfer') || t.includes('filter')) return '#ffcc44';
    return '#1e3a5a';
  }

  // ---- Draw edges first (behind nodes) ----
  const edgeGroup = g.append('g').attr('class', 'edges');
  connections.forEach(c => {
    const sp = pos[String(c.from)];
    const dp = pos[String(c.to)];
    if (!sp || !dp) return;

    const x1 = sp.x + NODE_W, y1 = sp.y + NODE_H / 2;
    const x2 = dp.x - 2,      y2 = dp.y + NODE_H / 2;
    const mx  = (x1 + x2) / 2;

    edgeGroup.append('path')
      .attr('d', `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`)
      .attr('fill', 'none')
      .attr('stroke', 'rgba(0,212,255,0.35)')
      .attr('stroke-width', 1.2)
      .attr('marker-end', 'url(#arr)');
  });

  // ---- Draw nodes ----
  const nodeGroup = g.append('g').attr('class', 'nodes');
  blocks.forEach(b => {
    const p = pos[String(b.id)];
    if (!p) return;

    const node = nodeGroup.append('g')
      .attr('transform', `translate(${p.x},${p.y})`)
      .style('cursor', 'default');

    // background rect
    node.append('rect')
      .attr('width', NODE_W).attr('height', NODE_H)
      .attr('rx', 5)
      .attr('fill', fillColor(b.type))
      .attr('stroke', strokeColor(b.type))
      .attr('stroke-width', 1.5);

    // type label (small, muted)
    const typeLabel = (b.type || '').slice(0, 16);
    node.append('text')
      .attr('x', NODE_W / 2).attr('y', 12)
      .attr('text-anchor', 'middle')
      .attr('fill', '#556688')
      .attr('font-size', '7.5px')
      .attr('font-family', 'JetBrains Mono, monospace')
      .text(typeLabel);

    // name label
    const rawName = (b.name || '').replace(/\\n|\n/g, ' ').trim();
    const name = rawName.length > 15 ? rawName.slice(0, 14) + '…' : rawName;
    node.append('text')
      .attr('x', NODE_W / 2).attr('y', 26)
      .attr('text-anchor', 'middle')
      .attr('fill', '#d0e8ff')
      .attr('font-size', '9px')
      .attr('font-weight', '600')
      .attr('font-family', 'JetBrains Mono, monospace')
      .text(name);

    // tooltip
    node.append('title').text(`[${b.type}]\n${b.name}`);
  });

  // ---- Fit all into view ----
  setTimeout(fitDiagram, 120);
}

// ---- Fit / Reset ----
function fitDiagram() {
  const svgEl = document.getElementById('diagram-svg');
  const gEl   = svgEl.querySelector('.zoom-group');
  if (!gEl || !zoomBehavior) return;

  const svgR = svgEl.getBoundingClientRect();
  const gR   = gEl.getBoundingClientRect();
  if (gR.width < 1 || gR.height < 1) return;

  const scaleX = (svgR.width  - 80) / gR.width;
  const scaleY = (svgR.height - 80) / gR.height;
  const scale  = Math.min(scaleX, scaleY, 1.5);

  // centre the diagram
  const tx = (svgR.width  - gR.width  * scale) / 2 - gR.left * scale + svgR.left * scale;
  const ty = (svgR.height - gR.height * scale) / 2 - gR.top  * scale + svgR.top  * scale;

  d3.select('#diagram-svg')
    .transition().duration(500)
    .call(zoomBehavior.transform,
          d3.zoomIdentity.translate(tx, ty).scale(scale));
}

function resetZoom() {
  if (!zoomBehavior) return;
  d3.select('#diagram-svg')
    .transition().duration(400)
    .call(zoomBehavior.transform, d3.zoomIdentity.translate(40, 40).scale(1));
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
  const name = selectedFile ? selectedFile.name.replace(/\.[^.]+$/, '') : 'model';
  const blob = new Blob([currentCode], { type: 'text/plain' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `${name}_output.c`;
  a.click();
  URL.revokeObjectURL(a.href);
  showToast('⬇ Downloading...');
}

// ---- Toast ----
function showToast(msg, isError = false) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.style.borderColor = isError ? 'var(--red)' : 'var(--cyan)';
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 3000);
}

// ---- Background Particles ----
function initParticles() {
  const canvas = document.getElementById('bg-canvas');
  const ctx    = canvas.getContext('2d');

  function resize() {
    canvas.width  = window.innerWidth;
    canvas.height = window.innerHeight;
  }
  resize();
  window.addEventListener('resize', resize);

  const pts = Array.from({ length: 55 }, () => ({
    x: Math.random() * canvas.width,
    y: Math.random() * canvas.height,
    vx: (Math.random() - 0.5) * 0.25,
    vy: (Math.random() - 0.5) * 0.25,
    r: Math.random() * 1.4 + 0.4,
    a: Math.random() * 0.5 + 0.1,
  }));

  (function draw() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    pts.forEach(p => {
      p.x += p.vx; p.y += p.vy;
      if (p.x < 0) p.x = canvas.width;
      if (p.x > canvas.width)  p.x = 0;
      if (p.y < 0) p.y = canvas.height;
      if (p.y > canvas.height) p.y = 0;
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(0,212,255,${p.a * 0.35})`;
      ctx.fill();
    });
    requestAnimationFrame(draw);
  })();
}