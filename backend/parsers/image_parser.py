# Image Parser for SimToC — No API key required
# Handles both Simulink screenshots and SimToC website screenshots

import os, re

try:
    import cv2, numpy as np
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False

try:
    import pytesseract
    for _p in ['/opt/homebrew/bin/tesseract','/usr/bin/tesseract','/usr/local/bin/tesseract']:
        if os.path.exists(_p):
            pytesseract.pytesseract.tesseract_cmd = _p
            break
    TESSERACT = True
except ImportError:
    TESSERACT = False

# ── Type keywords ─────────────────────────────────────────────────
TYPE_KW = {
    'constant':'Constant','gain':'Gain',
    'subtract':'Sum','sum':'Sum',
    'multiply':'Product','divide':'Product','product':'Product',
    'integrator':'Integrator','derivative':'Derivative',
    'saturation':'Saturation','saturate':'Saturation',
    'sat_sum':'Saturation','sat_sub':'Saturation',
    'sat_mult':'Saturation','sat_div':'Saturation',
    'transfer fcn':'TransferFcn','transfer':'TransferFcn',
    'pid':'PIDController','unit delay':'UnitDelay','delay':'UnitDelay',
    'zero order':'ZeroOrderHold','zero-order':'ZeroOrderHold',
    'display':'Display','result':'Display','scope':'Scope',
    'inport':'Inport','outport':'Outport',
    'in1':'Inport','out1':'Outport',
    'mux':'Mux','demux':'Demux','switch':'Switch',
    'step':'Step','sine wave':'SineWave','sine':'SineWave',
    'subsystem':'SubSystem','counter':'Reference',
}

# ── Color bands: (HSV_low, HSV_high, default_type, min_V) ─────────
# SimToC website uses specific colours per block type
COLORS = [
    ([20,100, 60], [42,200,160], 'Constant'),   # dark yellow
    ([40,100, 60], [85,255,200], 'Sum'),         # green
    ([95, 60, 40], [135,220,190],'Product'),     # blue/teal
    ([130,50, 60], [165,255,220],'Outport'),     # purple
    ([0, 120, 80], [12,255,200], 'SFunction'),   # red
    ([0,   0,180], [180, 35,240],'Display'),     # light gray
]


def parse_image(filepath):
    if not CV2_AVAILABLE:
        raise ValueError("OpenCV not installed. Add 'opencv-python-headless' to requirements.txt.")

    img = cv2.imread(filepath)
    if img is None:
        raise ValueError("Could not read image. Use PNG or JPG.")

    h, w = img.shape[:2]
    scale = 1.0
    if w > 2500:
        scale = 2500.0 / w
        img = cv2.resize(img, (2500, int(h*scale)))

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    hsv  = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

    counter = [0]
    def nid():
        counter[0] += 1
        return str(counter[0])

    # Detect image background
    bg = float(img[:30, :30].mean())
    is_dark = bg < 100

    blocks = _find_blocks(img, gray, hsv, nid, scale, is_dark)

    if not blocks:
        raise ValueError(
            "No blocks detected in image.\n"
            "Tip: For perfect results upload the .slx file directly.\n"
            "Screenshots must be clear and high resolution."
        )

    connections = _find_connections(gray, blocks, scale)
    return blocks, connections, 0.1, 10.0


