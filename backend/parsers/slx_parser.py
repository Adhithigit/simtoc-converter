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
        system_files = [f for f in z.namelist() if f.startswith('simulink/systems/') and f.endswith('.xml')]
        
        for sfile in system_files:
            with z.open(sfile) as f:
                content = f.read().decode('utf-8', errors='ignore')
            
            try:
                root = ET.fromstring(content)
            except:
                continue

            # SID -> internal id map
            sid_to_id = {}

            # Parse all Block elements
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

                # Extract all parameters
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
                    'id':     bid,
                    'type':   btype,
                    'name':   bname,
                    'x':      x,
                    'y':      y,
                    'params': params
                })

            # Parse all Line connections (SID-based: "1#out:1" -> "3#in:1")
            for line in root.findall('.//Line'):
                src_el = line.find("P[@Name='Src']")
                dst_el = line.find("P[@Name='Dst']")
                if src_el is None or dst_el is None:
                    continue

                src_str = (src_el.text or '').strip()
                dst_str = (dst_el.text or '').strip()

                # Parse "SID#out:port" or "SID#in:port"
                src_sid = src_str.split('#')[0] if '#' in src_str else src_str
                dst_sid = dst_str.split('#')[0] if '#' in dst_str else dst_str

                src_id = sid_to_id.get(src_sid)
                dst_id = sid_to_id.get(dst_sid)

                if src_id and dst_id and src_id != dst_id:
                    # Get port numbers
                    src_port = 1
                    dst_port = 1
                    if '#out:' in src_str:
                        try: src_port = int(src_str.split('#out:')[1])
                        except: pass
                    if '#in:' in dst_str:
                        try: dst_port = int(dst_str.split('#in:')[1])
                        except: pass

                    connections.append({
                        'from':      src_id,
                        'to':        dst_id,
                        'src_port':  src_port,
                        'dst_port':  dst_port
                    })

    # Deduplicate
    seen, unique = set(), []
    for c in connections:
        k = (c['from'], c['to'], c.get('dst_port', 1))
        if k not in seen:
            seen.add(k)
            unique.append(c)

    return blocks, unique


def _normalize(btype):
    return {
        'S-Function': 'SFunction', 'S-function': 'SFunction',
        'Math': 'MathFunction', 'Trigonometry': 'Trigonometry',
        'Logic': 'LogicOperator',
    }.get(btype, btype)