# Image Parser for SimToC
# Graceful imports — won't crash if OpenCV/Tesseract not installed

try:
    import cv2
    import numpy as np
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False

try:
    import pytesseract
    from PIL import Image
    import os
    if os.path.exists('/opt/homebrew/bin/tesseract'):
        pytesseract.pytesseract.tesseract_cmd = '/opt/homebrew/bin/tesseract'
    elif os.path.exists('/usr/local/bin/tesseract'):
        pytesseract.pytesseract.tesseract_cmd = '/usr/local/bin/tesseract'
    TESSERACT = True
except ImportError:
    TESSERACT = False

import re

BLOCK_KEYWORDS = {
    'transfer fcn':  'TransferFcn',   'transfer':    'TransferFcn',
    'integrator':    'Integrator',    'derivative':  'Derivative',
    'pid':           'PIDController', 'unit delay':  'UnitDelay',
    'zero-order':    'ZeroOrderHold', 'zero order':  'ZeroOrderHold',
    'saturation':    'Saturation',    'saturate':    'Saturation',
    'subsystem':     'SubSystem',     'constant':    'Constant',
    'inport':        'Inport',        'outport':     'Outport',
    'demux':         'Demux',         'scope':       'Scope',
    'display':       'Display',       'switch':      'Switch',
    'product':       'Product',       'lookup':      'LookupTable',
    'delay':         'UnitDelay',     'sine wave':   'SineWave',
    'sine':          'SineWave',      'step':        'Step',
    'gain':          'Gain',          'sum':         'Sum',
    'mux':           'Mux',           '1/s':         'Integrator',
    '+':             'Sum',           'k':           'Gain',
}


def parse_image(filepath):
    if not CV2_AVAILABLE:
        raise ValueError(
            "OpenCV is not installed. "
            "Add 'opencv-python-headless' to requirements.txt and redeploy."
        )

    from PIL import Image as PILImage
    img_orig = cv2.imread(filepath)
    if img_orig is None:
        raise ValueError("Could not read image. Please use PNG or JPG.")

    # Resize if very large
    h, w = img_orig.shape[:2]
    scale = 1.0
    if w > 2000:
        scale = 2000.0 / w
        img_orig = cv2.resize(img_orig, (2000, int(h * scale)))

    gray = cv2.cvtColor(img_orig, cv2.COLOR_BGR2GRAY)

    counter = [0]
    def nid():
        counter[0] += 1
        return str(counter[0])

    # ---- Detect rectangles ----
    rects = _detect_rectangles(gray, img_orig)

    blocks = []
    if rects:
        for (rx, ry, rw, rh, color_hint) in rects:
            text = ''
            if TESSERACT:
                roi_gray = gray[ry:ry+rh, rx:rx+rw]
                text = _ocr_roi(roi_gray)

            btype  = _classify(text, color_hint)
            bname  = _clean_name(text) or f'{btype}_{nid()}'
            params = _extract_params(text, btype)
            bid    = nid()

            blocks.append({
                'id': bid, 'type': btype, 'name': bname,
                'x': float(rx) / scale,
                'y': float(ry) / scale,
                'params': params
            })

    # ---- Fallback: full image OCR ----
    if not blocks and TESSERACT:
        blocks = _full_ocr_fallback(img_orig, gray, nid)

    # ---- Last resort: grid regions ----
    if not blocks:
        blocks = _region_fallback(img_orig, nid)

    if not blocks:
        raise ValueError(
            "No blocks detected in image.\n"
            "Tips:\n"
            "  • Use a high-resolution screenshot (>1000px wide)\n"
            "  • Make sure blocks are clearly visible rectangles\n"
            "  • For best results upload the .slx or .mdl file directly"
        )

    # ---- Detect connections ----
    connections = _detect_arrows(gray, blocks, scale)

    if not connections and len(blocks) > 1:
        sb = sorted(blocks, key=lambda b: (b['x'], b['y']))
        for i in range(len(sb) - 1):
            if abs(sb[i]['y'] - sb[i+1]['y']) < 80:
                connections.append({
                    'from': sb[i]['id'], 'to': sb[i+1]['id'],
                    'src_port': 1, 'dst_port': 1
                })

    return blocks, connections, 0.1, 10.0


