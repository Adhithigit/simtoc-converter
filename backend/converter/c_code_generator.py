import re

def generate_c_code(blocks, connections):
    lines = []

    lines += [
        "/*",
        " * ================================================",
        " * Auto-generated C Code — SimToC Converter",
        " * Generated from Simulink/Block Diagram",
        " * Review before use in production systems",
        " * ================================================",
        " */",
        "",
        "#include <stdio.h>",
        "#include <math.h>",
        "#include <stdlib.h>",
        "#include <string.h>",
        "",
    ]

    lines += ["typedef double Signal;", ""]

    # State blocks
    state_types = ['Integrator', 'Derivative', 'UnitDelay', 'ZeroOrderHold',
                   'TransferFcn', 'PIDController', 'StateSpace', 'SineWave', 'Step']
    state_blocks = [b for b in blocks if b['type'] in state_types]

    if state_blocks:
        lines.append("/* --- State Variables --- */")
        for b in state_blocks:
            n = _sname(b['name'])
            t = b['type']
            if t == 'Integrator':
                lines.append(f"static Signal state_{n} = 0.0;")
            elif t == 'Derivative':
                lines.append(f"static Signal prev_{n} = 0.0;")
            elif t in ['UnitDelay', 'ZeroOrderHold']:
                lines.append(f"static Signal delay_{n} = 0.0;")
            elif t == 'TransferFcn':
                lines.append(f"static Signal tf_state_{n}[8] = {{0}};")
            elif t == 'PIDController':
                lines.append(f"static Signal pid_int_{n} = 0.0;")
                lines.append(f"static Signal pid_prev_{n} = 0.0;")
            elif t in ['SineWave', 'Step']:
                lines.append(f"static double time_{n} = 0.0;")
        lines.append("")

    # Constants
    const_blocks = [b for b in blocks if b['type'] == 'Constant']
    if const_blocks:
        lines.append("/* --- Constants --- */")
        for b in const_blocks:
            n = _sname(b['name'])
            v = _safe_float(b['params'].get('Value', '1.0'), '1.0')
            lines.append(f"#define CONST_{n.upper()} ({v})")
        lines.append("")

    # Gain params
    gain_blocks = [b for b in blocks if b['type'] == 'Gain']
    if gain_blocks:
        lines.append("/* --- Gain Parameters --- */")
        for b in gain_blocks:
            n = _sname(b['name'])
            v = _safe_float(b['params'].get('Gain', '1.0'), '1.0')
            lines.append(f"static const Signal GAIN_{n.upper()} = {v};")
        lines.append("")

    # Build maps
    conn_map = {}   # src_id -> [dst_id, ...]
    in_map = {}     # dst_id -> [src_id, ...]
    for c in connections:
        s = str(c.get('from', ''))
        d = str(c.get('to', ''))
        conn_map.setdefault(s, []).append(d)
        in_map.setdefault(d, []).append(s)

    block_by_id = {str(b['id']): b for b in blocks}

    inports  = [b for b in blocks if b['type'] in ['Inport', 'In']]
    outports = [b for b in blocks if b['type'] in ['Outport', 'Out']]

    # Function signature
    lines += [
        "/* ================================================",
        "   model_step() — call every simulation time step",
        "   ================================================ */",
        "void model_step(",
    ]

    params = []
    for ip in inports:
        params.append(f"    Signal {_sname(ip['name'])}_in")
    for op in outports:
        params.append(f"    Signal* {_sname(op['name'])}_out")

    if params:
        lines.append(',\n'.join(params))
    else:
        lines.append("    void")
    lines.append(") {")
    lines.append("    static const double dt = 0.001;  /* Sample time in seconds */")
    lines.append("")

    # Signal wire declarations
    all_sig_names = sorted(set(f"sig_{_sname(b['name'])}" for b in blocks))
    if all_sig_names:
        lines.append("    /* Signal wires */")
        for s in all_sig_names:
            lines.append(f"    Signal {s} = 0.0;")
        lines.append("")

    # Topologically sorted block processing
    ordered = _topo_sort(blocks, conn_map)

    lines.append("    /* --- Signal Flow --- */")
    for b in ordered:
        bid  = str(b['id'])
        bt   = b['type']
        bn   = _sname(b['name'])
        bp   = b.get('params', {})
        ins  = in_map.get(bid, [])
        insigs = [f"sig_{_sname(block_by_id[i]['name'])}" for i in ins if i in block_by_id]
        in0  = insigs[0] if insigs else "0.0"
        out  = f"sig_{bn}"

        lines.append("")
        lines.append(f"    /* [{bt}] {b['name']} */")
        for cl in _block_c(bt, bn, out, in0, insigs, bp):
            lines.append(f"    {cl}")

    lines.append("")

    # Assign outputs
    for op in outports:
        on = _sname(op['name'])
        srcs = in_map.get(str(op['id']), [])
        if srcs and srcs[0] in block_by_id:
            src_sig = f"sig_{_sname(block_by_id[srcs[0]]['name'])}"
        else:
            src_sig = f"sig_{on}"
        lines.append(f"    *{on}_out = {src_sig};")

    lines += ["}", ""]

    # Init function
    lines += [
        "/* ================================================",
        "   model_init() — call once before simulation",
        "   ================================================ */",
        "void model_init(void) {",
    ]
    for b in state_blocks:
        n = _sname(b['name'])
        t = b['type']
        if t == 'Integrator':
            ic = _safe_float(b['params'].get('InitialCondition', '0.0'), '0.0')
            lines.append(f"    state_{n} = {ic};")
        elif t == 'Derivative':
            lines.append(f"    prev_{n} = 0.0;")
        elif t in ['UnitDelay', 'ZeroOrderHold']:
            lines.append(f"    delay_{n} = 0.0;")
        elif t == 'PIDController':
            lines.append(f"    pid_int_{n} = 0.0;")
            lines.append(f"    pid_prev_{n} = 0.0;")
        elif t in ['SineWave', 'Step']:
            lines.append(f"    time_{n} = 0.0;")
    lines += ["}", ""]

    # Example main
    lines += [
        "/* ================================================",
        "   main() — example usage",
        "   Compile: gcc model_output.c -lm -o model && ./model",
        "   ================================================ */",
        "int main(void) {",
        "    model_init();",
        "    double t = 0.0;",
        "    const double dt = 0.001;",
        "    const double T = 10.0;",
        "",
    ]

    if outports:
        for op in outports:
            lines.append(f"    Signal {_sname(op['name'])}_result = 0.0;")
        lines.append("")
        lines.append("    while (t < T) {")
        for ip in inports:
            lines.append(f"        Signal {_sname(ip['name'])}_val = 1.0;  /* TODO: set your input */")

        call_args = []
        for ip in inports:
            call_args.append(f"{_sname(ip['name'])}_val")
        for op in outports:
            call_args.append(f"&{_sname(op['name'])}_result")

        lines.append(f"        model_step({', '.join(call_args)});")
        for op in outports:
            n = _sname(op['name'])
            lines.append(f'        printf("t=%.4f  {n}=%.6f\\n", t, {n}_result);')
        lines.append("        t += dt;")
        lines.append("    }")
    else:
        lines.append("    while (t < T) {")
        lines.append("        model_step();")
        lines.append("        t += dt;")
        lines.append("    }")

    lines += ["    return 0;", "}"]

    return '\n'.join(lines)


