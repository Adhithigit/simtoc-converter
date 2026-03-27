import zipfile
import xml.etree.ElementTree as ET
import re

def parse_slx(filepath):
    blocks = []
    connections = []
    counter = [0]

    def nid():
        counter[0] += 1
        return str(counter[0])

    with zipfile.ZipFile(filepath, 'r') as z:
        system_files = [f for f in z.namelist()
                        if f.startswith('simulink/systems/') and f.endswith('.xml')]

        for sfile in system_files:
            with z.open(sfile) as f:
                content = f.read().decode('utf-8', errors='ignore')
            try:
                root = ET.fromstring(content)
            except:
                continue

            sid_to_id = {}

            # ---- Parse Blocks ----
            for block in root.findall('.//Block'):
                btype = block.get('BlockType', '')
                bname = block.get('Name', '')
                sid   = block.get('SID', '')

                x, y = 0.0, 0.0
                pos_el = block.find("P[@Name='Position']")
                if pos_el is not None and pos_el.text:
                    nums = re.findall(r'[-\d.]+', pos_el.text)
                    if len(nums) >= 2:
                        try: x, y = float(nums[0]), float(nums[1])
                        except: pass

                params = {}
                for p in block.findall('P'):
                    pname = p.get('Name', '')
                    ptext = (p.text or '').strip()
                    if pname:
                        params[pname] = ptext

                bid = nid()
                if sid:
                    sid_to_id[sid] = bid

                btype = _normalize(btype)
                blocks.append({
                    'id': bid, 'type': btype, 'name': bname,
                    'x': x, 'y': y, 'params': params
                })

            # ---- Parse Lines (with Branch support) ----
            for line in root.findall('.//Line'):
                src_el = line.find("P[@Name='Src']")
                dst_el = line.find("P[@Name='Dst']")

                if src_el is None:
                    continue

                src_str = (src_el.text or '').strip()
                src_sid = src_str.split('#')[0] if '#' in src_str else src_str
                src_id  = sid_to_id.get(src_sid)
                if not src_id:
                    continue

                # Direct destination (no branching)
                if dst_el is not None and dst_el.text:
                    dst_str  = dst_el.text.strip()
                    dst_sid  = dst_str.split('#')[0] if '#' in dst_str else dst_str
                    dst_id   = sid_to_id.get(dst_sid)
                    dst_port = _port(dst_str, 'in')
                    if dst_id and src_id != dst_id:
                        connections.append({
                            'from': src_id, 'to': dst_id,
                            'src_port': _port(src_str, 'out'),
                            'dst_port': dst_port
                        })

                # Branch destinations
                for branch in line.findall('Branch'):
                    bdst_el = branch.find("P[@Name='Dst']")
                    if bdst_el is not None and bdst_el.text:
                        dst_str  = bdst_el.text.strip()
                        dst_sid  = dst_str.split('#')[0] if '#' in dst_str else dst_str
                        dst_id   = sid_to_id.get(dst_sid)
                        dst_port = _port(dst_str, 'in')
                        if dst_id and src_id != dst_id:
                            connections.append({
                                'from': src_id, 'to': dst_id,
                                'src_port': _port(src_str, 'out'),
                                'dst_port': dst_port
                            })

    # Deduplicate
    seen, unique = set(), []
    for c in connections:
        k = (c['from'], c['to'], c.get('dst_port', 1))
        if k not in seen:
            seen.add(k)
            unique.append(c)

    # Extract simulation settings from configSet
    sim_dt   = 0.1
    sim_stop = 10.0
    try:
        with zipfile.ZipFile(filepath, 'r') as z2:
            cfg_files = [f for f in z2.namelist() if 'configSet' in f and f.endswith('.xml')]
            if cfg_files:
                with z2.open(cfg_files[0]) as cf:
                    cfg = cf.read().decode('utf-8', errors='ignore')
                import re as _re
                m = _re.search(r'<P Name="StopTime"[^>]*>([^<]+)</P>', cfg)
                if m:
                    try: sim_stop = float(m.group(1).strip())
                    except: pass
                m = _re.search(r'<P Name="FixedStep"[^>]*>([^<]+)</P>', cfg)
                if m:
                    v = m.group(1).strip()
                    if v not in ('auto','inf',''):
                        try: sim_dt = float(v)
                        except: pass
    except:
        pass

    return blocks, unique, sim_dt, sim_stop


def _port(s, direction):
    """Extract port number from SID string like '3#in:2' or '1#out:1'."""
    marker = f'#{direction}:'
    if marker in s:
        try:
            return int(s.split(marker)[1].split('#')[0])
        except:
            pass
    return 1


def _normalize(btype):
    return {
        'S-Function': 'SFunction', 'S-function': 'SFunction',
        'Math': 'MathFunction', 'Trigonometry': 'Trigonometry',
        'Logic': 'LogicOperator', 'Saturate': 'Saturate',
    }.get(btype, btype)