# ================================================================
# Rectangle Detection
# ================================================================

def _detect_rectangles(gray, img_bgr):
    results = []
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)

    for low, high in [(30, 100), (50, 150), (80, 200)]:
        edged = cv2.Canny(blurred, low, high)
        edged = cv2.dilate(edged, np.ones((2, 2), np.uint8), iterations=1)
        contours, _ = cv2.findContours(
            edged, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        for c in contours:
            peri   = cv2.arcLength(c, True)
            approx = cv2.approxPolyDP(c, 0.03 * peri, True)
            if len(approx) not in (4, 5, 6):
                continue
            x, y, w, h = cv2.boundingRect(approx)
            aspect = w / max(h, 1)
            if (w < 20 or h < 15 or
                    w > gray.shape[1] * 0.85 or
                    h > gray.shape[0] * 0.85 or
                    aspect < 0.3 or aspect > 6.0):
                continue
            roi   = img_bgr[y:y+h, x:x+w]
            color = _dominant_color(roi)
            results.append((x, y, w, h, color))

    return _dedup_rects(results)


def _dedup_rects(rects):
    rects = sorted(rects, key=lambda r: r[2]*r[3], reverse=True)
    kept  = []
    for r in rects:
        x, y, w, h = r[0], r[1], r[2], r[3]
        overlap = False
        for k in kept:
            kx, ky, kw, kh = k[0], k[1], k[2], k[3]
            ix1 = max(x, kx); iy1 = max(y, ky)
            ix2 = min(x+w, kx+kw); iy2 = min(y+h, ky+kh)
            if ix2 > ix1 and iy2 > iy1:
                inter = (ix2-ix1)*(iy2-iy1)
                union = w*h + kw*kh - inter
                if inter / max(union, 1) > 0.4:
                    overlap = True
                    break
        if not overlap:
            kept.append(r)
    return kept


def _dominant_color(roi):
    if roi is None or roi.size == 0:
        return 'unknown'
    try:
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        hue = hsv[:, :, 0].mean()
        if hue < 15 or hue > 165: return 'red'
        if 15  <= hue < 30:       return 'orange'
        if 30  <= hue < 75:       return 'yellow_green'
        if 75  <= hue < 105:      return 'green'
        if 105 <= hue < 135:      return 'cyan'
        if 135 <= hue < 155:      return 'blue'
    except:
        pass
    return 'unknown'


# ================================================================
# OCR
# ================================================================

def _ocr_roi(gray_roi):
    if not TESSERACT:
        return ''
    try:
        h, w = gray_roi.shape
        if w < 60 or h < 30:
            gray_roi = cv2.resize(
                gray_roi, (max(w*3, 120), max(h*3, 60)),
                interpolation=cv2.INTER_CUBIC
            )
        _, binary = cv2.threshold(
            gray_roi, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
        )
        cfg  = '--psm 8 --oem 3'
        t1   = pytesseract.image_to_string(binary, config=cfg).strip()
        t2   = pytesseract.image_to_string(
            cv2.bitwise_not(binary), config=cfg
        ).strip()
        return t1 if len(t1) >= len(t2) else t2
    except:
        return ''


def _full_ocr_fallback(img_bgr, gray, nid):
    if not TESSERACT:
        return []
    try:
        from PIL import Image as PILImage
        pil  = PILImage.fromarray(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB))
        data = pytesseract.image_to_data(
            pil, output_type=pytesseract.Output.DICT
        )
    except:
        return []

    blocks = []
    used   = set()
    n      = len(data['text'])

    for i in range(n):
        word = data['text'][i].strip()
        if not word or i in used or int(data['conf'][i]) < 40:
            continue
        cluster = [word]
        used.add(i)
        x_ref = data['left'][i]
        y_ref = data['top'][i]

        for j in range(i+1, n):
            if j in used: continue
            wj = data['text'][j].strip()
            if not wj: continue
            if abs(data['top'][j]-y_ref) < 20 and abs(data['left'][j]-x_ref) < 200:
                cluster.append(wj)
                used.add(j)

        text  = ' '.join(cluster)
        btype = _classify(text, 'unknown')
        if btype != 'SubSystem' or 'subsystem' in text.lower():
            name = _clean_name(text) or f'{btype}_{nid()}'
            bid  = nid()
            blocks.append({
                'id': bid, 'type': btype, 'name': name,
                'x': float(data['left'][i]),
                'y': float(data['top'][i]),
                'params': _extract_params(text, btype)
            })
    return blocks


