// =========================================
// SimToC — Frontend Script
// =========================================

const API = 'https://simtoc-converter.onrender.com';
// When running locally change above to: 'http://localhost:8080'

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
    setInterval(checkStatus, 15000);
});

// ---- Status ----
async function checkStatus() {
    try {
        const r = await fetch(`${API}/health`);
        if (r.ok) {
            document.getElementById('status-dot').className = 'status-dot on';
            document.getElementById('status-text').textContent = 'Backend Online';
        } else { setOff(); }
    } catch { setOff(); }
}

function setOff() {
    document.getElementById('status-dot').className = 'status-dot';
    document.getElementById('status-text').textContent = 'Backend Offline';
}

// ---- Drag & Drop ----
function setupDrop() {
    const zone = document.getElementById('upload-zone');
    zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('drag'); });
    zone.addEventListener('dragleave', () => zone.classList.remove('drag'));
    zone.addEventListener('drop', e => {
        e.preventDefault(); zone.classList.remove('drag');
        if (e.dataTransfer.files[0]) handleFile(e.dataTransfer.files[0]);
    });
    zone.addEventListener('click', e => {
        if (e.target.tagName !== 'BUTTON') document.getElementById('file-input').click();
    });
}

// ---- File Handling ----
function handleFile(file) {
    const ok = ['slx','mdl','pdf','png','jpg','jpeg','bmp'];
    const ext = file.name.split('.').pop().toLowerCase();
    if (!ok.includes(ext)) { toast('❌ Unsupported file type', true); return; }

    selectedFile = file;

    const icons = { slx:'🔧', mdl:'📐', pdf:'📄', png:'🖼️', jpg:'🖼️', jpeg:'🖼️', bmp:'🖼️' };
    document.getElementById('file-icon-display').textContent = icons[ext] || '📄';
    document.getElementById('file-name-display').textContent = file.name;
    document.getElementById('file-size-display').textContent = fmtBytes(file.size);
    document.getElementById('upload-zone').style.display = 'none';
    document.getElementById('file-badge-wrap').style.display = 'block';
    document.getElementById('convert-btn').disabled = false;
}

function removeFile() {
    selectedFile = null;
    document.getElementById('file-input').value = '';
    document.getElementById('file-badge-wrap').style.display = 'none';
    document.getElementById('upload-zone').style.display = 'block';
    document.getElementById('convert-btn').disabled = true;
    document.getElementById('stats-grid').style.display = 'none';
}

function fmtBytes(b) {
    if (b < 1024) return b + ' B';
    if (b < 1048576) return (b/1024).toFixed(1) + ' KB';
    return (b/1048576).toFixed(1) + ' MB';
}

// ---- Convert ----
async function startConvert() {
    if (!selectedFile) return;

    document.getElementById('loading').style.display = 'flex';

    const steps = [
        'Parsing block diagram...',
        'Mapping signal flows...',
        'Identifying block types...',
        'Generating C code...',
        'Building diagram data...',
        'Finalizing output...'
    ];

    let si = 0;
    const subEl = document.getElementById('loading-sub');
    const interval = setInterval(() => {
        subEl.textContent = steps[si % steps.length];
        si++;
    }, 1000);

    try {
        const fd = new FormData();
        fd.append('file', selectedFile);

        const res = await fetch(`${API}/convert`, { method:'POST', body: fd });
        const data = await res.json();
        clearInterval(interval);

        if (!res.ok || data.error) {
            toast('❌ ' + (data.error || 'Conversion failed'), true);
            return;
        }

        currentCode = data.c_code;

        // Stats
        document.getElementById('s-blocks').textContent = data.block_count;
        document.getElementById('s-conns').textContent = data.connection_count;
        document.getElementById('s-lines').textContent = data.c_code.split('\n').length;
        document.getElementById('stats-grid').style.display = 'grid';

        // Code display
        document.getElementById('code-placeholder').style.display = 'none';
        const el = document.getElementById('code-el');
        el.textContent = data.c_code;
        document.getElementById('code-pre').style.display = 'block';
        hljs.highlightElement(el);

        // Buttons
        document.getElementById('copy-btn').style.display = 'inline-flex';
        document.getElementById('dl-btn').style.display = 'inline-flex';

        // Diagram
        drawDiagram(data.diagram);

        toast('✅ Conversion complete!');

    } catch(err) {
        clearInterval(interval);
        toast('❌ Cannot reach backend. Check connection.', true);
        console.error(err);
    } finally {
        document.getElementById('loading').style.display = 'none';
    }
}

