import cv2
import numpy as np
from PIL import Image
import os
import re

# Try tesseract — graceful fallback if not available
try:
    import pytesseract
    # Mac Homebrew path
    if os.path.exists('/opt/homebrew/bin/tesseract'):
        pytesseract.pytesseract.tesseract_cmd = '/opt/homebrew/bin/tesseract'
    elif os.path.exists('/usr/local/bin/tesseract'):
        pytesseract.pytesseract.tesseract_cmd = '/usr/local/bin/tesseract'
    TESSERACT = True
except ImportError:
    TESSERACT = False

# ================================================================
# Block type classification — same keyword map as PDF parser
# ================================================================
BLOCK_KEYWORDS = {
    'transfer fcn':   'TransferFcn',
    'transfer':       'TransferFcn',
    'integrator':     'Integrator',
    'derivative':     'Derivative',
    'pid':            'PIDController',
    'unit delay':     'UnitDelay',
    'zero-order':     'ZeroOrderHold',
    'zero order':     'ZeroOrderHold',
    'saturation':     'Saturation',
    'saturate':       'Saturation',
    'subsystem':      'SubSystem',
    'constant':       'Constant',
    'inport':         'Inport',
    'outport':        'Outport',
    'demux':          'Demux',
    'scope':          'Scope',
    'display':        'Display',
    'switch':         'Switch',
    'product':        'Product',
    'lookup':         'LookupTable',
    'delay':          'UnitDelay',
    'sine wave':      'SineWave',
    'sine':           'SineWave',
    'step':           'Step',
    'gain':           'Gain',
    'sum':            'Sum',
    'mux':            'Mux',
    'from':           'From',
    'goto':           'Goto',
    '1/s':            'Integrator',
    's':              'Integrator',
    '+':              'Sum',
    '-':              'Sum',
    '*':              'Product',
    '/':              'Product',
    'k':              'Gain',
}

# Simulink brand colours used to identify block types from colour
BLOCK_COLORS = {
    # (lower_hue, upper_hue, block_type)
    # Simulink uses orange for Subsystems, cyan for sources, etc.
}


def parse_image(filepath):
    img_orig = cv2.imread(filepath)
    if img_orig is None:
        raise ValueError("Could not read image. Please use PNG or JPG format.")

    # Resize if very large (speeds up processing, OCR still accurate)
    h, w = img_orig.shape[:2]
    scale = 1.0
    if w > 2000:
        scale = 2000.0 / w
        img_orig = cv2.resize(img_orig, (2000, int(h * scale)))

    gray = cv2.cvtColor(img_orig, cv2.COLOR_BGR2GRAY)

    # ---- Step 1: Detect rectangular blocks ----
    rects = _detect_rectangles(gray, img_orig)

    blocks = []
    connections = []
    counter = [0]

    def nid():
        counter[0] += 1
        return str(counter[0])

    if rects:
        for (x, y, w, h, color_hint) in rects:
            # OCR the text inside the rectangle
            roi_gray = gray[y:y+h, x:x+w]
            text = _ocr_roi(roi_gray, img_orig[y:y+h, x:x+w]) if TESSERACT else ''

            btype = _classify(text, color_hint)
            bname = _clean_name(text) or f'{btype}_{nid()}'
            if not bname.strip():
                bname = f'{btype}_{counter[0]}'

            params = _extract_params(text, btype)

            bid = nid()
            blocks.append({
                'id':     bid,
                'type':   btype,
                'name':   bname,
                'x':      float(x) / scale,
                'y':      float(y) / scale,
                'params': params
            })

    # ---- Step 2: Fallback — full image OCR ----
    if not blocks and TESSERACT:
        blocks = _full_ocr_fallback(img_orig, gray, nid)

    if not blocks:
        # Last resort: create placeholder blocks from image regions
        blocks = _region_fallback(img_orig, nid)

    if not blocks:
        raise ValueError(
            "No blocks detected in image.\n"
            "Tips:\n"
            "  • Use a high-resolution screenshot (>1000px wide)\n"
            "  • Make sure blocks are clearly visible rectangles\n"
            "  • For best results upload the .slx or .mdl file directly"
        )

    # ---- Step 3: Detect connections (arrows) ----
    connections = _detect_arrows(img_orig, gray, blocks, scale)

    # Fallback: chain left-to-right if no arrows detected
    if not connections and len(blocks) > 1:
        sorted_b = sorted(blocks, key=lambda b: (b['x'], b['y']))
        for i in range(len(sorted_b) - 1):
            # Only connect if horizontally adjacent (same row roughly)
            if abs(sorted_b[i]['y'] - sorted_b[i+1]['y']) < 80:
                connections.append({
                    'from':     sorted_b[i]['id'],
                    'to':       sorted_b[i+1]['id'],
                    'src_port': 1,
                    'dst_port': 1
                })

    return blocks, connections, 0.1, 10.0


