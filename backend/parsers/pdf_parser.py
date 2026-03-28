# PDF Parser for SimToC
# Graceful import — won't crash if PyMuPDF not installed

try:
    import fitz
    FITZ_AVAILABLE = True
except ImportError:
    FITZ_AVAILABLE = False

import re

BLOCK_KEYWORDS = {
    'transferfcn':       ('TransferFcn',            10),
    'transfer fcn':      ('TransferFcn',            10),
    'transfer function': ('TransferFcn',            10),
    'pidcontroller':     ('PIDController',          10),
    'pid controller':    ('PIDController',          10),
    'unitdelay':         ('UnitDelay',              10),
    'unit delay':        ('UnitDelay',              10),
    'zero-order hold':   ('ZeroOrderHold',          10),
    'zero order hold':   ('ZeroOrderHold',          10),
    'discretefilter':    ('DiscreteFilter',         10),
    'sinewave':          ('SineWave',               10),
    'sine wave':         ('SineWave',               10),
    'pulsegenerator':    ('DiscretePulseGenerator', 10),
    'pulse generator':   ('DiscretePulseGenerator', 10),
    'state space':       ('StateSpace',             10),
    'ratelimiter':       ('RateLimiter',            10),
    'rate limiter':      ('RateLimiter',            10),
    'subsystem':         ('SubSystem',               9),
    'integrator':        ('Integrator',              9),
    'derivative':        ('Derivative',              9),
    'saturation':        ('Saturation',              9),
    'saturate':          ('Saturation',              9),
    'constant':          ('Constant',                9),
    'inport':            ('Inport',                  9),
    'outport':           ('Outport',                 9),
    'demux':             ('Demux',                   9),
    'scope':             ('Scope',                   9),
    'display':           ('Display',                 9),
    'switch':            ('Switch',                  9),
    'product':           ('Product',                 8),
    'lookup':            ('LookupTable',             8),
    'delay':             ('UnitDelay',               8),
    'gain':              ('Gain',                    8),
    'sum':               ('Sum',                     8),
    'mux':               ('Mux',                     8),
    'step':              ('Step',                    8),
    'pid':               ('PIDController',           7),
    'sin':               ('SineWave',                7),
}

CONNECTION_PATTERNS = [
    r'(\w[\w\s]*?)\s*[-\u2014\u2192>]+\s*(\w[\w\s]*)',
    r'(\w[\w\s]*?)\s+connects?\s+to\s+(\w[\w\s]*)',
    r'output\s+of\s+(\w[\w\s]*?)\s+(?:goes?\s+to|feeds?)\s+(\w[\w\s]*)',
]


