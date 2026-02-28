import re

def parse_mdl(filepath):
    blocks = []
    connections = []
    counter = [0]

    def nid():
        counter[0] += 1
        return str(counter[0])

    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()

    content = content.replace('\r\n', '\n').replace('\r', '\n')

    # ---- Parse all Block sections ----
    block_pattern = re.compile(
        r'^\s*Block\s*\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}',
        re.MULTILINE | re.DOTALL
    )

    for m in block_pattern.finditer(content):
        bc = m.group(1)
        btype = _val(bc, 'BlockType')
        bname = _val(bc, 'Name')
        pos   = _val(bc, 'Position')

        if not btype:
            continue

        btype = btype.strip().strip('"')
        bname = (bname or '').strip().strip('"').strip()

        x, y = 0.0, 0.0
        if pos:
            nums = re.findall(r'[-\d.]+', pos)
            if len(nums) >= 2:
                try:
                    x, y = float(nums[0]), float(nums[1])
                except:
                    pass

        params = {}
        for line in bc.split('\n'):
            line = line.strip()
            if not line or '{' in line or '}' in line:
                continue
            parts = line.split(None, 1)
            if len(parts) == 2:
                k = parts[0].strip()
                v = parts[1].strip().strip('"')
                params[k] = v

        bid = nid()
        bname = bname or f'Block_{bid}'
        btype = _normalize(btype)

        blocks.append({
            'id':     bid,
            'type':   btype,
            'name':   bname,
            'x':      x,
            'y':      y,
            'params': params
        })

    # ---- Build name -> id map (with stripped/normalized names) ----
    name_to_id = {}
    for b in blocks:
        # Store multiple variants of the name for fuzzy matching
        raw   = b['name']
        clean = raw.strip()
        name_to_id[raw]   = b['id']
        name_to_id[clean] = b['id']

    def resolve(name):
        name = str(name).strip().strip('"')
        if name in name_to_id:
            return name_to_id[name]
        # Try stripped version
        stripped = name.strip()
        if stripped in name_to_id:
            return name_to_id[stripped]
        return None

    # ---- Parse Line connections ----
    line_pattern = re.compile(
        r'Line\s*\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}',
        re.DOTALL
    )

    for lm in line_pattern.finditer(content):
        lc = lm.group(1)
        src_name = _val(lc, 'SrcBlock')
        dst_name = _val(lc, 'DstBlock')

        if src_name and dst_name:
            src_id = resolve(src_name)
            dst_id = resolve(dst_name)
            if src_id and dst_id and src_id != dst_id:
                connections.append({'from': src_id, 'to': dst_id})

        # Branch connections
        for bm in re.finditer(r'Branch\s*\{([^{}]*)\}', lc, re.DOTALL):
            dst2 = _val(bm.group(1), 'DstBlock')
            if src_name and dst2:
                src_id = resolve(src_name)
                dst_id = resolve(dst2)
                if src_id and dst_id and src_id != dst_id:
                    connections.append({'from': src_id, 'to': dst_id})

    # Remove duplicate connections
    seen = set()
    unique = []
    for c in connections:
        key = (c['from'], c['to'])
        if key not in seen:
            seen.add(key)
            unique.append(c)

    return blocks, unique


def _normalize(btype):
    m = {
        'S-Function': 'SFunction', 'S-function': 'SFunction',
        'ComplexToRealImag': 'ComplexToRealImag',
        'RealImagToComplex': 'RealImagToComplex',
        'Concatenate': 'Concatenate',
        'DiscretePulseGenerator': 'DiscretePulseGenerator',
        'RelationalOperator': 'RelationalOperator',
        'Math': 'MathFunction',
        'Trigonometry': 'Trigonometry',
        'Logic': 'LogicOperator',
        'ToWorkspace': 'ToWorkspace',
        'FromWorkspace': 'FromWorkspace',
        'DataTypeConversion': 'DataTypeConversion',
        'DiscreteFilter': 'DiscreteFilter',
        'DiscreteTransferFcn': 'DiscreteTransferFcn',
        'UnitDelay': 'UnitDelay',
        'ZeroOrderHold': 'ZeroOrderHold',
        'Quantizer': 'Quantizer',
        'Memory': 'Memory',
        'BusCreator': 'BusCreator',
        'BusSelector': 'BusSelector',
        'MultiPortSwitch': 'MultiPortSwitch',
        'Selector': 'Selector',
        'Reshape': 'Reshape',
        'DotProduct': 'DotProduct',
        'Display': 'Display',
        'Terminator': 'Terminator',
        'Goto': 'Goto',
        'From': 'From',
        'EnablePort': 'EnablePort',
        'Merge': 'Merge',
    }
    return m.get(btype, btype)


def _val(content, key):
    m = re.search(
        rf'^\s*{re.escape(key)}\s+"?([^"\n]+)"?\s*$',
        content, re.MULTILINE
    )
    return m.group(1).strip().strip('"') if m else None