import fitz  # PyMuPDF
import re

# ================================================================
# PDF Parser — extracts Simulink block info from PDF documents
#
# Handles 3 cases:
#   1. PDF exported from MATLAB (has structured text with block names)
#   2. PDF report listing blocks and connections in text form
#   3. PDF with just a diagram image (falls back to OCR-style extraction)
# ================================================================

# Map of keyword -> (BlockType, priority)
BLOCK_KEYWORDS = {
    # exact Simulink block names first (higher priority)
    'transferfcn':        ('TransferFcn',       10),
    'transfer fcn':       ('TransferFcn',       10),
    'transfer function':  ('TransferFcn',       10),
    'pidcontroller':      ('PIDController',     10),
    'pid controller':     ('PIDController',     10),
    'unitdelay':          ('UnitDelay',         10),
    'unit delay':         ('UnitDelay',         10),
    'zeroorhold':         ('ZeroOrderHold',     10),
    'zero-order hold':    ('ZeroOrderHold',     10),
    'zero order hold':    ('ZeroOrderHold',     10),
    'discretefilter':     ('DiscreteFilter',    10),
    'sinewave':           ('SineWave',          10),
    'sine wave':          ('SineWave',          10),
    'pulsegenerator':     ('DiscretePulseGenerator', 10),
    'pulse generator':    ('DiscretePulseGenerator', 10),
    'statefeedback':      ('StateSpace',        10),
    'state space':        ('StateSpace',        10),
    'ratelimiter':        ('RateLimiter',       10),
    'rate limiter':       ('RateLimiter',       10),
    'subsystem':          ('SubSystem',          9),
    'integrator':         ('Integrator',         9),
    'derivative':         ('Derivative',         9),
    'saturation':         ('Saturation',         9),
    'saturate':           ('Saturation',         9),
    'constant':           ('Constant',           9),
    'inport':             ('Inport',             9),
    'outport':            ('Outport',            9),
    'demux':              ('Demux',              9),
    'scope':              ('Scope',              9),
    'switch':             ('Switch',             9),
    'product':            ('Product',            8),
    'lookup':             ('LookupTable',        8),
    'delay':              ('UnitDelay',          8),
    'clock':              ('SineWave',           8),
    'gain':               ('Gain',               8),
    'sum':                ('Sum',                8),
    'mux':                ('Mux',                8),
    'step':               ('Step',               8),
    'sin':                ('SineWave',           7),
    'pid':                ('PIDController',      7),
}

# Patterns that indicate a connection line in PDF text
CONNECTION_PATTERNS = [
    r'(\w[\w\s]*?)\s*[-—→>]+\s*(\w[\w\s]*)',   # A -> B  or  A — B
    r'(\w[\w\s]*?)\s+connects?\s+to\s+(\w[\w\s]*)',
    r'output\s+of\s+(\w[\w\s]*?)\s+(?:goes?\s+to|feeds?)\s+(\w[\w\s]*)',
    r'(\w[\w\s]*?)\s+(?:drives?|feeds?)\s+(\w[\w\s]*)',
]


