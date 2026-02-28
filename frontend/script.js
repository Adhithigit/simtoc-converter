// ================================================
// SimToC — Frontend Script
// ================================================
const API = 'https://simtoc-converter.onrender.com';

let currentCode = '';
let selectedFile = null;

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

// ---- Status Check ----
async function checkStatus() {
  const dot  = document.getElementById('status-dot');
  const text = document.getElementById('status-text');
  try {
    const r = await fetch(`${API}/health`, { signal: AbortSignal.timeout(8000) });
    if (r.ok) {
      dot.className  = 'status-dot online';
      text.textContent = 'Backend Online';
    } else { throw new Error(); }
  } catch {
    dot.className  = 'status-dot offline';
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
  if (!allowed.includes(ext)) { toast('Unsupported file type!', true); return; }

  selectedFile = file;
  document.getElementById('drop-zone').style.display = 'none';
  const info = document.getElementById('file-info');
  info.style.display = 'flex';
  document.getElementById('file-name').textContent = file.name;
  document.getElementById('file-size').textContent = formatSize(file.size);
  document.getElementById('btn-convert').disabled = false;
}

function clearFile() {
  selectedFile = null;
  document.getElementById('drop-zone').style.display = 'block';
  document.getElementById('file-info').style.display = 'none';
  document.getElementById('btn-convert').disabled = true;
  document.getElementById('file-input').value = '';
}

function formatSize(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024*1024) return (bytes/1024).toFixed(1) + ' KB';
  return (bytes/1024/1024).toFixed(1) + ' MB';
}

// ---- Convert ----
async function convertFile() {
  if (!selectedFile) return;

  const btn  = document.getElementById('btn-convert');
  const text = document.getElementById('btn-text');
  btn.disabled = true;
  btn.classList.add('loading');
  text.textContent = '⏳ Converting...';

  // Hide previous results
  document.getElementById('diagram-empty').style.display = 'flex';
  document.getElementById('diagram-svg').style.display = 'none';
  document.getElementById('code-empty').style.display = 'flex';
  document.getElementById('code-output').style.display = 'none';
  document.getElementById('stats-grid').style.display = 'none';

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
    toast('✅ Conversion successful!');
  } catch (e) {
    toast(`❌ ${e.message}`, true);
    console.error(e);
  } finally {
    btn.disabled = false;
    btn.classList.remove('loading');
    text.textContent = '⚡ Convert to C';
  }
}

// ---- Display Results ----
function displayResults(data) {
  currentCode = data.c_code || '';

  // Stats
  const lines = currentCode.split('\n').length;
  document.getElementById('stat-blocks').textContent = (data.blocks || []).length;
  document.getElementById('stat-conns').textContent  = (data.connections || []).length;
  document.getElementById('stat-lines').textContent  = lines;
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
  if (data.blocks && data.blocks.length > 0) {
    document.getElementById('diagram-empty').style.display = 'none';
    document.getElementById('diagram-svg').style.display   = 'block';
    renderDiagram(data.blocks, data.connections || []);
  }
}

// ---- D3 Diagram ----
let svgEl, zoomBehavior;

