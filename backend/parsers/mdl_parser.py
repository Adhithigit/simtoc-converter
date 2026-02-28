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

    # ---- Parse Blocks ----
    block_pattern = re.compile(r'Block\s*\{(.*?)\n\s*\}', re.DOTALL)

    for match in block_pattern.finditer(content):
        bc = match.group(1)
        block_type = _val(bc, 'BlockType')
        block_name = _val(bc, 'Name')
        pos_str    = _val(bc, 'Position')

        if not block_type:
            continue

        x, y = 0.0, 0.0
        if pos_str:
            nums = re.findall(r'[-\d.]+', pos_str)
            if len(nums) >= 2:
                try:
                    x = float(nums[0])
                    y = float(nums[1])
                except:
                    pass

        params = {}
        for line in bc.split('\n'):
            line = line.strip()
            if not line or line.startswith('//'):
                continue
            parts = line.split(None, 1)
            if len(parts) == 2:
                key = parts[0].strip()
                val = parts[1].strip().strip('"')
                if key not in ('BlockType', 'Name', 'Position'):
                    params[key] = val

        bid = nid()
        blocks.append({
            'id':     bid,
            'type':   block_type,
            'name':   block_name or f'Block_{bid}',
            'x':      x,
            'y':      y,
            'params': params
        })

    # ---- Build name → id map ----
    name_to_id = {b['name']: b['id'] for b in blocks}

    # ---- Parse Line connections ----
    line_pattern = re.compile(r'Line\s*\{(.*?)\n\s*\}', re.DOTALL)

    for match in line_pattern.finditer(content):
        lc = match.group(1)
        src_name = _val(lc, 'SrcBlock')
        dst_name = _val(lc, 'DstBlock')

        if src_name and dst_name:
            src_id = name_to_id.get(src_name)
            dst_id = name_to_id.get(dst_name)

            if src_id and dst_id:
                connections.append({'from': src_id, 'to': dst_id})

        # Handle branch connections (one source to multiple destinations)
        branch_pattern = re.compile(r'Branch\s*\{(.*?)\}', re.DOTALL)
        for branch in branch_pattern.finditer(lc):
            bc2 = branch.group(1)
            dst_name2 = _val(bc2, 'DstBlock')
            if src_name and dst_name2:
                src_id  = name_to_id.get(src_name)
                dst_id2 = name_to_id.get(dst_name2)
                if src_id and dst_id2:
                    connections.append({'from': src_id, 'to': dst_id2})

    return blocks, connections


def _val(content, key):
    m = re.search(rf'^\s*{re.escape(key)}\s+"?([^"\n]+)"?', content, re.MULTILINE)
    return m.group(1).strip().strip('"') if m else None