# ================================================================
# Rectangle Detection
# ================================================================

def _detect_rectangles(gray, img_bgr):
    """Detect rectangular blocks in a Simulink diagram image."""
    results = []

    # Preprocess: enhance edges
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)

    # Try multiple edge thresholds to catch faint lines
    for low, high in [(30, 100), (50, 150), (80, 200)]:
        edged = cv2.Canny(blurred, low, high)
        edged = cv2.dilate(edged, np.ones((2,2), np.uint8), iterations=1)

        contours, _ = cv2.findContours(
            edged, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        for c in contours:
            peri  = cv2.arcLength(c, True)
            approx = cv2.approxPolyDP(c, 0.03 * peri, True)

            # Accept 4-sided shapes (rectangles/parallelograms)
            if len(approx) not in (4, 5, 6):
                continue

            x, y, w, h = cv2.boundingRect(approx)
            aspect = w / max(h, 1)

            # Filter: reasonable block size, not the whole image
            if (w < 20 or h < 15 or
                w > gray.shape[1] * 0.85 or
                h > gray.shape[0] * 0.85):
                continue

            # Aspect ratio: Simulink blocks are typically 0.4–4.0
            if aspect < 0.3 or aspect > 6.0:
                continue

            # Detect dominant colour inside (for block type hint)
            roi = img_bgr[y:y+h, x:x+w]
            color_hint = _dominant_color(roi)

            results.append((x, y, w, h, color_hint))

    # Remove duplicates / overlapping rects
    results = _deduplicate_rects(results)

    return results


def _deduplicate_rects(rects):
    """Remove overlapping rectangles, keeping the most informative."""
    if not rects:
        return []

    # Sort by area descending
    rects = sorted(rects, key=lambda r: r[2]*r[3], reverse=True)
    kept = []

    for r in rects:
        x, y, w, h = r[0], r[1], r[2], r[3]
        overlaps = False
        for k in kept:
            kx, ky, kw, kh = k[0], k[1], k[2], k[3]
            # IoU overlap check
            ix1 = max(x, kx); iy1 = max(y, ky)
            ix2 = min(x+w, kx+kw); iy2 = min(y+h, ky+kh)
            if ix2 > ix1 and iy2 > iy1:
                inter = (ix2-ix1) * (iy2-iy1)
                union = w*h + kw*kh - inter
                if inter / max(union, 1) > 0.4:
                    overlaps = True
                    break
        if not overlaps:
            kept.append(r)

    return kept


def _dominant_color(roi):
    """Return dominant HSV hue bucket as a color hint string."""
    if roi.size == 0:
        return 'unknown'
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    hue = hsv[:, :, 0].mean()
    if hue < 15 or hue > 165:
        return 'red'
    elif 15 <= hue < 30:
        return 'orange'
    elif 30 <= hue < 75:
        return 'yellow_green'
    elif 75 <= hue < 105:
        return 'green'
    elif 105 <= hue < 135:
        return 'cyan'
    elif 135 <= hue < 155:
        return 'blue'
    return 'unknown'


# ================================================================
# OCR
# ================================================================

def _ocr_roi(gray_roi, color_roi):
    """OCR a single block ROI with preprocessing."""
    if not TESSERACT:
        return ''
    try:
        # Enlarge small ROIs
        h, w = gray_roi.shape
        if w < 60 or h < 30:
            gray_roi = cv2.resize(
                gray_roi, (max(w*3, 120), max(h*3, 60)),
                interpolation=cv2.INTER_CUBIC
            )

        # Binarise for better OCR
        _, binary = cv2.threshold(
            gray_roi, 0, 255,
            cv2.THRESH_BINARY + cv2.THRESH_OTSU
        )

        # Try both normal and inverted (dark text on light, light on dark)
        text1 = pytesseract.image_to_string(
            binary,
            config='--psm 8 --oem 3 -c tessedit_char_whitelist="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_+*/- "'
        ).strip()
        text2 = pytesseract.image_to_string(
            cv2.bitwise_not(binary),
            config='--psm 8 --oem 3 -c tessedit_char_whitelist="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_+*/- "'
        ).strip()

        # Return whichever is longer
        return text1 if len(text1) >= len(text2) else text2
    except:
        return ''


def _full_ocr_fallback(img_bgr, gray, nid):
    """OCR the whole image and extract block info from text."""
    if not TESSERACT:
        return []
    try:
        pil = Image.fromarray(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB))
        data = pytesseract.image_to_data(
            pil, output_type=pytesseract.Output.DICT
        )
    except:
        return []

    blocks = []
    used_words = set()

    n = len(data['text'])
    for i in range(n):
        word = data['text'][i].strip()
        if not word or i in used_words:
            continue

        conf = int(data['conf'][i])
        if conf < 40:
            continue

        # Collect neighbouring words on the same line
        cluster = [word]
        used_words.add(i)
        x_ref  = data['left'][i]
        y_ref  = data['top'][i]

        for j in range(i+1, n):
            if j in used_words:
                continue
            wj = data['text'][j].strip()
            if not wj:
                continue
            if (abs(data['top'][j] - y_ref) < 20 and
                    abs(data['left'][j] - x_ref) < 200):
                cluster.append(wj)
                used_words.add(j)

        text = ' '.join(cluster)
        btype = _classify(text, 'unknown')

        if btype != 'SubSystem' or 'subsystem' in text.lower():
            name   = _clean_name(text) or f'{btype}_{nid()}'
            params = _extract_params(text, btype)
            bid    = nid()
            blocks.append({
                'id':     bid,
                'type':   btype,
                'name':   name,
                'x':      float(data['left'][i]),
                'y':      float(data['top'][i]),
                'params': params
            })

    return blocks