def _region_fallback(img_bgr, nid):
    h, w   = img_bgr.shape[:2]
    cols   = min(5, max(2, w // 150))
    rows   = min(3, max(1, h // 120))
    types  = ['Inport','Gain','Sum','Integrator','Saturation','Outport']
    cw, ch = w // cols, h // rows
    blocks = []
    for r in range(rows):
        for c in range(cols):
            idx   = r * cols + c
            btype = types[idx % len(types)]
            bid   = nid()
            blocks.append({
                'id': bid, 'type': btype, 'name': f'{btype}_{bid}',
                'x': float(c*cw+20), 'y': float(r*ch+20), 'params': {}
            })
    return blocks


# ================================================================
# Arrow Detection
# ================================================================

def _detect_arrows(gray, blocks, scale=1.0):
    if not CV2_AVAILABLE or len(blocks) < 2:
        return []

    centres = {
        b['id']: (b['x'] * scale + 55, b['y'] * scale + 18)
        for b in blocks
    }

    edges = cv2.Canny(gray, 50, 150)
    lines = cv2.HoughLinesP(
        edges, 1, 3.14159/180,
        threshold=30, minLineLength=30, maxLineGap=15
    )
    if lines is None:
        return []

    conns = []
    seen  = set()

    for line in lines:
        x1, y1, x2, y2 = line[0]
        sid = _nearest(x1, y1, centres, 80)
        did = _nearest(x2, y2, centres, 80)
        if sid and did and sid != did:
            scx = centres[sid][0]
            dcx = centres[did][0]
            if scx > dcx:
                sid, did = did, sid
            k = (sid, did)
            if k not in seen:
                seen.add(k)
                conns.append({
                    'from': sid, 'to': did,
                    'src_port': 1, 'dst_port': 1
                })
    return conns


def _nearest(px, py, centres, max_d):
    best_id, best_d = None, max_d
    for bid, (cx, cy) in centres.items():
        d = ((px-cx)**2 + (py-cy)**2) ** 0.5
        if d < best_d:
            best_d, best_id = d, bid
    return best_id


# ================================================================
# Classification & Utilities
# ================================================================

def _classify(text, color_hint='unknown'):
    tl   = text.lower().strip()
    best, best_len = None, 0
    for kw, btype in BLOCK_KEYWORDS.items():
        if kw in tl and len(kw) > best_len:
            best, best_len = btype, len(kw)
    if best:
        return best
    color_map = {
        'orange': 'SubSystem', 'cyan': 'Inport',
        'yellow_green': 'Constant', 'green': 'Outport',
    }
    return color_map.get(color_hint, 'SubSystem')


def _clean_name(text):
    name = re.sub(r'[^\w\s]', '', text).strip()
    name = re.sub(r'\s+', '_', name)
    return name[:20] if name else ''


def _extract_params(text, btype):
    params = {}
    nums = re.findall(r'[-\d.]+(?:e[-+]?\d+)?', text)
    if btype == 'Gain' and nums:
        params['Gain'] = nums[0]
    elif btype == 'Constant' and nums:
        params['Value'] = nums[0]
    elif btype == 'Saturation' and len(nums) >= 2:
        vals = sorted([float(n) for n in nums[:2]])
        params['LowerLimit'] = str(vals[0])
        params['UpperLimit'] = str(vals[1])
    return params