def parse_pdf(filepath):
    if not FITZ_AVAILABLE:
        raise ValueError(
            "PyMuPDF (fitz) is not installed. "
            "Add 'pymupdf' to requirements.txt and redeploy."
        )

    blocks = []
    connections = []
    counter = [0]

    def nid():
        counter[0] += 1
        return str(counter[0])

    doc = fitz.open(filepath)
    full_text = ""
    word_positions = []  # (x, y, word)

    for page in doc:
        full_text += page.get_text() + "\n"
        for block in page.get_text("dict")["blocks"]:
            if block.get("type") == 0:
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        for word in span["text"].split():
                            if word.strip():
                                bbox = span["bbox"]
                                word_positions.append((
                                    bbox[0], bbox[1], word.strip()
                                ))
    doc.close()

    # Strategy 1 — structured block listings
    structured = _extract_structured(full_text)
    if structured:
        sx, sy = 160, 80
        for i, (btype, bname, params) in enumerate(structured):
            bid = nid()
            blocks.append({
                'id': bid, 'type': btype, 'name': bname,
                'x': float(50 + (i % 5) * sx),
                'y': float(50 + (i // 5) * sy),
                'params': params
            })

    # Strategy 2 — keyword scan
    if not blocks:
        blocks = _keyword_scan(full_text, nid)

    # Strategy 3 — spatial word clusters
    if not blocks and word_positions:
        blocks = _spatial_cluster(word_positions, nid)

    if not blocks:
        raise ValueError(
            "No Simulink blocks found in PDF.\n"
            "For best results use a PDF exported from MATLAB, "
            "or upload the .slx / .mdl file directly."
        )

    # Connections
    name_to_id = {}
    for b in blocks:
        name_to_id[b['name'].lower()] = b['id']
        name_to_id[b['type'].lower()] = b['id']

    connections = _extract_connections(full_text, name_to_id, blocks)

    if not connections and len(blocks) > 1:
        sb = sorted(blocks, key=lambda b: (b['x'], b['y']))
        for i in range(len(sb) - 1):
            connections.append({
                'from': sb[i]['id'], 'to': sb[i+1]['id'],
                'src_port': 1, 'dst_port': 1
            })

    return blocks, connections, 0.1, 10.0


def _extract_structured(text):
    found = []
    for line in text.split('\n'):
        line = line.strip()
        if not line or len(line) > 200:
            continue
        # Pattern: Name (BlockType) or [BlockType] Name
        m = re.match(
            r'^["\']?(\w[\w\s]*?)["\']?\s*[\(\[]\s*([A-Za-z][\w\s]*?)\s*[\)\]]'
            r'(?:\s+(.*))?$', line
        )
        if m:
            name  = m.group(1).strip()
            btype = _classify(m.group(2).strip())
            params = _parse_params(m.group(3) or '')
            found.append((btype, name, params))
    return found


def _keyword_scan(text, nid):
    blocks = []
    tl     = text.lower()
    seen   = set()

    for kw, (btype, _) in sorted(BLOCK_KEYWORDS.items(), key=lambda x: -x[1][1]):
        start = 0
        while True:
            idx = tl.find(kw, start)
            if idx == -1:
                break
            start = idx + 1

            ctx   = text[max(0, idx-50): idx+len(kw)+50]
            name  = _extract_nearby_name(ctx, kw, btype)
            if name not in seen:
                seen.add(name)
                val_m  = re.search(r'(?:value|gain|k)\s*[=:]\s*([-\d.]+)', ctx, re.I)
                params = {}
                if val_m:
                    params['Value'] = val_m.group(1)
                    if btype == 'Gain':
                        params['Gain'] = val_m.group(1)

                bid = nid()
                blocks.append({
                    'id': bid, 'type': btype, 'name': name,
                    'x': 0.0, 'y': 0.0, 'params': params
                })

    sx, sy = 160, 80
    for i, b in enumerate(blocks):
        b['x'] = float(50 + (i % 5) * sx)
        b['y'] = float(50 + (i // 5) * sy)

    return blocks


def _spatial_cluster(word_positions, nid):
    blocks = []
    used   = set()
    wp     = sorted(word_positions, key=lambda w: (w[1], w[0]))

    for i, (x, y, word) in enumerate(wp):
        if i in used:
            continue
        cluster = [word]
        used.add(i)
        for j, (xj, yj, wj) in enumerate(wp):
            if j not in used and abs(xj-x) < 80 and abs(yj-y) < 25:
                cluster.append(wj)
                used.add(j)

        text  = ' '.join(cluster)
        btype = _classify(text)
        if btype != 'SubSystem' or 'subsystem' in text.lower():
            bid = nid()
            blocks.append({
                'id': bid, 'type': btype,
                'name': text[:20].strip() or f'{btype}_{bid}',
                'x': float(x), 'y': float(y), 'params': {}
            })
    return blocks


def _extract_connections(text, name_to_id, blocks):
    conns = []
    seen  = set()
    for pat in CONNECTION_PATTERNS:
        for m in re.finditer(pat, text, re.I):
            sn = m.group(1).strip().lower()
            dn = m.group(2).strip().lower()
            sid = name_to_id.get(sn) or next(
                (b['id'] for b in blocks if sn in b['name'].lower()), None)
            did = name_to_id.get(dn) or next(
                (b['id'] for b in blocks if dn in b['name'].lower()), None)
            if sid and did and sid != did:
                k = (sid, did)
                if k not in seen:
                    seen.add(k)
                    conns.append({'from': sid, 'to': did,
                                  'src_port': 1, 'dst_port': 1})
    return conns


def _classify(text):
    tl = text.lower()
    best, score = 'SubSystem', 0
    for kw, (btype, s) in BLOCK_KEYWORDS.items():
        if kw in tl and s > score:
            best, score = btype, s
    return best


def _extract_nearby_name(ctx, kw, btype):
    m = re.search(r'\b([A-Z][a-zA-Z0-9_]{1,20})\b', ctx)
    if m and m.group(1).lower() != kw:
        return m.group(1)
    return f'{btype}1'


def _parse_params(raw):
    params = {}
    for m in re.finditer(r'(\w+)\s*[=:]\s*([-\d.eE+]+|\w+)', raw):
        params[m.group(1)] = m.group(2)
    return params