function renderDiagram(blocks, connections) {
  const container = document.getElementById('diagram-container');
  const W = container.clientWidth;
  const H = container.clientHeight;

  const svg = d3.select('#diagram-svg');
  svg.selectAll('*').remove();

  // Arrow marker
  svg.append('defs').append('marker')
    .attr('id', 'arrow')
    .attr('viewBox', '0 -5 10 10')
    .attr('refX', 10).attr('refY', 0)
    .attr('markerWidth', 6).attr('markerHeight', 6)
    .attr('orient', 'auto')
    .append('path')
    .attr('d', 'M0,-5L10,0L0,5')
    .attr('fill', 'rgba(0,212,255,0.7)');

  const g = svg.append('g').attr('class', 'zoom-group');

  zoomBehavior = d3.zoom()
    .scaleExtent([0.1, 4])
    .on('zoom', e => g.attr('transform', e.transform));
  svg.call(zoomBehavior);

  // Layout: use positions from MDL if available, else auto-layout
  const NODE_W = 100;
  const NODE_H = 36;
  const PAD_X  = 140;
  const PAD_Y  = 60;

  // Check if we have real positions
  const hasPositions = blocks.some(b => b.x !== 0 || b.y !== 0);

  let nodeMap = {};
  let positions = {};

  if (hasPositions) {
    // Use real positions but scale them
    const xs = blocks.map(b => b.x);
    const ys = blocks.map(b => b.y);
    const minX = Math.min(...xs), maxX = Math.max(...xs);
    const minY = Math.min(...ys), maxY = Math.max(...ys);
    const rangeX = maxX - minX || 1;
    const rangeY = maxY - minY || 1;

    blocks.forEach(b => {
      positions[b.id] = {
        x: 60 + ((b.x - minX) / rangeX) * (W - 200),
        y: 40 + ((b.y - minY) / rangeY) * (H - 100)
      };
    });
  } else {
    // Auto layout: left to right by topological order
    const inDeg = {};
    blocks.forEach(b => inDeg[b.id] = 0);
    connections.forEach(c => { if (inDeg[c.to] !== undefined) inDeg[c.to]++; });

    const layers = [];
    let remaining = [...blocks];
    let placed = new Set();

    while (remaining.length > 0) {
      const layer = remaining.filter(b => inDeg[b.id] === 0 && !placed.has(b.id));
      if (layer.length === 0) { // break cycles
        const fallback = remaining.filter(b => !placed.has(b.id));
        if (fallback.length) { layers.push([fallback[0]]); placed.add(fallback[0].id); }
        break;
      }
      layers.push(layer);
      layer.forEach(b => {
        placed.add(b.id);
        connections.filter(c => c.from === b.id).forEach(c => {
          if (inDeg[c.to] !== undefined) inDeg[c.to]--;
        });
      });
      remaining = remaining.filter(b => !placed.has(b.id));
    }

    layers.forEach((layer, li) => {
      layer.forEach((b, bi) => {
        positions[b.id] = {
          x: 60 + li * PAD_X,
          y: 40 + bi * PAD_Y
        };
      });
    });
  }

  blocks.forEach(b => { nodeMap[b.id] = b; });

  // Block color by type
  function blockColor(type) {
    const t = (type || '').toLowerCase();
    if (['inport','in'].includes(t))         return '#1a4a2e';
    if (['outport','out'].includes(t))        return '#2e1a4a';
    if (['gain','product','sum'].includes(t)) return '#1a2e4a';
    if (t.includes('integrator') || t.includes('delay') || t.includes('memory')) return '#2e2a1a';
    if (t.includes('subsystem'))              return '#1e3040';
    if (t.includes('sfunc') || t.includes('reference')) return '#2e1a1a';
    if (['constant','step','sinewave'].includes(t)) return '#1a3a2e';
    return '#1a2235';
  }
  function blockBorder(type) {
    const t = (type || '').toLowerCase();
    if (['inport','in'].includes(t))  return '#00ff88';
    if (['outport','out'].includes(t)) return '#aa44ff';
    if (t.includes('sfunc') || t.includes('reference')) return '#ff4466';
    if (t.includes('subsystem'))      return '#0099cc';
    return '#1e3a5a';
  }

  // Draw connections
  const linkGroup = g.append('g');
  connections.forEach(c => {
    const src = positions[c.from];
    const dst = positions[c.to];
    if (!src || !dst) return;

    const x1 = src.x + NODE_W;
    const y1 = src.y + NODE_H / 2;
    const x2 = dst.x;
    const y2 = dst.y + NODE_H / 2;
    const mx = (x1 + x2) / 2;

    linkGroup.append('path')
      .attr('class', 'link')
      .attr('d', `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`)
      .attr('marker-end', 'url(#arrow)');
  });

  // Draw nodes
  const nodeGroup = g.append('g');
  blocks.forEach(b => {
    const pos = positions[b.id];
    if (!pos) return;

    const node = nodeGroup.append('g')
      .attr('class', 'block-node')
      .attr('transform', `translate(${pos.x},${pos.y})`)
      .style('cursor', 'pointer');

    node.append('rect')
      .attr('width', NODE_W)
      .attr('height', NODE_H)
      .attr('rx', 6)
      .attr('fill', blockColor(b.type))
      .attr('stroke', blockBorder(b.type))
      .attr('stroke-width', 1.5);

    // Type label
    node.append('text')
      .attr('x', NODE_W / 2)
      .attr('y', 13)
      .attr('text-anchor', 'middle')
      .attr('fill', '#88aacc')
      .attr('font-size', '8px')
      .text(b.type || '');

    // Name label (truncated)
    const name = (b.name || '').replace(/\\n/g, ' ');
    node.append('text')
      .attr('x', NODE_W / 2)
      .attr('y', 27)
      .attr('text-anchor', 'middle')
      .attr('fill', '#e0eeff')
      .attr('font-size', '9px')
      .attr('font-weight', '600')
      .text(name.length > 14 ? name.slice(0, 13) + '…' : name);

    // Tooltip on hover
    node.append('title').text(`[${b.type}] ${b.name}`);
  });

  // Auto fit
  setTimeout(() => fitDiagram(), 100);
}

