import re
from collections import defaultdict, deque

# ================================================================
# SimToC — Unified C Code Generator v4
# Handles both combinational and time-based models correctly
# ================================================================

def generate_c_code(blocks, connections):
    """Main entry point — auto-detects model type and generates correct C."""

    block_by_id   = {str(b['id']): b for b in blocks}
    block_by_name = {b['name']: b for b in blocks}

    # Normalize connections (name->id or SID->id)
    norm = []
    for c in connections:
        s = str(c.get('from', '')).strip()
        d = str(c.get('to',   '')).strip()
        if not s.isdigit() and s in block_by_name:
            s = str(block_by_name[s]['id'])
        if not d.isdigit() and d in block_by_name:
            d = str(block_by_name[d]['id'])
        if s and d and s != d:
            norm.append({'from': s, 'to': d, 'dst_port': c.get('dst_port', 1)})

    conn_map = {}
    in_map   = {}
    for c in norm:
        conn_map.setdefault(c['from'], []).append(c['to'])
        in_map.setdefault(c['to'], []).append((c['from'], c.get('dst_port', 1)))

    # Detect model characteristics
    TIME_TYPES = {'Integrator','Derivative','UnitDelay','ZeroOrderHold',
                  'TransferFcn','DiscreteTransferFcn','DiscreteFilter',
                  'PIDController','Memory','SineWave','Step',
                  'DiscretePulseGenerator','DiscreteStateSpace','RateLimiter',
                  'Reference'}  # Reference = Counter etc — time-based

    has_time   = any(b['type'] in TIME_TYPES for b in blocks)
    has_inport = any(b['type'] in ('Inport','In') for b in blocks)

    # Find Mux blocks and their sizes
    mux_sizes = {}
    for b in blocks:
        if b['type'] == 'Mux':
            bid = str(b['id'])
            n = max(len(in_map.get(bid, [])),
                    int(_sf(b['params'].get('Inputs', b['params'].get('NumInputPorts','2')), '2')))
            mux_sizes[bid] = max(n, 2)

    ordered = _topo(blocks, conn_map)

    if not has_time and not has_inport:
        return _gen_combinational(blocks, ordered, conn_map, in_map,
                                  block_by_id, mux_sizes)
    else:
        return _gen_time_based(blocks, ordered, conn_map, in_map,
                               block_by_id, mux_sizes, has_inport)


# ================================================================
# COMBINATIONAL — no loop, just compute and print once
# ================================================================

def _gen_combinational(blocks, ordered, conn_map, in_map, block_by_id, mux_sizes):
    lines = [
        "/*",
        " * Auto-generated C — SimToC Converter",
        " * Model type: Combinational (no time dependency)",
        " */",
        "#include <stdio.h>",
        "#include <math.h>",
        "",
        "typedef double Signal;",
        "",
    ]

    # Constants
    cb = [b for b in blocks if b['type'] == 'Constant']
    if cb:
        lines.append("/* Simulink Constant block values */")
        for b in cb:
            v = _parse_val(b['params'].get('Value','1.0'))
            lines.append(f"#define {_sn(b['name']).upper()} ({v})")
        lines.append("")

    # Gains
    gb = [b for b in blocks if b['type'] == 'Gain']
    if gb:
        lines.append("/* Gain values */")
        for b in gb:
            v = _parse_val(b['params'].get('Gain','1.0'))
            lines.append(f"static const Signal GAIN_{_sn(b['name']).upper()} = {v};")
        lines.append("")

    # Mux arrays
    for b in blocks:
        if b['type'] == 'Mux':
            n = mux_sizes.get(str(b['id']), 2)
            lines.append(f"Signal mux_{_sn(b['name'])}[{n}];")
    if any(b['type'] == 'Mux' for b in blocks):
        lines.append("")

    lines += ["int main(void) {", ""]

    for b in ordered:
        bid = str(b['id'])
        bt  = b['type']
        bn  = _sn(b['name'])
        bp  = b.get('params', {})

        raw_ins = sorted(in_map.get(bid, []), key=lambda x: x[1])
        insigs  = [f"sig_{_sn(block_by_id[s]['name'])}"
                   for s, _ in raw_ins if s in block_by_id]
        in0 = insigs[0] if insigs else "0.0"

        lines.append(f"    /* [{bt}] {b['name']} */")
        code = _block_code(bt, bn, insigs, in0, bp, mux_sizes.get(bid, 2), combinational=True)
        lines.extend(f"    {l}" for l in code)
        lines.append("")

    lines += ["    return 0;", "}"]
    return '\n'.join(lines)


