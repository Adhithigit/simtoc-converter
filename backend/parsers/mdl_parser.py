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

    # Build name->id map after parsing
    _parse_all_blocks(content, blocks, connections, counter)

    # Build name -> id lookup
    name_to_id = {}
    for b in blocks:
        name_to_id[b['name']] = b['id']
        name_to_id[b['name'].strip()] = b['id']

    # Resolve name-based connections to ID-based
    resolved = []
    for c in connections:
        src = str(c.get('from', '')).strip()
        dst = str(c.get('to', '')).strip()

        if not src.isdigit():
            src = str(name_to_id.get(src, src))
        if not dst.isdigit():
            dst = str(name_to_id.get(dst, dst))

        if src and dst and src != dst and src.isdigit() and dst.isdigit():
            resolved.append({'from': src, 'to': dst})

    return blocks, resolved


def _parse_all_blocks(content, blocks, connections, counter):
    def nid():
        counter[0] += 1
        return str(counter[0])

    # Find all Block sections using regex
    # Match Block { ... } at any nesting level
    pos = 0
    while pos < len(content):
        m = re.search(r'\bBlock\s*\{', content[pos:])
        if not m:
            break

        abs_start = pos + m.start()
        brace_open = pos + m.end() - 1

        # Extract content between braces
        bc = _get_brace_content(content, brace_open)
        if bc is None:
            pos = abs_start + 1
            continue

        block_type = _val(bc, 'BlockType')
        block_name = _val(bc, 'Name')
        pos_str    = _val(bc, 'Position')

        if block_type:
            block_type = block_type.strip().strip('"')
            block_type = _normalize(block_type)

            x, y = 0.0, 0.0
            if pos_str:
                nums = re.findall(r'[-\d.]+', pos_str)
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
            bname = (block_name or f'Block_{bid}').strip().strip('"')

            blocks.append({
                'id':     bid,
                'type':   block_type,
                'name':   bname,
                'x':      x,
                'y':      y,
                'params': params
            })

        pos = abs_start + len(bc) + 2
        if pos <= abs_start:
            pos = abs_start + 1

    # Parse Line connections
    for lm in re.finditer(r'\bLine\s*\{(.*?)\n[ \t]*\}', content, re.DOTALL):
        lc = lm.group(1)
        src = _val(lc, 'SrcBlock')
        dst = _val(lc, 'DstBlock')
        if src and dst:
            connections.append({'from': src.strip(), 'to': dst.strip()})

        # Branch connections
        for bm in re.finditer(r'Branch\s*\{(.*?)\}', lc, re.DOTALL):
            dst2 = _val(bm.group(1), 'DstBlock')
            if src and dst2:
                connections.append({'from': src.strip(), 'to': dst2.strip()})


def _get_brace_content(content, start):
    if start >= len(content) or content[start] != '{':
        return None
    depth = 0
    for i in range(start, min(start + 50000, len(content))):
        if content[i] == '{':
            depth += 1
        elif content[i] == '}':
            depth -= 1
            if depth == 0:
                return content[start+1:i]
    return None


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