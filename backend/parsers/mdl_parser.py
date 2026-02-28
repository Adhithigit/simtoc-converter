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

    block_pattern = re.compile(r'Block\s*\{(.*?)\}', re.DOTALL)

    for match in block_pattern.finditer(content):
        bc = match.group(1)
        block_type = _val(bc, 'BlockType')
        block_name = _val(bc, 'Name')
        pos_str = _val(bc, 'Position')

        if not block_type:
            continue

        x, y = 0.0, 0.0
        if pos_str:
            nums = re.findall(r'[\d.]+', pos_str)
            if len(nums) >= 2:
                x, y = float(nums[0]), float(nums[1])

        params = {}
        for line in bc.split('\n'):
            line = line.strip()
            if line and not line.startswith('//'):
                parts = line.split(None, 1)
                if len(parts) == 2:
                    params[parts[0]] = parts[1].strip().strip('"')

        blocks.append({
            'id': nid(),
            'type': block_type,
            'name': block_name or f'Block_{counter[0]}',
            'x': x,
            'y': y,
            'params': params
        })

    line_pattern = re.compile(r'Line\s*\{(.*?)\}', re.DOTALL)
    for match in line_pattern.finditer(content):
        lc = match.group(1)
        src = _val(lc, 'SrcBlock')
        dst = _val(lc, 'DstBlock')
        if src and dst:
            connections.append({'from': src, 'to': dst})

    return blocks, connections


def _val(content, key):
    m = re.search(rf'{re.escape(key)}\s+"?([^"\n]+)"?', content)
    return m.group(1).strip().strip('"') if m else None