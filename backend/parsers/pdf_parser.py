# PDF Parser for SimToC
# Uses Claude AI to extract Simulink blocks from PDF files

import os
import re
import base64
import json

try:
    import fitz
    FITZ_AVAILABLE = True
except ImportError:
    FITZ_AVAILABLE = False


def parse_pdf(filepath):
    """
    Parse a PDF containing a Simulink diagram or block list.
    Uses Claude AI for accurate extraction.
    Returns (blocks, connections, sim_dt, sim_stop)
    """
    if not FITZ_AVAILABLE:
        raise ValueError(
            "PyMuPDF not installed. Add 'pymupdf' to requirements.txt."
        )

    doc  = fitz.open(filepath)
    text = ""
    pages_b64 = []

    for page in doc:
        text += page.get_text() + "\n"
        # Render page as image for visual analysis
        mat  = fitz.Matrix(2.0, 2.0)  # 2x zoom for clarity
        pix  = page.get_pixmap(matrix=mat)
        png  = pix.tobytes("png")
        pages_b64.append(base64.b64encode(png).decode('utf-8'))

    doc.close()

    # Try text-based extraction first (fast)
    blocks, connections = _extract_from_text(text)

    # If text extraction failed or got too few blocks, use AI vision
    if len(blocks) < 2 and pages_b64:
        blocks, connections = _call_claude_pdf(pages_b64[0], text)

    if not blocks:
        raise ValueError(
            "No Simulink blocks found in this PDF.\n"
            "For best results, upload the .slx or .mdl file directly."
        )

    return blocks, connections, 0.1, 10.0


def _extract_from_text(text):
    """Try to extract blocks from PDF text (works for text-based PDFs)."""
    blocks = []
    connections = []
    counter = [0]

    def nid():
        counter[0] += 1
        return str(counter[0])

    # Look for lines that look like "BlockName [BlockType] value=X"
    BTYPES = {
        'Constant':'Constant','Gain':'Gain','Sum':'Sum','Integrator':'Integrator',
        'Derivative':'Derivative','Saturation':'Saturation','Saturate':'Saturation',
        'TransferFcn':'TransferFcn','Transfer Fcn':'TransferFcn',
        'PIDController':'PIDController','PID Controller':'PIDController',
        'UnitDelay':'UnitDelay','Unit Delay':'UnitDelay',
        'ZeroOrderHold':'ZeroOrderHold','Scope':'Scope','Display':'Display',
        'Inport':'Inport','Outport':'Outport','Mux':'Mux','Demux':'Demux',
        'Product':'Product','Switch':'Switch','Step':'Step','SineWave':'SineWave',
        'Sine Wave':'SineWave','SubSystem':'SubSystem','Reference':'Reference',
    }

    seen = set()
    for line in text.split('\n'):
        line = line.strip()
        if not line: continue
        for btype_raw, btype in BTYPES.items():
            if btype_raw.lower() in line.lower():
                # Extract name
                name = re.sub(r'(?i)' + re.escape(btype_raw), '', line).strip()
                name = re.sub(r'[^a-zA-Z0-9_\s]', '', name).strip()[:20]
                name = name or f'{btype}_{nid()}'
                if name not in seen:
                    seen.add(name)
                    params = {}
                    nums = re.findall(r'[-\d.]+', line)
                    if nums:
                        if btype == 'Gain': params['Gain'] = nums[0]
                        elif btype == 'Constant': params['Value'] = nums[0]
                    bid = nid()
                    blocks.append({
                        'id': bid, 'type': btype, 'name': name,
                        'x': float((len(blocks) % 5) * 160 + 50),
                        'y': float((len(blocks) // 5) * 80  + 50),
                        'params': params
                    })
                break

    # Chain connections if no arrows found
    if blocks and len(blocks) > 1:
        for i in range(len(blocks) - 1):
            connections.append({
                'from': blocks[i]['id'], 'to': blocks[i+1]['id'],
                'src_port': 1, 'dst_port': 1
            })

    return blocks, connections


def _call_claude_pdf(page_b64, text_content):
    """Use Claude vision on the first page of the PDF."""
    import urllib.request

    prompt = f"""You are analyzing a PDF page that contains a Simulink block diagram.

The PDF text content is:
{text_content[:2000]}

Also look at the rendered page image carefully.

Extract ALL Simulink blocks and connections.

Return ONLY a JSON object:
{{
  "blocks": [
    {{
      "id": "1",
      "type": "BlockType",
      "name": "BlockName",
      "x": 100,
      "y": 100,
      "params": {{"Value": "10"}}
    }}
  ],
  "connections": [
    {{"from": "1", "to": "2", "src_port": 1, "dst_port": 1}}
  ]
}}

Use exact Simulink types: Constant, Gain, Sum, Integrator, Saturation, TransferFcn, PIDController, Scope, Display, Inport, Outport, Mux, Demux, Product, Switch, Step, SineWave, UnitDelay, SubSystem, Reference.
For each connection include src_port and dst_port numbers.
Return ONLY the JSON."""

    payload = json.dumps({
        "model": "claude-opus-4-5",
        "max_tokens": 4096,
        "messages": [{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": page_b64
                    }
                },
                {"type": "text", "text": prompt}
            ]
        }]
    }).encode('utf-8')

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "Content-Type":      "application/json",
            "anthropic-version": "2023-06-01",
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='ignore')
        raise ValueError(f"Claude API error {e.code}: {body[:200]}")

    content = result.get('content', [])
    text_out = ''.join(c.get('text','') for c in content if c.get('type')=='text')

    from parsers.image_parser import _parse_claude_response
    return _parse_claude_response(text_out)