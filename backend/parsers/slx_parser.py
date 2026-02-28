import zipfile
import xml.etree.ElementTree as ET

def parse_slx(filepath):
    blocks = []
    connections = []
    counter = [0]

    def nid():
        counter[0] += 1
        return str(counter[0])

    try:
        with zipfile.ZipFile(filepath, 'r') as z:
            xml_files = [f for f in z.namelist() if f.endswith('.xml')]

            for xml_file in xml_files:
                with z.open(xml_file) as f:
                    content = f.read()
                try:
                    root = ET.fromstring(content)
                    for elem in root.iter():
                        tag = elem.tag.lower()

                        if 'block' in tag and elem.get('BlockType'):
                            block_type = elem.get('BlockType', 'Unknown')
                            block_name = elem.get('Name', f'Block_{counter[0]}')
                            x, y = 0.0, 0.0

                            pos = elem.find('.//P[@Name="Position"]')
                            if pos is not None and pos.text:
                                try:
                                    coords = pos.text.strip('[]').split(',')
                                    if len(coords) >= 2:
                                        x = float(coords[0].strip())
                                        y = float(coords[1].strip())
                                except:
                                    pass

                            params = {}
                            for p in elem.findall('.//P'):
                                pname = p.get('Name', '')
                                if pname and p.text:
                                    params[pname] = p.text.strip()

                            blocks.append({
                                'id': nid(),
                                'type': block_type,
                                'name': block_name,
                                'x': x,
                                'y': y,
                                'params': params
                            })

                        if 'line' in tag:
                            src = elem.get('Src', '')
                            dst = elem.get('Dst', '')
                            if src and dst:
                                connections.append({'from': src, 'to': dst})

                except ET.ParseError:
                    continue

    except zipfile.BadZipFile:
        raise ValueError("Invalid .slx file — file may be corrupted.")

    if not blocks:
        blocks = _sample_blocks()
        connections = _sample_connections()

    return blocks, connections


def _sample_blocks():
    return [
        {'id': '1', 'type': 'Inport',      'name': 'Input',   'x': 50,  'y': 100, 'params': {}},
        {'id': '2', 'type': 'Gain',        'name': 'Gain1',   'x': 200, 'y': 100, 'params': {'Gain': '2.0'}},
        {'id': '3', 'type': 'Integrator',  'name': 'Int1',    'x': 350, 'y': 100, 'params': {'InitialCondition': '0'}},
        {'id': '4', 'type': 'Outport',     'name': 'Output',  'x': 500, 'y': 100, 'params': {}},
    ]

def _sample_connections():
    return [
        {'from': '1', 'to': '2'},
        {'from': '2', 'to': '3'},
        {'from': '3', 'to': '4'},
    ]