# ---- Block → C Code ----

def _block_c(btype, bn, out, in0, all_ins, params):
    if btype in ['Inport', 'In']:
        return [f"{out} = {bn}_in;"]

    if btype in ['Outport', 'Out']:
        return [f"/* output assigned after step */"]

    if btype == 'Gain':
        return [f"{out} = GAIN_{bn.upper()} * {in0};"]

    if btype == 'Sum':
        signs = str(params.get('Inputs', params.get('Signs', '++')))
        signs = ''.join(c for c in signs if c in '+-')
        if not signs:
            signs = '+' * max(len(all_ins), 1)
        terms = []
        for i, sig in enumerate(all_ins):
            sign = signs[i] if i < len(signs) else '+'
            terms.append(f"-{sig}" if sign == '-' else sig)
        expr = ' + '.join(terms).replace('+ -', '- ') if terms else in0
        return [f"{out} = {expr};"]

    if btype == 'Product':
        expr = ' * '.join(all_ins) if len(all_ins) >= 2 else f"{in0} * {in0}"
        return [f"{out} = {expr};"]

    if btype == 'Abs':
        return [f"{out} = fabs({in0});"]

    if btype == 'Sqrt':
        return [f"{out} = sqrt(fabs({in0}));"]

    if btype == 'Constant':
        v = _safe_float(params.get('Value', '1.0'), '1.0')
        return [f"{out} = {v};"]

    if btype == 'Integrator':
        return [
            f"state_{bn} += {in0} * dt;",
            f"{out} = state_{bn};"
        ]

    if btype == 'Derivative':
        return [
            f"{out} = ({in0} - prev_{bn}) / dt;",
            f"prev_{bn} = {in0};"
        ]

    if btype == 'UnitDelay':
        return [
            f"{out} = delay_{bn};",
            f"delay_{bn} = {in0};"
        ]

    if btype == 'ZeroOrderHold':
        return [
            f"delay_{bn} = {in0};",
            f"{out} = delay_{bn};"
        ]

    if btype == 'Saturation':
        hi = _safe_float(params.get('UpperLimit', params.get('Upper', '1.0')), '1.0')
        lo = _safe_float(params.get('LowerLimit', params.get('Lower', '-1.0')), '-1.0')
        return [
            f"{out} = {in0};",
            f"if ({out} > {hi}) {out} = {hi};",
            f"if ({out} < {lo}) {out} = {lo};"
        ]

    if btype == 'Switch':
        thr = _safe_float(params.get('Threshold', '0.5'), '0.5')
        ctrl = all_ins[1] if len(all_ins) > 1 else in0
        in2  = all_ins[2] if len(all_ins) > 2 else '0.0'
        return [f"{out} = ({ctrl} >= {thr}) ? {in0} : {in2};"]

    if btype in ['TransferFcn', 'TransferFunction']:
        num = params.get('Numerator', '[1]')
        den = params.get('Denominator', '[1 1]')
        return [
            f"/* TransferFcn Num:{num} Den:{den} — first-order approx */",
            f"tf_state_{bn}[0] += ({in0} - tf_state_{bn}[0]) * dt;",
            f"{out} = tf_state_{bn}[0];"
        ]

    if btype == 'PIDController':
        kp = _safe_float(params.get('P', params.get('Kp', '1.0')), '1.0')
        ki = _safe_float(params.get('I', params.get('Ki', '0.1')), '0.1')
        kd = _safe_float(params.get('D', params.get('Kd', '0.01')), '0.01')
        return [
            f"pid_int_{bn} += {in0} * dt;",
            f"Signal pid_d_{bn} = ({in0} - pid_prev_{bn}) / dt;",
            f"{out} = {kp}*{in0} + {ki}*pid_int_{bn} + {kd}*pid_d_{bn};",
            f"pid_prev_{bn} = {in0};"
        ]

    if btype == 'SineWave':
        amp  = _safe_float(params.get('Amplitude', '1.0'), '1.0')
        freq = _safe_float(params.get('Frequency', '1.0'), '1.0')
        bias = _safe_float(params.get('Bias', '0.0'), '0.0')
        return [
            f"{out} = {bias} + {amp} * sin(2.0 * 3.14159265358979 * {freq} * time_{bn});",
            f"time_{bn} += dt;"
        ]

    if btype == 'Step':
        st  = _safe_float(params.get('Time', '1.0'), '1.0')
        bef = _safe_float(params.get('Before', '0.0'), '0.0')
        aft = _safe_float(params.get('After',  '1.0'), '1.0')
        return [
            f"{out} = (time_{bn} >= {st}) ? {aft} : {bef};",
            f"time_{bn} += dt;"
        ]

    if btype in ['Mux', 'Demux']:
        return [f"{out} = {in0};  /* {btype}: using first signal */"]

    if btype == 'Scope':
        return [f'printf("SCOPE {bn}: %f\\n", (double){in0});']

    if btype in ['SubSystem', 'Subsystem']:
        return [f"{out} = {in0};  /* SubSystem {bn} — expand manually */"]

    if btype == 'StateSpace':
        return [
            f"/* StateSpace {bn} — configure A,B,C,D matrices manually */",
            f"{out} = {in0};"
        ]

    return [
        f"/* Unknown block '{btype}' — pass-through */",
        f"{out} = {in0};"
    ]


# ---- Helpers ----

def _sname(name):
    name = str(name)
    name = re.sub(r'[^a-zA-Z0-9_]', '_', name)
    if name and name[0].isdigit():
        name = 'b_' + name
    return name or 'unnamed'


def _safe_float(val, fallback):
    try:
        float(str(val).strip())
        return str(val).strip()
    except:
        return fallback


def _topo_sort(blocks, conn_map):
    from collections import defaultdict, deque

    ids = [str(b['id']) for b in blocks]
    in_deg = defaultdict(int)

    for src, dsts in conn_map.items():
        for d in dsts:
            in_deg[d] += 1

    queue = deque(bid for bid in ids if in_deg[bid] == 0)
    order = []
    by_id = {str(b['id']): b for b in blocks}

    while queue:
        node = queue.popleft()
        if node in by_id:
            order.append(by_id[node])
        for nb in conn_map.get(node, []):
            in_deg[nb] -= 1
            if in_deg[nb] == 0:
                queue.append(nb)

    seen = {str(b['id']) for b in order}
    for b in blocks:
        if str(b['id']) not in seen:
            order.append(b)

    return order