def _find_blocks(img, gray, hsv, nid, scale, is_dark):
    all_blocks = []

    if is_dark:
        # SimToC website — use colour segmentation
        for lower, upper, default_type in COLORS:
            mask = cv2.inRange(hsv, np.array(lower, np.uint8), np.array(upper, np.uint8))
            k    = np.ones((3,3), np.uint8)
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k)
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  k)
            contours,_ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            for c in contours:
                x,y,bw,bh = cv2.boundingRect(c)
                if bw < 30 or bh < 12 or bw/max(bh,1) > 12:
                    continue
                text  = _ocr(gray, x, y, bw, bh)
                btype, bname = _parse_text(text, default_type)
                params = _get_params(text, btype)
                bid = nid()
                all_blocks.append({
                    'id':bid,'type':btype,'name':bname,
                    'x':float(x)/scale,'y':float(y)/scale,'params':params,
                    '_px':x+bw//2,'_py':y+bh//2
                })
    else:
        # Actual Simulink screenshot — white/light background
        blurred = cv2.GaussianBlur(gray,(3,3),0)
        for thr_lo, thr_hi in [(30,100),(50,150)]:
            edged = cv2.Canny(blurred, thr_lo, thr_hi)
            edged = cv2.dilate(edged, np.ones((2,2),np.uint8))
            contours,_ = cv2.findContours(edged, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for c in contours:
                peri   = cv2.arcLength(c,True)
                approx = cv2.approxPolyDP(c, 0.04*peri, True)
                if len(approx) not in (4,5,6): continue
                x,y,bw,bh = cv2.boundingRect(approx)
                ar = bw/max(bh,1)
                if bw < 25 or bh < 15 or bw > gray.shape[1]*.75 or ar < 0.25 or ar > 8:
                    continue
                text  = _ocr(gray, x, y, bw, bh)
                # Colour hint from block fill
                roi_h = hsv[y:y+bh, x:x+bw]
                hint  = 'SubSystem'
                if roi_h.size > 0:
                    hue = roi_h[:,:,0].mean()
                    sat = roi_h[:,:,1].mean()
                    if sat > 40:
                        hint = ('Constant' if 20<=hue<35 else
                                'Sum'      if 40<=hue<80 else
                                'Product'  if 100<=hue<130 else 'SubSystem')
                btype, bname = _parse_text(text, hint)
                bid = nid()
                all_blocks.append({
                    'id':bid,'type':btype,'name':bname,
                    'x':float(x)/scale,'y':float(y)/scale,
                    'params':_get_params(text,btype),
                    '_px':x+bw//2,'_py':y+bh//2
                })

    return _dedup(all_blocks)


def _parse_text(raw, default_type):
    """Extract block type and name from OCR text."""
    lines = [l.strip() for l in (raw or '').split('\n') if l.strip()]
    if not lines:
        return default_type, default_type

    # Find block type from any line
    btype = default_type
    for line in lines:
        tl = line.lower()
        # Longest keyword match
        best, bl = None, 0
        for kw, bt in TYPE_KW.items():
            if kw in tl and len(kw) > bl:
                best, bl = bt, len(kw)
        if best:
            btype = best
            break

    # Name = line that isn't a block type keyword, or just the last line
    name_lines = []
    for line in lines:
        tl = line.lower()
        is_kw = any(kw in tl for kw in TYPE_KW)
        if not is_kw or len(line.strip()) <= 3:
            cleaned = re.sub(r'[^\w\s]','',line).strip()
            if cleaned:
                name_lines.append(cleaned)

    bname = name_lines[0][:20] if name_lines else (lines[-1][:20] if lines else btype)
    return btype, bname or btype


def _get_params(text, btype):
    nums = re.findall(r'[-\d.]+', text or '')
    p = {}
    if btype == 'Gain' and nums:        p['Gain']  = nums[0]
    elif btype == 'Constant' and nums:  p['Value'] = nums[0]
    elif btype == 'Saturation' and len(nums) >= 2:
        v = sorted([float(n) for n in nums[:2]])
        p['LowerLimit'] = str(v[0]); p['UpperLimit'] = str(v[1])
    elif btype == 'Reference':
        p['SourceBlock'] = 'simulink/Sources/Counter Free-Running'
        p['SourceType']  = 'Counter Free-Running'
    return p


def _ocr(gray, x, y, w, h):
    if not TESSERACT: return ''
    try:
        roi = gray[y:y+h, x:x+w]
        sc  = max(3, 80//max(w,1))
        big = cv2.resize(roi,(w*sc,h*sc),interpolation=cv2.INTER_CUBIC)
        _,b1 = cv2.threshold(big,0,255,cv2.THRESH_BINARY+cv2.THRESH_OTSU)
        b2   = cv2.bitwise_not(b1)
        cfg  = '--psm 6 --oem 3'
        t1   = pytesseract.image_to_string(b1, config=cfg).strip()
        t2   = pytesseract.image_to_string(b2, config=cfg).strip()
        return t1 if len(t1) >= len(t2) else t2
    except: return ''


def _find_connections(gray, blocks, scale):
    if len(blocks) < 2:
        return []
    centres = {b['id']:(b.get('_px', b['x']*scale+55),
                         b.get('_py', b['y']*scale+18)) for b in blocks}
    for b in blocks:
        b.pop('_px',None); b.pop('_py',None)

    conns, seen = [], set()
    edges = cv2.Canny(gray, 50, 150)
    lines = cv2.HoughLinesP(edges,1,3.14159/180,threshold=25,
                             minLineLength=25,maxLineGap=12)
    if lines is not None:
        for ln in lines:
            x1,y1,x2,y2 = ln[0]
            sid = _nearest(x1,y1,centres,70)
            did = _nearest(x2,y2,centres,70)
            if not(sid and did and sid!=did): continue
            if centres[sid][0] > centres[did][0]+5:
                sid,did = did,sid
            k = (sid,did)
            if k not in seen:
                seen.add(k)
                dp = 1
                dst = next((b for b in blocks if b['id']==did),None)
                src = next((b for b in blocks if b['id']==sid),None)
                if dst and dst['type']=='Sum' and src:
                    dp = 1 if src['y'] <= dst['y'] else 2
                conns.append({'from':sid,'to':did,'src_port':1,'dst_port':dp})

    if not conns and len(blocks) > 1:
        sb = sorted(blocks, key=lambda b: b['x'])
        for i in range(len(sb)-1):
            if abs(sb[i]['y']-sb[i+1]['y']) < 100:
                k = (sb[i]['id'],sb[i+1]['id'])
                if k not in seen:
                    seen.add(k)
                    conns.append({'from':sb[i]['id'],'to':sb[i+1]['id'],
                                  'src_port':1,'dst_port':1})
    return conns


def _nearest(px,py,centres,md):
    best_id,bd = None,md
    for bid,(cx,cy) in centres.items():
        d=((px-cx)**2+(py-cy)**2)**.5
        if d<bd: bd,best_id=d,bid
    return best_id

def _dedup(blocks):
    kept=[]
    for b in blocks:
        px=b.get('_px',b['x']); py=b.get('_py',b['y'])
        if not any(abs(px-k.get('_px',k['x']))<45 and
                   abs(py-k.get('_py',k['y']))<35 for k in kept):
            kept.append(b)
    return kept