// ---- D3 Diagram ----
function drawDiagram(data) {
    const { blocks, connections } = data;
    if (!blocks || !blocks.length) return;

    document.getElementById('diag-placeholder').style.display = 'none';
    const svg = document.getElementById('diag-svg');
    svg.style.display = 'block';

    const wrap = document.getElementById('diagram-wrap');
    const W = wrap.clientWidth, H = wrap.clientHeight;

    const s = d3.select('#diag-svg');
    s.selectAll('*').remove();
    s.attr('viewBox', `0 0 ${W} ${H}`);

    // Defs
    const defs = s.append('defs');

    defs.append('marker').attr('id','arr')
        .attr('viewBox','0 -5 10 10').attr('refX',10).attr('refY',0)
        .attr('markerWidth',7).attr('markerHeight',7).attr('orient','auto')
        .append('path').attr('d','M0,-5L10,0L0,5').attr('fill','rgba(0,212,255,.8)');

    const gf = defs.append('filter').attr('id','glow');
    gf.append('feGaussianBlur').attr('stdDeviation','3').attr('result','cb');
    const fm = gf.append('feMerge');
    fm.append('feMergeNode').attr('in','cb');
    fm.append('feMergeNode').attr('in','SourceGraphic');

    const g = s.append('g');

    // Layout
    const BW = 100, BH = 48;
    const allZero = blocks.every(b => b.x === 0 && b.y === 0);
    const cols = Math.ceil(Math.sqrt(blocks.length));

    const laid = blocks.map((b, i) => ({
        ...b,
        px: allZero ? 40 + (i % cols) * 160 : b.x,
        py: allZero ? 40 + Math.floor(i / cols) * 110 : b.y
    }));

    const maxX = Math.max(...laid.map(b => b.px)) + BW + 20;
    const maxY = Math.max(...laid.map(b => b.py)) + BH + 20;
    const sc = Math.min((W - 40) / maxX, (H - 40) / maxY, 1.8);

    const byId = {};
    laid.forEach(b => { byId[b.id] = b; });

    const colors = {
        Gain:'#4d9fff', Sum:'#00ff88', Integrator:'#8b5cf6',
        Derivative:'#8b5cf6', Inport:'#00d4ff', Outport:'#ff6b35',
        Constant:'#ffd700', Scope:'#ff4d88', PIDController:'#8b5cf6',
        TransferFcn:'#4d9fff', Saturation:'#ff6b35', Step:'#00ff88',
        SineWave:'#00d4ff', Product:'#4d9fff', Switch:'#ffd700'
    };

    // Connections
    connections.forEach((c, i) => {
        const src = byId[c.from] || byId[String(c.from)];
        const dst = byId[c.to]   || byId[String(c.to)];
        if (!src || !dst) return;

        const x1 = src.px * sc + BW * sc / 2;
        const y1 = src.py * sc + BH * sc / 2;
        const x2 = dst.px * sc + BW * sc / 2;
        const y2 = dst.py * sc + BH * sc / 2;

        g.append('line')
            .attr('x1',x1).attr('y1',y1)
            .attr('x2',x1).attr('y2',y1)
            .attr('stroke','rgba(0,212,255,.5)')
            .attr('stroke-width',2)
            .attr('marker-end','url(#arr)')
            .transition().delay(i*120+350).duration(550)
            .attr('x2',x2).attr('y2',y2);
    });

    // Blocks
    laid.forEach((b, i) => {
        const bx = b.px * sc, by = b.py * sc;
        const bw = BW * sc, bh = BH * sc;
        const col = colors[b.type] || '#334155';

        const bg = g.append('g').attr('opacity',0)
            .attr('transform', `translate(${bx},${by})`);

        bg.append('rect')
            .attr('width',bw).attr('height',bh).attr('rx',8).attr('ry',8)
            .attr('fill', col+'22').attr('stroke', col)
            .attr('stroke-width',1.5).attr('filter','url(#glow)');

        bg.append('text')
            .attr('x',bw/2).attr('y',bh*.35)
            .attr('text-anchor','middle').attr('dominant-baseline','middle')
            .attr('fill',col)
            .attr('font-size', Math.max(8, 10*sc))
            .attr('font-family','Courier New').attr('font-weight','bold')
            .text(b.type);

        const label = b.name.length > 13 ? b.name.slice(0,13)+'…' : b.name;
        bg.append('text')
            .attr('x',bw/2).attr('y',bh*.68)
            .attr('text-anchor','middle').attr('dominant-baseline','middle')
            .attr('fill','rgba(255,255,255,.55)')
            .attr('font-size', Math.max(6, 8*sc))
            .attr('font-family','Courier New')
            .text(label);

        bg.transition().delay(i*80).duration(380).attr('opacity',1);
    });

    // Zoom
    const zoom = d3.zoom().scaleExtent([.25,5])
        .on('zoom', e => g.attr('transform', e.transform));
    s.call(zoom);
    window._zoom = zoom;
    window._svg = s;
}