def parse_pdf(filepath):
    blocks = []
    connections = []
    counter = [0]

    def nid():
        counter[0] += 1
        return str(counter[0])

    doc = fitz.open(filepath)

    # ---- Extract all text with position info ----
    all_words   = []   # (x0, y0, x1, y1, word, page_num)
    full_text   = ""
    page_texts  = []

    for page_num, page in enumerate(doc):
        page_text = page.get_text()
        full_text += page_text + "\n"
        page_texts.append(page_text)

        # Get words with positions for spatial analysis
        for block in page.get_text("dict")["blocks"]:
            if block.get("type") == 0:  # text block
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        for word in span.get("text", "").split():
                            if word.strip():
                                bbox = span["bbox"]
                                all_words.append((
                                    bbox[0], bbox[1], bbox[2], bbox[3],
                                    word.strip(), page_num
                                ))

    doc.close()

    # ---- Strategy 1: Look for structured Simulink block listings ----
    # Patterns like "Block: Gain1 (Gain)" or "Gain1 [Gain]"
    structured_blocks = _extract_structured_blocks(full_text)

    if structured_blocks:
        spacing_x, spacing_y = 160, 80
        for i, (btype, bname, bparams) in enumerate(structured_blocks):
            bid = nid()
            blocks.append({
                'id':     bid,
                'type':   btype,
                'name':   bname,
                'x':      float(50 + (i % 5) * spacing_x),
                'y':      float(50 + (i // 5) * spacing_y),
                'params': bparams
            })

    # ---- Strategy 2: Keyword scanning with deduplication ----
    if not blocks:
        blocks = _keyword_scan(full_text, nid)

    # ---- Strategy 3: Spatial word clustering ----
    if not blocks and all_words:
        blocks = _spatial_blocks(all_words, nid)

    if not blocks:
        raise ValueError(
            "No recognizable Simulink blocks found in this PDF.\n"
            "Tip: For best results use a PDF exported directly from MATLAB "
            "or a PDF that lists block names as text."
        )

    # ---- Extract connections from text ----
    name_to_id = {b['name'].lower(): b['id'] for b in blocks}
    for b in blocks:
        name_to_id[b['type'].lower()] = b['id']

    connections = _extract_connections(full_text, name_to_id, blocks)

    # If no connections found, chain blocks left-to-right by position
    if not connections and len(blocks) > 1:
        sorted_b = sorted(blocks, key=lambda b: (b['x'], b['y']))
        for i in range(len(sorted_b) - 1):
            connections.append({
                'from':     sorted_b[i]['id'],
                'to':       sorted_b[i+1]['id'],
                'src_port': 1,
                'dst_port': 1
            })

    return blocks, connections, 0.1, 10.0


# ================================================================
# Helpers
# ================================================================

def _extract_structured_blocks(text):
    """
    Look for lines like:
      Block "Gain1" (Gain)  Value: 2.0
      [Constant] Input1 = 10
      Gain - Gain1 - Gain: 5
    """
    found = []
    lines = text.split('\n')

    for line in lines:
        line = line.strip()
        if not line or len(line) > 200:
            continue

        # Pattern: "BlockType BlockName params"
        # e.g. "Constant Input1 Value=10"
        m = re.match(
            r'^(?:Block\s+)?["\']?(\w[\w\s]*?)["\']?\s*'
            r'[\(\[]\s*([A-Za-z][\w\s]*?)\s*[\)\]]'
            r'(?:\s+(.*))?$',
            line
        )
        if m:
            name  = m.group(1).strip()
            btype = _classify_type(m.group(2).strip())
            raw   = m.group(3) or ''
            params = _parse_inline_params(raw)
            found.append((btype, name, params))
            continue

        # Pattern: "BlockType: Name = value"
        m = re.match(
            r'^([A-Za-z][\w\s]{2,20}):\s+(\w[\w\s]*?)'
            r'(?:\s*[=:]\s*(.+))?$',
            line
        )
        if m:
            btype_raw = m.group(1).strip()
            btype = _classify_type(btype_raw)
            if btype != 'SubSystem' or btype_raw.lower() in ('subsystem','sub system'):
                name   = m.group(2).strip()
                raw    = m.group(3) or ''
                params = _parse_inline_params(raw)
                found.append((btype, name, params))

    return found


def _keyword_scan(text, nid):
    """
    Scan text for known block keywords.
    Extract actual names when possible (e.g. 'Gain1', 'Sum_A').
    """
    blocks = []
    tl = text.lower()
    seen_names = set()

    # Try to find "BlockType named X" or "X (BlockType)"
    for keyword, (btype, priority) in sorted(
        BLOCK_KEYWORDS.items(), key=lambda x: -x[1][1]
    ):
        # Find all occurrences
        start = 0
        while True:
            idx = tl.find(keyword, start)
            if idx == -1:
                break
            start = idx + 1

            # Extract surrounding context (50 chars each side)
            ctx_start = max(0, idx - 50)
            ctx_end   = min(len(text), idx + len(keyword) + 50)
            ctx       = text[ctx_start:ctx_end]

            # Try to find a name near this keyword
            name = _extract_name_near(ctx, keyword, btype)

            if name not in seen_names:
                seen_names.add(name)
                # Try to extract params
                params = {}
                # Look for value after = sign
                val_m = re.search(
                    r'(?:value|gain|k)\s*[=:]\s*([-\d.]+)',
                    ctx, re.IGNORECASE
                )
                if val_m:
                    params['Value'] = val_m.group(1)
                    if btype == 'Gain':
                        params['Gain'] = val_m.group(1)

                bid = nid()
                blocks.append({
                    'id':     bid,
                    'type':   btype,
                    'name':   name,
                    'x':      0.0,
                    'y':      0.0,
                    'params': params
                })

    # Assign grid positions
    spacing_x, spacing_y = 160, 80
    for i, b in enumerate(blocks):
        b['x'] = float(50 + (i % 5) * spacing_x)
        b['y'] = float(50 + (i // 5) * spacing_y)

    return blocks


def _spatial_blocks(words, nid):
    """
    Group words spatially into block-like clusters
    and classify each cluster.
    """
    blocks = []
    used   = set()

    # Sort by y then x (top-to-bottom, left-to-right)
    words = sorted(words, key=lambda w: (w[1], w[0]))

    for i, (x0, y0, x1, y1, word, pg) in enumerate(words):
        if i in used:
            continue

        # Collect nearby words into a cluster
        cluster_words = [word]
        used.add(i)
        for j, (x0j, y0j, x1j, y1j, wj, pgj) in enumerate(words):
            if j in used or pgj != pg:
                continue
            if (abs(x0j - x0) < 80 and abs(y0j - y0) < 30):
                cluster_words.append(wj)
                used.add(j)

        cluster_text = ' '.join(cluster_words).lower()
        btype = _classify_type(cluster_text)

        # Only keep if we recognised a real block type
        if btype != 'SubSystem' or 'subsystem' in cluster_text:
            name  = ' '.join(cluster_words)[:20].strip()
            bid   = nid()
            blocks.append({
                'id':     bid,
                'type':   btype,
                'name':   name or f'{btype}_{bid}',
                'x':      float(x0),
                'y':      float(y0),
                'params': {}
            })

    return blocks


def _extract_connections(text, name_to_id, blocks):
    """
    Look for arrow-style connection text and return connection list.
    """
    connections = []
    seen = set()

    for pattern in CONNECTION_PATTERNS:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            src_name = m.group(1).strip().lower()
            dst_name = m.group(2).strip().lower()

            src_id = name_to_id.get(src_name)
            dst_id = name_to_id.get(dst_name)

            if not src_id:
                # fuzzy: check if any block name contains src_name
                for b in blocks:
                    if src_name in b['name'].lower():
                        src_id = b['id']
                        break
            if not dst_id:
                for b in blocks:
                    if dst_name in b['name'].lower():
                        dst_id = b['id']
                        break

            if src_id and dst_id and src_id != dst_id:
                k = (src_id, dst_id)
                if k not in seen:
                    seen.add(k)
                    connections.append({
                        'from': src_id, 'to': dst_id,
                        'src_port': 1, 'dst_port': 1
                    })

    return connections


def _classify_type(text):
    tl = text.lower().strip()
    best_type  = 'SubSystem'
    best_score = 0
    for kw, (btype, score) in BLOCK_KEYWORDS.items():
        if kw in tl and score > best_score:
            best_type  = btype
            best_score = score
    return best_type


def _extract_name_near(context, keyword, btype):
    """Try to find the instance name near a keyword."""
    # Look for CamelCase or underscore_name adjacent to keyword
    m = re.search(
        r'\b([A-Z][a-zA-Z0-9_]{1,20})\b',
        context
    )
    if m:
        candidate = m.group(1)
        # Skip if it IS the keyword itself
        if candidate.lower() != keyword.lower():
            return candidate

    # Fallback: use keyword + counter
    return f'{btype}1'


def _parse_inline_params(raw):
    """Parse 'Key=Value Key2=Value2' style param strings."""
    params = {}
    for m in re.finditer(r'(\w+)\s*[=:]\s*([-\d.eE+]+|\w+)', raw):
        params[m.group(1)] = m.group(2)
    return params