# ================================================================
# TIME-BASED — simulation loop, print only at end or on change
# ================================================================

def _gen_time_based(blocks, ordered, conn_map, in_map,
                    block_by_id, mux_sizes, has_inport):

    TIME_TYPES = {'Integrator','Derivative','UnitDelay','ZeroOrderHold',
                  'TransferFcn','DiscreteTransferFcn','DiscreteFilter',
                  'PIDController','Memory','SineWave','Step',
                  'DiscretePulseGenerator','RateLimiter','Reference'}
    state_blocks = [b for b in blocks if b['type'] in TIME_TYPES]

    inports  = [b for b in blocks if b['type'] in ('Inport','In')]
    outports = [b for b in blocks if b['type'] in ('Outport','Out')]

    lines = [
        "/*",
        " * Auto-generated C — SimToC Converter",
        " * Model type: Time-based (uses simulation loop)",
        " */",
        "#include <stdio.h>",
        "#include <math.h>",
        "#include <string.h>",
        "",
        "#ifndef M_PI",
        "#define M_PI 3.14159265358979323846",
        "#endif",
        "",
        "typedef double Signal;",
        "",
    ]

    # State variables
    if state_blocks:
        lines.append("/* State variables */")
        for b in state_blocks:
            n = _sn(b['name'])
            t = b['type']
            p = b.get('params', {})
            if t == 'Integrator':
                ic = _sf(p.get('InitialCondition','0.0'),'0.0')
                lines.append(f"static Signal state_{n} = {ic};")
            elif t == 'Derivative':
                lines.append(f"static Signal deriv_prev_{n} = 0.0;")
            elif t in ('UnitDelay','Memory'):
                ic = _sf(p.get('InitialCondition', p.get('X0','0.0')),'0.0')
                lines.append(f"static Signal delay_{n} = {ic};")
            elif t == 'ZeroOrderHold':
                lines.append(f"static Signal zoh_{n} = 0.0;")
                lines.append(f"static double zoh_t_{n} = 0.0;")
            elif t in ('TransferFcn','DiscreteTransferFcn','DiscreteFilter'):
                lines.append(f"static Signal tf_x_{n}[8] = {{0}};")
                lines.append(f"static Signal tf_y_{n}[8] = {{0}};")
            elif t == 'PIDController':
                lines.append(f"static Signal pid_i_{n} = 0.0;")
                lines.append(f"static Signal pid_p_{n} = 0.0;")
                lines.append(f"static Signal pid_f_{n} = 0.0;")
            elif t == 'Reference':
                # Counter Free-Running
                lines.append(f"static double ref_count_{n} = 0.0;")
            elif t in ('SineWave','Step','DiscretePulseGenerator'):
                pass  # use t directly
            elif t == 'RateLimiter':
                lines.append(f"static Signal rl_prev_{n} = 0.0;")
        lines.append("")

    # Gains and constants
    gb = [b for b in blocks if b['type'] == 'Gain']
    if gb:
        lines.append("/* Gain values */")
        for b in gb:
            v = _parse_val(b['params'].get('Gain','1.0'))
            lines.append(f"static const Signal GAIN_{_sn(b['name']).upper()} = {v};")
        lines.append("")

    cb = [b for b in blocks if b['type'] == 'Constant']
    if cb:
        lines.append("/* Constant values */")
        for b in cb:
            v = _parse_val(b['params'].get('Value','1.0'))
            lines.append(f"#define K_{_sn(b['name']).upper()} ({v})")
        lines.append("")

    # Mux arrays as globals
    for b in blocks:
        if b['type'] == 'Mux':
            n = mux_sizes.get(str(b['id']), 2)
            lines.append(f"static Signal mux_{_sn(b['name'])}[{n}];")
    if any(b['type'] == 'Mux' for b in blocks):
        lines.append("")

    # model_step signature
    sig_params = []
    for ip in inports:
        sig_params.append(f"    Signal {_sn(ip['name'])}_in")
    for op in outports:
        sig_params.append(f"    Signal* {_sn(op['name'])}_out")
    sig_params += ["    double t", "    double dt"]

    lines += [
        "void model_step(",
        ',\n'.join(sig_params) if sig_params else "    void",
        ") {",
        "",
        "    /* Signal wires */",
    ]

    for b in blocks:
        n  = _sn(b['name'])
        bt = b['type']
        if bt == 'Mux':
            lines.append(f"    Signal sig_{n} = 0.0;  /* Mux primary output */")
        elif bt == 'ComplexToRealImag':
            lines.append(f"    Signal sig_{n}_re = 0.0, sig_{n}_im = 0.0;")
        else:
            lines.append(f"    Signal sig_{n} = 0.0;")
    lines.append("")

    lines.append("    /* Signal flow */")
    for b in ordered:
        bid = str(b['id'])
        bt  = b['type']
        bn  = _sn(b['name'])
        bp  = b.get('params', {})

        raw_ins = sorted(in_map.get(bid, []), key=lambda x: x[1])
        insigs  = [f"sig_{_sn(block_by_id[s]['name'])}"
                   for s, _ in raw_ins if s in block_by_id]
        in0 = insigs[0] if insigs else "0.0"

        lines.append(f"")
        lines.append(f"    /* [{bt}] {b['name']} */")
        code = _block_code(bt, bn, insigs, in0, bp, mux_sizes.get(bid, 2), combinational=False)
        lines.extend(f"    {l}" for l in code)

    lines.append("")

    # Assign outports
    for op in outports:
        on   = _sn(op['name'])
        srcs = in_map.get(str(op['id']), [])
        if srcs:
            sb = block_by_id.get(srcs[0][0])
            src_sig = f"sig_{_sn(sb['name'])}" if sb else f"sig_{on}"
        else:
            src_sig = "0.0"
        lines.append(f"    *{on}_out = {src_sig};")

    lines += ["}", ""]

    # model_init
    lines += ["void model_init(void) {"]
    for b in state_blocks:
        n = _sn(b['name'])
        t = b['type']
        p = b.get('params', {})
        if t == 'Integrator':
            ic = _sf(p.get('InitialCondition','0.0'),'0.0')
            lines.append(f"    state_{n} = {ic};")
        elif t == 'Derivative':
            lines.append(f"    deriv_prev_{n} = 0.0;")
        elif t in ('UnitDelay','Memory'):
            ic = _sf(p.get('InitialCondition', p.get('X0','0.0')),'0.0')
            lines.append(f"    delay_{n} = {ic};")
        elif t == 'ZeroOrderHold':
            lines.append(f"    zoh_{n} = 0.0; zoh_t_{n} = 0.0;")
        elif t in ('TransferFcn','DiscreteTransferFcn','DiscreteFilter'):
            lines.append(f"    memset(tf_x_{n},0,sizeof(tf_x_{n}));")
            lines.append(f"    memset(tf_y_{n},0,sizeof(tf_y_{n}));")
        elif t == 'PIDController':
            lines.append(f"    pid_i_{n}=0.0; pid_p_{n}=0.0; pid_f_{n}=0.0;")
        elif t == 'Reference':
            lines.append(f"    ref_count_{n} = 0.0;")
        elif t == 'RateLimiter':
            lines.append(f"    rl_prev_{n} = 0.0;")
    lines += ["}", ""]

    # main
    lines += [
        "int main(void) {",
        "    model_init();",
        "    const double DT = 0.1;   /* sample period — matches Simulink FixedStep */",
        "    const double T  = 10.0;  /* simulation stop time */",
        "    double t = 0.0;",
        "",
    ]

    for op in outports:
        lines.append(f"    Signal {_sn(op['name'])}_result = 0.0;")

    call_args  = [f"{_sn(ip['name'])}_val" for ip in inports]
    call_args += [f"&{_sn(op['name'])}_result" for op in outports]
    call_args += ["t", "DT"]

    lines.append("")
    lines.append("    while (t < T) {")
    for ip in inports:
        lines.append(f"        Signal {_sn(ip['name'])}_val = 1.0;  /* TODO: set input */")
    lines.append(f"        model_step({', '.join(call_args)});")
    for op in outports:
        n = _sn(op['name'])
        lines.append(f'        printf("t=%.2f  {n}=%.4f\\n", t, {n}_result);')
    lines += [
        "        t += DT;",
        "    }",
        "    return 0;",
        "}",
    ]

    return '\n'.join(lines)


