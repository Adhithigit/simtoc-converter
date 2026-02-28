import cv2
import numpy as np
import pytesseract
from PIL import Image
import os

# Mac: tesseract is found automatically via Homebrew
# No need to set path manually on Mac

KNOWN_BLOCKS = [
    'gain', 'sum', 'integrator', 'derivative', 'scope', 'constant',
    'inport', 'outport', 'product', 'saturation', 'switch', 'mux',
    'demux', 'step', 'sine', 'pulse', 'transfer', 'pid', 'delay',
    'state', 'zero', 'clock', 'subsystem', 'lookup'
]

def parse_image(filepath):
    img = cv2.imread(filepath)
    if img is None:
        raise ValueError("Could not read image. Try PNG or JPG format.")

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    rects = _detect_rectangles(gray)

    blocks = []
    connections = []

    if rects:
        for i, (x, y, w, h) in enumerate(rects):
            roi = img[y:y+h, x:x+w]
            roi_pil = Image.fromarray(cv2.cvtColor(roi, cv2.COLOR_BGR2RGB))
            try:
                text = pytesseract.image_to_string(roi_pil).strip().lower()
            except:
                text = ''

            btype = _classify(text) if text else 'SubSystem'
            bname = text[:15].strip().replace('\n', ' ') if text else f'Block_{i+1}'

            blocks.append({
                'id': str(i + 1),
                'type': btype,
                'name': bname or f'{btype}_{i+1}',
                'x': float(x),
                'y': float(y),
                'params': {}
            })
    else:
        # Fallback: OCR full image
        try:
            full_text = pytesseract.image_to_string(Image.open(filepath)).lower()
        except:
            full_text = ''

        spacing = 150
        found = [kw for kw in KNOWN_BLOCKS if kw in full_text]
        for i, kw in enumerate(found):
            btype = kw.title()
            blocks.append({
                'id': str(i + 1),
                'type': btype,
                'name': f'{btype}_{i+1}',
                'x': float(50 + (i % 5) * spacing),
                'y': float(100 + (i // 5) * spacing),
                'params': {}
            })

    # Connect blocks left to right
    sorted_b = sorted(blocks, key=lambda b: b['x'])
    for i in range(len(sorted_b) - 1):
        connections.append({'from': sorted_b[i]['id'], 'to': sorted_b[i+1]['id']})

    if not blocks:
        raise ValueError("No blocks identified from image.")

    return blocks, connections


def _detect_rectangles(gray):
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edged = cv2.Canny(blurred, 50, 150)
    contours, _ = cv2.findContours(edged, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    rects = []
    for c in contours:
        approx = cv2.approxPolyDP(c, 0.02 * cv2.arcLength(c, True), True)
        if len(approx) == 4:
            x, y, w, h = cv2.boundingRect(approx)
            if w > 30 and h > 20 and w < gray.shape[1] * 0.8:
                rects.append((x, y, w, h))

    filtered = []
    for r in rects:
        if not any(_overlaps(r, e) for e in filtered):
            filtered.append(r)

    return sorted(filtered, key=lambda r: r[0])


def _overlaps(r1, r2):
    return not (r1[0]+r1[2] < r2[0] or r2[0]+r2[2] < r1[0] or
                r1[1]+r1[3] < r2[1] or r2[1]+r2[3] < r1[1])


def _classify(text):
    if 'gain' in text: return 'Gain'
    if 'sum' in text or '+' in text: return 'Sum'
    if 'integrat' in text or '1/s' in text: return 'Integrator'
    if 'deriv' in text: return 'Derivative'
    if 'scope' in text: return 'Scope'
    if 'constant' in text: return 'Constant'
    if 'pid' in text: return 'PIDController'
    if 'transfer' in text: return 'TransferFcn'
    if 'step' in text: return 'Step'
    if 'sine' in text or 'sin(' in text: return 'SineWave'
    if 'product' in text or '*' in text: return 'Product'
    if 'sat' in text: return 'Saturation'
    if 'mux' in text: return 'Mux'
    if 'demux' in text: return 'Demux'
    if 'delay' in text: return 'UnitDelay'
    if 'in' in text and len(text) < 8: return 'Inport'
    if 'out' in text and len(text) < 8: return 'Outport'
    return 'SubSystem'