def _region_fallback(img_bgr, nid):
    """Divide image into grid and assign generic block names."""
    h, w = img_bgr.shape[:2]
    grid_cols = min(5, max(2, w // 150))
    grid_rows = min(3, max(1, h // 120))
    blocks    = []

    generic_types = ['Inport', 'Gain', 'Sum', 'Integrator',
                     'Saturation', 'Outport']

    cell_w = w // grid_cols
    cell_h = h // grid_rows

    for row in range(grid_rows):
        for col in range(grid_cols):
            idx   = row * grid_cols + col
            btype = generic_types[idx % len(generic_types)]
            bid   = nid()
            blocks.append({
                'id':     bid,
                'type':   btype,
                'name':   f'{btype}_{bid}',
                'x':      float(col * cell_w + 20),
                'y':      float(row * cell_h + 20),
                'params': {}
            })

    return blocks


# ================================================================
# Arrow / Connection Detection
# ================================================================

def _detect_arrows(img_bgr, gray, blocks, scale=1.0):
    """
    Detect horizontal/vertical lines that connect blocks.
    Returns list of connection dicts.
    """
    connections = []
    if len(blocks) < 2:
        return connections

    # Build a map of block centres
    centres = {}
    for b in blocks:
        cx = (b['x'] + 60) * scale   # approx centre
        cy = (b['y'] + 20) * scale
        centres[b['id']] = (cx, cy)

    # Detect lines using HoughLinesP
    edges = cv2.Canny(gray, 50, 150)
    lines = cv2.HoughLinesP(
        edges, 1, np.pi/180,
        threshold=30,
        minLineLength=30,
        maxLineGap=15
    )

    if lines is None:
        return connections

    seen = set()
    for line in lines:
        x1, y1, x2, y2 = line[0]

        # Find nearest block to each endpoint
        src_id = _nearest_block_id(x1, y1, centres, max_dist=80)
        dst_id = _nearest_block_id(x2, y2, centres, max_dist=80)

        if src_id and dst_id and src_id != dst_id:
            # Arrow goes left-to-right or top-to-bottom
            src_cx, src_cy = centres[src_id]
            dst_cx, dst_cy = centres[dst_id]

            # Ensure arrow direction (src is to the left/top of dst)
            if src_cx > dst_cx:
                src_id, dst_id = dst_id, src_id

            k = (src_id, dst_id)
            if k not in seen:
                seen.add(k)
                connections.append({
                    'from':     src_id,
                    'to':       dst_id,
                    'src_port': 1,
                    'dst_port': 1
                })

    return connections


def _nearest_block_id(px, py, centres, max_dist=60):
    """Return the block id whose centre is nearest to (px, py)."""
    best_id   = None
    best_dist = max_dist

    for bid, (cx, cy) in centres.items():
        d = ((px - cx)**2 + (py - cy)**2) ** 0.5
        if d < best_dist:
            best_dist = d
            best_id   = bid

    return best_id


# ================================================================
# Text Classification & Utilities
# ================================================================

def _classify(text, color_hint='unknown'):
    """Classify a block from its OCR text and colour hint."""
    tl = text.lower().strip()

    # Exact/longest match first
    best_type  = None
    best_len   = 0
    for kw, btype in BLOCK_KEYWORDS.items():
        if kw in tl and len(kw) > best_len:
            best_type = btype
            best_len  = len(kw)

    if best_type:
        return best_type

    # Colour-based fallback (Simulink uses specific colours)
    color_map = {
        'orange':       'SubSystem',
        'cyan':         'Inport',
        'yellow_green': 'Constant',
        'green':        'Outport',
    }
    if color_hint in color_map:
        return color_map[color_hint]

    return 'SubSystem'


def _clean_name(text):
    """Turn OCR text into a valid C identifier-style name."""
    # Remove non-alphanumeric except spaces and underscores
    name = re.sub(r'[^\w\s]', '', text).strip()
    # Collapse whitespace
    name = re.sub(r'\s+', '_', name)
    # Limit length
    return name[:20] if name else ''


def _extract_params(text, btype):
    """Extract block parameters from OCR text."""
    params = {}
    tl = text.lower()

    # Generic: look for numbers
    nums = re.findall(r'[-\d.]+(?:e[-+]?\d+)?', text)

    if btype == 'Gain' and nums:
        params['Gain'] = nums[0]
    elif btype == 'Constant' and nums:
        params['Value'] = nums[0]
    elif btype == 'Saturation' and len(nums) >= 2:
        vals = sorted([float(n) for n in nums[:2]])
        params['LowerLimit'] = str(vals[0])
        params['UpperLimit'] = str(vals[1])
    elif btype == 'Step' and nums:
        params['Time']   = nums[0]
        params['After']  = nums[1] if len(nums) > 1 else '1.0'
    elif btype in ('TransferFcn',) and nums:
        params['Numerator']   = f'[{nums[0]}]' if nums else '[1]'
        params['Denominator'] = f'[{" ".join(nums[1:3])}]' if len(nums) > 1 else '[1 1]'

    return params