# ================================================================
# Block → C lines (shared between both generators)
# ================================================================

def _block_code(bt, bn, insigs, in0, p, mux_n=2, combinational=True):
    """Returns list of C code lines for a block."""
    out = f"sig_{bn}"

    if bt in ('Inport','In'):
        return [f"Signal {out} = {bn}_in;" if combinational else f"{out} = {bn}_in;"]

    if bt in ('Outport','Out'):
        return ["/* output assigned below */"]

    if bt == 'Ground':
        return [f"Signal {out} = 0.0;" if combinational else f"{out} = 0.0;"]

    decl = "Signal " if combinational else ""

    if bt == 'Constant':
        v = _parse_val(p.get('Value','1.0'))
        return [f"{decl}{out} = {v};"]

    if bt == 'Gain':
        return [f"{decl}{out} = GAIN_{bn.upper()} * {in0};"]

    if bt == 'Sum':
        signs_raw = str(p.get('Inputs', p.get('Signs', '++')))
        signs = ''.join(c for c in signs_raw if c in '+-')
        if not signs:
            signs = '+' * max(len(insigs), 1)
        terms = []
        for i, sig in enumerate(insigs):
            s = signs[i] if i < len(signs) else '+'
            if i == 0:
                terms.append(f"-{sig}" if s == '-' else sig)
            else:
                terms.append(f"- {sig}" if s == '-' else f"+ {sig}")
        expr = ' '.join(terms) if terms else '0.0'
        return [f"{decl}{out} = {expr};"]

    if bt == 'Product':
        op_str = p.get('Inputs', p.get('Multiplication','**'))
        if '/' in op_str and len(insigs) >= 2:
            return [f"{decl}{out} = ({insigs[1]} != 0.0) ? {insigs[0]} / {insigs[1]} : 0.0;"]
        expr = ' * '.join(insigs) if len(insigs) >= 2 else f"{in0} * {in0}"
        return [f"{decl}{out} = {expr};"]

    if bt == 'Abs':
        return [f"{decl}{out} = fabs({in0});"]

    if bt == 'Sqrt':
        return [f"{decl}{out} = sqrt(fabs({in0}));"]

    if bt == 'MathFunction':
        op = p.get('Operator', p.get('Function','exp')).lower()
        fn_map = {
            'square': f"({in0})*({in0})", 'sqrt': f"sqrt(fabs({in0}))",
            'exp': f"exp({in0})", 'log': f"log(fabs({in0})+1e-300)",
            'log10': f"log10(fabs({in0})+1e-300)",
            'floor': f"floor({in0})", 'ceil': f"ceil({in0})",
            'round': f"round({in0})", 'sign': f"(({in0}>0.0)-({in0}<0.0))",
            'pow': f"pow({in0},{insigs[1] if len(insigs)>1 else '2.0'})",
        }
        return [f"{decl}{out} = {fn_map.get(op, f'{op}({in0})'+';')};"]

    if bt == 'Trigonometry':
        op = p.get('Operator','sin').lower()
        fn_map = {
            'sin': f"sin({in0})", 'cos': f"cos({in0})", 'tan': f"tan({in0})",
            'asin': f"asin(fmax(-1.0,fmin(1.0,{in0})))",
            'acos': f"acos(fmax(-1.0,fmin(1.0,{in0})))",
            'atan': f"atan({in0})",
            'atan2': f"atan2({insigs[0]},{insigs[1] if len(insigs)>1 else '1.0'})",
        }
        return [f"{decl}{out} = {fn_map.get(op, f'sin({in0})')};"]

    if bt in ('Saturation','Saturate'):
        hi = _sf(p.get('UpperLimit', p.get('UpperSaturationLimit','1.0')),'1.0')
        lo = _sf(p.get('LowerLimit', p.get('LowerSaturationLimit','-1.0')),'-1.0')
        return [f"{decl}{out} = fmax({lo}, fmin({hi}, {in0}));  /* Saturation [{lo},{hi}] */"]

    if bt == 'RelationalOperator':
        op_raw = p.get('Operator', p.get('RelOp','=='))
        op_map = {'==':'==','!=':'!=','<':'<','>':'>','<=':'<=','>=':'>='}
        cop = op_map.get(op_raw,'==')
        in1 = insigs[1] if len(insigs) > 1 else '0.0'
        return [f"{decl}{out} = (Signal)({in0} {cop} {in1});"]

    if bt == 'LogicOperator':
        op = p.get('Operator','AND').upper()
        if op == 'NOT':
            return [f"{decl}{out} = (Signal)(!(int){in0});"]
        lop = {'AND':' && ','OR':' || ','XOR':' ^ '}.get(op,' && ')
        expr = lop.join(f"(int){s}" for s in insigs) if insigs else f"(int){in0}"
        if op in ('NAND','NOR'):
            return [f"{decl}{out} = (Signal)!({expr});"]
        return [f"{decl}{out} = (Signal)({expr});"]

    # ---- MUX — uses global array ----
    if bt == 'Mux':
        code = []
        for i, sig in enumerate(insigs):
            code.append(f"mux_{bn}[{i}] = {sig};")
        # out is just a pointer alias — use array directly
        code.append(f"{decl}{out} = mux_{bn}[0];  /* Mux[0] of {mux_n} signals */")
        return code

    # ---- DEMUX ----
    if bt == 'Demux':
        no = int(_sf(p.get('Outputs', str(max(len(insigs),2))),'2'))
        code = [f"{decl}{out} = {in0};  /* Demux primary output */"]
        for i in range(1, no):
            code.append(f"/* demux_{bn}_out{i+1}: route manually if needed */")
        return code

    if bt == 'Concatenate':
        return [f"{decl}{out} = {in0};"]

    if bt == 'Selector':
        idx = p.get('Indices', p.get('Index','1'))
        return [f"{decl}{out} = {in0};  /* Selector[{idx}] */"]

    if bt in ('BusCreator','BusSelector','Reshape','Transpose','Merge'):
        return [f"{decl}{out} = {in0};"]

    if bt == 'Goto':
        tag = _sn(p.get('GotoTag', p.get('Tag', bn)))
        return [f"bus_{tag} = {in0};"]

    if bt == 'From':
        tag = _sn(p.get('GotoTag', p.get('Tag', bn)))
        return [f"{decl}{out} = bus_{tag};"]

    if bt == 'DataTypeConversion':
        return [f"{decl}{out} = (Signal)({in0});"]

    if bt == 'Quantizer':
        q = _sf(p.get('QuantizationInterval','1.0'),'1.0')
        return [f"{decl}{out} = {q} * round({in0} / {q});"]

    if bt == 'Switch':
        thr  = _sf(p.get('Threshold','0.5'),'0.5')
        crit = p.get('Criteria','u2 >= Threshold')
        cop  = '>=' if '>=' in crit else ('>' if '>' in crit else '!=')
        ctrl = insigs[1] if len(insigs) > 1 else in0
        u3   = insigs[2] if len(insigs) > 2 else '0.0'
        return [f"{decl}{out} = ({ctrl} {cop} {thr}) ? {insigs[0] if insigs else in0} : {u3};"]

    # ---- Time-based blocks ----
    if bt == 'Integrator':
        ic = _sf(p.get('InitialCondition','0.0'),'0.0')
        return [
            f"state_{bn} += {in0} * dt;",
            f"{out} = state_{bn};"
        ]

    if bt == 'Derivative':
        return [
            f"{out} = (dt > 0.0) ? ({in0} - deriv_prev_{bn}) / dt : 0.0;",
            f"deriv_prev_{bn} = {in0};"
        ]

    if bt == 'UnitDelay':
        return [f"{out} = delay_{bn};", f"delay_{bn} = {in0};"]

    if bt == 'Memory':
        return [f"{out} = delay_{bn};", f"delay_{bn} = {in0};"]

    if bt == 'ZeroOrderHold':
        ts = _sf(p.get('SampleTime','0.1'),'0.1')
        return [
            f"zoh_t_{bn} += dt;",
            f"if (zoh_t_{bn} >= {ts}) {{ zoh_{bn} = {in0}; zoh_t_{bn} = 0.0; }}",
            f"{out} = zoh_{bn};"
        ]

    if bt in ('TransferFcn','DiscreteTransferFcn'):
        num_s = p.get('Numerator','[1]')
        den_s = p.get('Denominator','[1 1]')
        num = re.findall(r'[-\d.eE+]+', num_s)
        den = re.findall(r'[-\d.eE+]+', den_s)
        a0  = den[0] if den else '1.0'
        a1  = den[1] if len(den) > 1 else '1.0'
        b0  = num[0] if num else '1.0'
        return [
            f"/* TransferFcn {num_s}/{den_s} */",
            f"tf_x_{bn}[0] += ({in0} - ({a1}/{a0})*tf_x_{bn}[0]) * dt;",
            f"{out} = ({b0}/{a0}) * tf_x_{bn}[0];"
        ]

    if bt == 'DiscreteFilter':
        num_s = p.get('Numerator','[1]')
        den_s = p.get('Denominator','[1]')
        num = re.findall(r'[-\d.eE+]+', num_s)
        den = re.findall(r'[-\d.eE+]+', den_s)
        b0 = num[0] if num else '1.0'
        a0 = den[0] if den else '1.0'
        return [
            f"/* DiscreteFilter B={num_s} A={den_s} */",
            f"tf_x_{bn}[0] = {in0};",
            f"{out} = ({b0}/{a0}) * tf_x_{bn}[0] + tf_y_{bn}[0];",
            f"tf_y_{bn}[0] = {out};"
        ]

    if bt == 'PIDController':
        kp = _sf(p.get('P', p.get('Kp','1.0')),'1.0')
        ki = _sf(p.get('I', p.get('Ki','0.0')),'0.0')
        kd = _sf(p.get('D', p.get('Kd','0.0')),'0.0')
        n  = _sf(p.get('N', p.get('FilterCoefficient','100.0')),'100.0')
        return [
            f"pid_i_{bn} += {in0} * dt;",
            f"pid_f_{bn} += {n}*({in0} - pid_f_{bn}) * dt;",
            f"{out} = {kp}*{in0} + {ki}*pid_i_{bn} + {kd}*{n}*({in0} - pid_f_{bn});",
            f"pid_p_{bn} = {in0};"
        ]

    if bt == 'SineWave':
        amp   = _sf(p.get('Amplitude','1.0'),'1.0')
        freq  = _sf(p.get('Frequency','1.0'),'1.0')
        bias  = _sf(p.get('Bias','0.0'),'0.0')
        phase = _sf(p.get('Phase','0.0'),'0.0')
        return [f"{out} = {bias} + {amp}*sin(2.0*M_PI*{freq}*t + {phase});"]

    if bt == 'Step':
        st  = _sf(p.get('Time','1.0'),'1.0')
        bef = _sf(p.get('Before','0.0'),'0.0')
        aft = _sf(p.get('After','1.0'),'1.0')
        return [f"{out} = (t >= {st}) ? {aft} : {bef};"]

    if bt == 'DiscretePulseGenerator':
        amp    = _sf(p.get('Amplitude','1.0'),'1.0')
        period = _sf(p.get('Period','1.0'),'1.0')
        duty   = _sf(p.get('PulseWidth','50'),'50')
        return [
            f"{{ double _ph=fmod(t,{period}); {out}=(_ph<({period}*{duty}/100.0))?{amp}:0.0; }}"
        ]

    if bt == 'RateLimiter':
        r = _sf(p.get('RisingSlewLimit','1.0'),'1.0')
        f_val = _sf(p.get('FallingSlewLimit','-1.0'),'-1.0')
        return [
            f"{{ Signal _d={in0}-rl_prev_{bn}; Signal _r=_d/dt;",
            f"  if(_r>{r}) _d={r}*dt; if(_r<{f_val}) _d={f_val}*dt;",
            f"  {out}=rl_prev_{bn}+_d; rl_prev_{bn}={out}; }}"
        ]

    # Reference block — Counter Free-Running is most common
    if bt == 'Reference':
        src = p.get('SourceBlock','')
        if 'Counter' in src or 'counter' in src:
            ts = _sf(p.get('SampleTime', p.get('tsamp','1.0')),'1.0')
            return [
                f"/* Counter Free-Running: increments each sample */",
                f"ref_count_{bn} += 1.0;",
                f"{out} = ref_count_{bn};"
            ]
        # Generic reference pass-through
        n_ins = max(len(insigs), 1)
        arr = ', '.join(insigs) if insigs else '0.0'
        return [
            f"/* Reference block: {p.get('SourceBlock','?')} */",
            f"{out} = {in0};  /* implement {_sn(p.get('SourceBlock','ref'))}() manually */"
        ]

    # ---- Sinks ----
    if bt == 'Scope':
        return [f'printf("SCOPE [{bn}]: %g\\n", (double){in0});']

    if bt == 'Display':
        # Check if input is from a Mux (print all elements)
        src_is_mux = in0.startswith('sig_') and any(
            b2['type'] == 'Mux' and _sn(b2['name']) == in0[4:]
            for b2 in []  # simplified - just print the signal
        )
        decl_line = f"Signal {out} = {in0};" if combinational else f"{out} = {in0};"
        return [f'printf("{bn} = %g\\n", (double){in0});', decl_line]

    if bt == 'ToWorkspace':
        var = p.get('VariableName', bn)
        return [f'/* ToWorkspace [{var}]: store {in0} into array */']

    if bt == 'Terminator':
        return [f"(void){in0};"]

    if bt in ('EnablePort','TriggerPort'):
        return [f"{decl}{out} = {in0};" if decl else f"{out} = {in0};"]

    if bt in ('SubSystem','Subsystem'):
        n_ins = max(len(insigs), 1)
        arr = ', '.join(insigs) if insigs else '0.0'
        return [
            f"/* SubSystem [{bn}]: implement {bn}_step() to expand */",
            f"{decl}{out} = {in0};" if decl else f"{out} = {in0};"
        ]

    if bt == 'SFunction':
        sfname = p.get('FunctionName', p.get('SFunctionName', bn))
        return [
            f"/* S-Function: {sfname} */",
            f"{decl}{out} = {in0};  /* implement sfunc_{bn}() */"
            if decl else f"{out} = {in0};  /* implement sfunc_{bn}() */"
        ]

    # Fallback
    return [f"{decl}{out} = {in0};  /* [{bt}] */" if decl else f"{out} = {in0};  /* [{bt}] */"]