function resetZoom() {
    if (window._svg && window._zoom)
        window._svg.transition().duration(450)
            .call(window._zoom.transform, d3.zoomIdentity);
}

// ---- Code actions ----
function copyCode() {
    navigator.clipboard.writeText(currentCode)
        .then(() => toast('✅ Copied to clipboard!'))
        .catch(() => toast('❌ Copy failed', true));
}

function openDownload() { document.getElementById('dl-modal').style.display = 'flex'; }
function closeDownload() { document.getElementById('dl-modal').style.display = 'none'; }
function setName(n) { document.getElementById('dl-name').value = n; }

async function doDownload() {
    if (!currentCode) return;
    const fname = document.getElementById('dl-name').value || 'model_output.c';

    if (window.showSaveFilePicker) {
        try {
            const handle = await window.showSaveFilePicker({
                suggestedName: fname,
                types: [{ description:'C Source File', accept:{'text/x-csrc':['.c']} }]
            });
            const w = await handle.createWritable();
            await w.write(currentCode);
            await w.close();
            toast('✅ File saved!');
            closeDownload();
            return;
        } catch(e) { /* user cancelled picker */ }
    }

    // Fallback
    const blob = new Blob([currentCode], { type:'text/x-csrc' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = fname;
    document.body.appendChild(a); a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    toast('✅ Download started!');
    closeDownload();
}

// ---- Toast ----
function toast(msg, isErr=false) {
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.className = 'toast show' + (isErr ? ' err' : '');
    setTimeout(() => t.className = 'toast', 3500);
}

// ---- Particles ----
function initParticles() {
    const c = document.getElementById('particle-canvas');
    const ctx = c.getContext('2d');

    const resize = () => { c.width = innerWidth; c.height = innerHeight; };
    resize();
    window.addEventListener('resize', resize);

    const pts = Array.from({length:55}, () => ({
        x: Math.random() * innerWidth,
        y: Math.random() * innerHeight,
        vx: (Math.random()-.5)*.4,
        vy: (Math.random()-.5)*.4,
        r: Math.random()*1.8+.4,
        op: Math.random()*.45+.1,
        col: Math.random()>.5 ? '0,212,255' : '77,159,255'
    }));

    (function frame() {
        ctx.clearRect(0,0,c.width,c.height);
        pts.forEach(p => {
            p.x += p.vx; p.y += p.vy;
            if (p.x < 0) p.x = c.width;
            if (p.x > c.width) p.x = 0;
            if (p.y < 0) p.y = c.height;
            if (p.y > c.height) p.y = 0;
            ctx.beginPath();
            ctx.arc(p.x,p.y,p.r,0,Math.PI*2);
            ctx.fillStyle = `rgba(${p.col},${p.op})`;
            ctx.fill();
        });
        for (let i=0;i<pts.length;i++) {
            for (let j=i+1;j<pts.length;j++) {
                const dx=pts[i].x-pts[j].x, dy=pts[i].y-pts[j].y;
                const d=Math.sqrt(dx*dx+dy*dy);
                if (d<90) {
                    ctx.beginPath();
                    ctx.moveTo(pts[i].x,pts[i].y);
                    ctx.lineTo(pts[j].x,pts[j].y);
                    ctx.strokeStyle=`rgba(0,212,255,${.07*(1-d/90)})`;
                    ctx.lineWidth=.5;ctx.stroke();
                }
            }
        }
        requestAnimationFrame(frame);
    })();
}