function fitDiagram() {
  const svg = document.getElementById('diagram-svg');
  const g   = svg.querySelector('.zoom-group');
  if (!g || !zoomBehavior) return;

  const svgRect = svg.getBoundingClientRect();
  const gRect   = g.getBoundingClientRect();
  if (gRect.width === 0) return;

  const scaleX = (svgRect.width  - 80) / gRect.width;
  const scaleY = (svgRect.height - 80) / gRect.height;
  const scale  = Math.min(scaleX, scaleY, 2);

  const tx = (svgRect.width  - gRect.width  * scale) / 2;
  const ty = (svgRect.height - gRect.height * scale) / 2;

  d3.select('#diagram-svg').transition().duration(400)
    .call(zoomBehavior.transform, d3.zoomIdentity.translate(tx, ty).scale(scale));
}

function resetZoom() {
  d3.select('#diagram-svg').transition().duration(400)
    .call(zoomBehavior.transform, d3.zoomIdentity);
}

// ---- Copy & Download ----
async function copyCode() {
  if (!currentCode) return;
  try {
    await navigator.clipboard.writeText(currentCode);
    toast('📋 Code copied to clipboard!');
  } catch {
    toast('❌ Copy failed', true);
  }
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
  toast('⬇ Downloading...');
}

// ---- Toast ----
function toast(msg, isError = false) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.style.borderColor = isError ? 'var(--red)' : 'var(--cyan)';
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 3000);
}

// ---- Background Particles ----
function initParticles() {
  const canvas = document.getElementById('bg-canvas');
  const ctx = canvas.getContext('2d');
  canvas.width  = window.innerWidth;
  canvas.height = window.innerHeight;

  const particles = Array.from({ length: 60 }, () => ({
    x: Math.random() * canvas.width,
    y: Math.random() * canvas.height,
    vx: (Math.random() - 0.5) * 0.3,
    vy: (Math.random() - 0.5) * 0.3,
    r:  Math.random() * 1.5 + 0.5,
    a:  Math.random()
  }));

  function draw() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    particles.forEach(p => {
      p.x += p.vx; p.y += p.vy;
      if (p.x < 0) p.x = canvas.width;
      if (p.x > canvas.width) p.x = 0;
      if (p.y < 0) p.y = canvas.height;
      if (p.y > canvas.height) p.y = 0;
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(0,212,255,${p.a * 0.4})`;
      ctx.fill();
    });
    requestAnimationFrame(draw);
  }
  draw();

  window.addEventListener('resize', () => {
    canvas.width  = window.innerWidth;
    canvas.height = window.innerHeight;
  });
}