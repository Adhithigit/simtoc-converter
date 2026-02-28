import fitz  # PyMuPDF
import re

KNOWN_BLOCKS = [
    'gain', 'sum', 'integrator', 'derivative', 'transfer function',
    'scope', 'constant', 'inport', 'outport', 'product', 'saturation',
    'switch', 'mux', 'demux', 'subsystem', 'state space', 'pid',
    'lookup table', 'delay', 'unit delay', 'zero-order hold',
    'step', 'sine wave', 'pulse generator', 'transfer fcn',
    'discrete', 'zero order hold', 'from workspace', 'to workspace'
]

def parse_pdf(filepath):
    blocks = []
    connections = []

    doc = fitz.open(filepath)
    full_text = ""
    for page in doc:
        full_text += page.get_text() + "\n"
    doc.close()

    found = _find_blocks(full_text)

    counter = [0]
    spacing = 150

    for i, (btype, bname) in enumerate(found):
        counter[0] += 1
        blocks.append({
            'id': str(counter[0]),
            'type': btype,
            'name': bname,
            'x': float(50 + (i % 5) * spacing),
            'y': float(100 + (i // 5) * spacing),
            'params': {}
        })

    if len(blocks) > 1:
        for i in range(len(blocks) - 1):
            connections.append({'from': blocks[i]['id'], 'to': blocks[i+1]['id']})

    if not blocks:
        raise ValueError("No recognizable Simulink blocks found in this PDF.")

    return blocks, connections


def _find_blocks(text):
    found = []
    tl = text.lower()
    for name in KNOWN_BLOCKS:
        if name in tl:
            btype = name.title().replace(' ', '')
            count = min(tl.count(name), 3)
            for i in range(count):
                found.append((btype, f'{btype}_{i+1}'))
    return found