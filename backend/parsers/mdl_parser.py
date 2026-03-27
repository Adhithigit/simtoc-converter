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

    # ---- Parse ALL Block sections using brace matching ----
    pos = 0
    while pos < len(content):
        m = re.search(r'\bBlock\s*\{', content[pos:])
        if not m:
            break
        abs_start = pos + m.start()
        brace_open = pos + m.end() - 1

        depth = 0
        bc = None
        for i in range(brace_open, min(brace_open + 20000, len(content))):
            if content[i] == '{': depth += 1
            elif content[i] == '}':
                depth -= 1
                if depth == 0:
                    bc = content[brace_open+1:i]
                    break

        if bc:
            btype_m = re.search(r'^\s*BlockType\s+"?([^"\n]+)"?\s*$', bc, re.MULTILINE)
            bname_m = re.search(r'^\s*Name\s+"?([^"\n]+)"?\s*$', bc, re.MULTILINE)
            pos_m   = re.search(r'^\s*Position\s+\[([^\]]+)\]', bc, re.MULTILINE)

            if btype_m:
                btype = btype_m.group(1).strip().strip('"')
                bname = bname_m.group(1).strip().strip('"').strip() if bname_m else ''

                x, y = 0.0, 0.0
                if pos_m:
                    nums = re.findall(r'[-\d.]+', pos_m.group(1))
                    if len(nums) >= 2:
                        try: x, y = float(nums[0]), float(nums[1])
                        except: pass

                params = {}
                for line in bc.split('\n'):
                    line = line.strip()
                    if not line or '{' in line or '}' in line: continue
                    parts = line.split(None, 1)
                    if len(parts) == 2:
                        k = parts[0].strip()
                        v = parts[1].strip().strip('"')
                        params[k] = v

                bid = nid()
                bname = bname or f'Block_{bid}'
                btype = _normalize(btype)

                blocks.append({
                    'id': bid, 'type': btype, 'name': bname,
                    'x': x, 'y': y, 'params': params
                })

        pos = abs_start + 1

    # ---- Build name->id map ----
    name_to_id = {}
    for b in blocks:
        raw = b['name']
        name_to_id[raw] = b['id']
        name_to_id[raw.strip()] = b['id']
        clean = raw.replace('\\n', ' ').replace('\n', ' ').strip()
        name_to_id[clean] = b['id']

    def resolve(name):
        if not name: return None
        name = str(name).strip().strip('"')
        if name in name_to_id: return name_to_id[name]
        clean = name.replace('\\n', ' ').replace('\n', ' ').strip()
        if clean in name_to_id: return name_to_id[clean]
        for k, v in name_to_id.items():
            if k.strip() == name.strip(): return v
        return None

    # ---- Parse ALL Line connections with port numbers ----
    for lm in re.finditer(r'\bLine\s*\{(.*?)\n\s*\}', content, re.DOTALL):
        lc = lm.group(1)
        src = _val(lc, 'SrcBlock')
        dst = _val(lc, 'DstBlock')

        # Get port numbers
        src_port = 1
        dst_port = 1
        sp_m = re.search(r'^\s*SrcPort\s+(\d+)', lc, re.MULTILINE)
        dp_m = re.search(r'^\s*DstPort\s+(\d+)', lc, re.MULTILINE)
        if sp_m: src_port = int(sp_m.group(1))
        if dp_m: dst_port = int(dp_m.group(1))

        if src and dst:
            sid = resolve(src)
            did = resolve(dst)
            if sid and did and sid != did:
                connections.append({
                    'from': sid, 'to': did,
                    'src_port': src_port, 'dst_port': dst_port
                })

        # Branch connections
        for bm in re.finditer(r'Branch\s*\{(.*?)\}', lc, re.DOTALL):
            bc2 = bm.group(1)
            dst2 = _val(bc2, 'DstBlock')
            dp2_m = re.search(r'^\s*DstPort\s+(\d+)', bc2, re.MULTILINE)
            dst_port2 = int(dp2_m.group(1)) if dp2_m else 1
            if src and dst2:
                sid = resolve(src)
                did = resolve(dst2)
                if sid and did and sid != did:
                    connections.append({
                        'from': sid, 'to': did,
                        'src_port': src_port, 'dst_port': dst_port2
                    })

    # Deduplicate by (from, to, dst_port)
    seen, unique = set(), []
    for c in connections:
        k = (c['from'], c['to'], c.get('dst_port', 1))
        if k not in seen:
            seen.add(k)
            unique.append(c)

    # ---- Extract simulation settings ----
    sim_dt   = 0.1
    sim_stop = 10.0
    try:
        m = re.search(r'StopTime\s+"([^"]+)"', content)
        if m:
            v = m.group(1).strip()
            if v not in ('inf', 'Inf'):
                try: sim_stop = float(v)
                except: pass
        m = re.search(r'FixedStep\s+"([^"]+)"', content)
        if m:
            v = m.group(1).strip()
            if v not in ('auto', 'inf', 'Inf', ''):
                try: sim_dt = float(v)
                except: pass
    except:
        pass

    return blocks, unique, sim_dt, sim_stop


def _normalize(btype):
    return {
        'S-Function':  'SFunction',
        'S-function':  'SFunction',
        'Math':        'MathFunction',
        'Trigonometry':'Trigonometry',
        'Logic':       'LogicOperator',
        'Saturate':    'Saturate',
    }.get(btype, btype)


def _val(content, key):
    m = re.search(
        rf'^\s*{re.escape(key)}\s+"?([^"\n]+)"?\s*$',
        content, re.MULTILINE
    )
    return m.group(1).strip().strip('"') if m else None