# ================================================================
# generate_simple_c_code — kept for backward compatibility
# ================================================================
def generate_simple_c_code(blocks, connections):
    return generate_c_code(blocks, connections)


# ================================================================
# Utilities
# ================================================================

def _sn(name):
    s = re.sub(r'[^a-zA-Z0-9_]', '_', str(name))
    return ('b_' + s) if s and s[0].isdigit() else (s or 'unnamed')

def _sf(val, fallback):
    try: float(str(val).strip()); return str(val).strip()
    except: return fallback

def _parse_val(v):
    """Parse a Simulink value string, return a C-safe number string."""
    v = str(v).strip()
    nums = re.findall(r'[-\d.eE+]+', v)
    return nums[0] if nums and len(nums) == 1 else (nums[0] if nums else v)

def _topo(blocks, conn_map):
    ids    = [str(b['id']) for b in blocks]
    in_deg = defaultdict(int)
    for src, dsts in conn_map.items():
        for d in dsts: in_deg[d] += 1
    queue  = deque(b for b in ids if in_deg[b] == 0)
    order  = []
    by_id  = {str(b['id']): b for b in blocks}
    while queue:
        node = queue.popleft()
        if node in by_id: order.append(by_id[node])
        for nb in conn_map.get(node, []):
            in_deg[nb] -= 1
            if in_deg[nb] == 0: queue.append(nb)
    seen = {str(b['id']) for b in order}
    for b in blocks:
        if str(b['id']) not in seen: order.append(b)
    return order