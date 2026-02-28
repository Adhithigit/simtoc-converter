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
        "#include <complex.h>",
        "",
    ]

    lines += ["typedef double Signal;", "typedef double complex CSignal;", ""]

    # Build connection maps
    block_by_id   = {str(b['id']): b for b in blocks}
    block_by_name = {b['name']: b for b in blocks}

    # Normalize connections
    norm_conns = []
    for c in connections:
        s = str(c.get('from', '')).strip()
        d = str(c.get('to',   '')).strip()
        if not s.isdigit() and s in block_by_name:
            s = str(block_by_name[s]['id'])
        if not d.isdigit() and d in block_by_name:
            d = str(block_by_name[d]['id'])
        if s and d and s != d:
            norm_conns.append({'from': s, 'to': d})

    conn_map = {}
    in_map   = {}
    for c in norm_conns:
        conn_map.setdefault(c['from'], []).append(c['to'])
        in_map.setdefault(c['to'],   []).append(c['from'])

    inports  = [b for b in blocks if b['type'] in ['Inport', 'In']]
    outports = [b for b in blocks if b['type'] in ['Outport', 'Out']]

    # ---- Categorize blocks ----
    state_types = [
        'Integrator', 'Derivative', 'UnitDelay', 'ZeroOrderHold',
        'TransferFcn', 'PIDController', 'DiscreteTransferFcn',
        'DiscreteFilter', 'SineWave', 'Step', 'Memory',
        'DiscretePulseGenerator'
    ]
    state_blocks = [b for b in blocks if b['type'] in state_types]

    # Mux/Demux blocks
    mux_blocks   = [b for b in blocks if b['type'] == 'Mux']
    demux_blocks = [b for b in blocks if b['type'] == 'Demux']

    # SFunction blocks
    sfunc_blocks = [b for b in blocks if b['type'] == 'SFunction']

    # ---- State variables ----
    if state_blocks:
        lines.append("/* --- State Variables --- */")
        for b in state_blocks:
            n = _sn(b['name'])
            t = b['type']
            if t in ['Integrator']:
                lines.append(f"static Signal state_{n} = 0.0;")
            elif t == 'Derivative':
                lines.append(f"static Signal prev_{n} = 0.0;")
            elif t in ['UnitDelay', 'ZeroOrderHold', 'Memory']:
                lines.append(f"static Signal delay_{n} = 0.0;")
            elif t in ['TransferFcn', 'DiscreteTransferFcn']:
                order = 4
                lines.append(f"static Signal tf_x_{n}[{order}] = {{0}};")
                lines.append(f"static Signal tf_y_{n}[{order}] = {{0}};")
            elif t == 'DiscreteFilter':
                lines.append(f"static Signal filt_x_{n}[8] = {{0}};")
                lines.append(f"static Signal filt_y_{n}[8] = {{0}};")
            elif t == 'PIDController':
                lines.append(f"static Signal pid_int_{n}  = 0.0;")
                lines.append(f"static Signal pid_prev_{n} = 0.0;")
            elif t in ['SineWave', 'Step', 'DiscretePulseGenerator']:
                lines.append(f"static double time_{n} = 0.0;")
        lines.append("")

    # ---- Mux arrays ----
    if mux_blocks:
        lines.append("/* --- Mux Signal Arrays --- */")
        for b in mux_blocks:
            n     = _sn(b['name'])
            ports = int(_sf(b['params'].get('Inputs', '2'), '2'))
            lines.append(f"static Signal mux_{n}[{ports}];")
        lines.append("")

    # ---- SFunction prototypes ----
    if sfunc_blocks:
        lines.append("/* --- S-Function Declarations --- */")
        lines.append("/* NOTE: Implement these functions based on your S-Function source */")
        for b in sfunc_blocks:
            n       = _sn(b['name'])
            sfname  = b['params'].get('FunctionName', b['params'].get('Name', n))
            sfname  = _sn(sfname)
            lines.append(f"/* S-Function: {b['name']} → {sfname} */")
            lines.append(f"Signal sfunc_{n}(Signal* inputs, int n_inputs, Signal* state, int n_state);")
        lines.append("")

    # ---- Constants ----
    const_blocks = [b for b in blocks if b['type'] == 'Constant']
    if const_blocks:
        lines.append("/* --- Constants --- */")
        for b in const_blocks:
            n = _sn(b['name'])
            v = _sf(b['params'].get('Value', '1.0'), '1.0')
            # Handle vector/matrix constants
            if '[' in v or ';' in v:
                nums = re.findall(r'[-\d.e+]+', v)
                if nums:
                    lines.append(f"static const Signal CONST_{n.upper()}[{len(nums)}] = {{{', '.join(nums)}}};")
                else:
                    lines.append(f"/* Constant {b['name']}: complex value = {v} */")
            else:
                lines.append(f"#define CONST_{n.upper()} ({v})")
        lines.append("")

    # ---- Gain parameters ----
    gain_blocks = [b for b in blocks if b['type'] == 'Gain']
    if gain_blocks:
        lines.append("/* --- Gain Parameters --- */")
        for b in gain_blocks:
            n = _sn(b['name'])
            v = _sf(b['params'].get('Gain', '1.0'), '1.0')
            if '[' in v or ';' in v:
                nums = re.findall(r'[-\d.e+]+', v)
                if nums:
                    lines.append(f"static const Signal GAIN_{n.upper()}[{len(nums)}] = {{{', '.join(nums)}}};")
                else:
                    lines.append(f"/* Gain {b['name']}: matrix gain = {v} */")
                    lines.append(f"static const Signal GAIN_{n.upper()} = 1.0; /* TODO: implement matrix gain */")
            else:
                lines.append(f"static const Signal GAIN_{n.upper()} = {v};")
        lines.append("")

    # ---- Goto/From signal table ----
    goto_blocks = [b for b in blocks if b['type'] == 'Goto']
    from_blocks = [b for b in blocks if b['type'] == 'From']
    if goto_blocks or from_blocks:
        lines.append("/* --- Goto/From Signal Bus --- */")
        tags = set()
        for b in goto_blocks + from_blocks:
            tag = _sn(b['params'].get('GotoTag', b['params'].get('Tag', b['name'])))
            tags.add(tag)
        for tag in sorted(tags):
            lines.append(f"static Signal gotobus_{tag} = 0.0;")
        lines.append("")

    # ---- Function signature ----
    lines += [
        "/* ================================================",
        "   model_step() — call every simulation time step",
        "   ================================================ */",
        "void model_step(",
    ]

    params_list = []
    for ip in inports:
        params_list.append(f"    Signal {_sn(ip['name'])}_in")
    for op in outports:
        params_list.append(f"    Signal* {_sn(op['name'])}_out")

    lines.append(',\n'.join(params_list) if params_list else "    void")
    lines += [") {", "    static const double dt = 0.001;  /* Sample time (seconds) */", ""]

    # ---- Signal wire declarations ----
    lines.append("    /* Signal wires */")
    for b in blocks:
        n = _sn(b['name'])
        if b['type'] == 'Mux':
            ports = int(_sf(b['params'].get('Inputs', '2'), '2'))
            lines.append(f"    Signal sig_{n}[{ports}];")
        elif b['type'] in ['ComplexToRealImag']:
            lines.append(f"    Signal sig_{n}_re = 0.0;")
            lines.append(f"    Signal sig_{n}_im = 0.0;")
        else:
            lines.append(f"    Signal sig_{n} = 0.0;")
    lines.append("")

    # ---- Signal flow ----
    ordered = _topo(blocks, conn_map)
    lines.append("    /* --- Signal Flow --- */")

    for b in ordered:
        bid = str(b['id'])
        bt  = b['type']
        bn  = _sn(b['name'])
        bp  = b.get('params', {})

        src_ids = in_map.get(bid, [])
        insigs  = []
        for sid in src_ids:
            sb = block_by_id.get(sid)
            if sb:
                insigs.append(f"sig_{_sn(sb['name'])}")

        in0 = insigs[0] if insigs else "0.0"
        out = f"sig_{bn}"

        lines.append("")
        lines.append(f"    /* [{bt}] {b['name']} */")
        for cl in _to_c(bt, bn, out, in0, insigs, bp, b):
            lines.append(f"    {cl}")

    lines.append("")

    # Assign outputs
    for op in outports:
        on   = _sn(op['name'])
        srcs = in_map.get(str(op['id']), [])
        if srcs:
            sb = block_by_id.get(srcs[0])
            src_sig = f"sig_{_sn(sb['name'])}" if sb else f"sig_{on}"
        else:
            src_sig = f"sig_{on}"
        lines.append(f"    *{on}_out = {src_sig};")

    lines += ["}", ""]

    # ---- Init function ----
    lines += [
        "/* ================================================",
        "   model_init() — call once before simulation",
        "   ================================================ */",
        "void model_init(void) {",
    ]
    for b in state_blocks:
        n = _sn(b['name'])
        t = b['type']
        if t == 'Integrator':
            ic = _sf(b['params'].get('InitialCondition', '0.0'), '0.0')
            lines.append(f"    state_{n} = {ic};")
        elif t == 'Derivative':
            lines.append(f"    prev_{n} = 0.0;")
        elif t in ['UnitDelay', 'ZeroOrderHold', 'Memory']:
            ic = _sf(b['params'].get('InitialCondition', b['params'].get('X0', '0.0')), '0.0')
            lines.append(f"    delay_{n} = {ic};")
        elif t in ['TransferFcn', 'DiscreteTransferFcn']:
            lines.append(f"    memset(tf_x_{n}, 0, sizeof(tf_x_{n}));")
            lines.append(f"    memset(tf_y_{n}, 0, sizeof(tf_y_{n}));")
        elif t == 'DiscreteFilter':
            lines.append(f"    memset(filt_x_{n}, 0, sizeof(filt_x_{n}));")
            lines.append(f"    memset(filt_y_{n}, 0, sizeof(filt_y_{n}));")
        elif t == 'PIDController':
            lines.append(f"    pid_int_{n}  = 0.0;")
            lines.append(f"    pid_prev_{n} = 0.0;")
        elif t in ['SineWave', 'Step', 'DiscretePulseGenerator']:
            lines.append(f"    time_{n} = 0.0;")
    lines += ["}", ""]

    # ---- S-Function stubs ----
    if sfunc_blocks:
        lines += [
            "/* ================================================",
            "   S-Function Stubs",
            "   Replace these with your actual S-Function logic",
            "   ================================================ */",
        ]
        for b in sfunc_blocks:
            n      = _sn(b['name'])
            sfname = _sn(b['params'].get('FunctionName', b['params'].get('Name', n)))
            params_str = b['params'].get('Parameters', '')
            lines += [
                f"Signal sfunc_{n}(Signal* inputs, int n_inputs, Signal* state, int n_state) {{",
                f"    /* S-Function: {b['name']} */",
                f"    /* Original function: {sfname} */",
            ]
            if params_str:
                lines.append(f"    /* Parameters: {params_str} */")
            lines += [
                f"    /* TODO: Implement your S-Function logic here */",
                f"    return (n_inputs > 0) ? inputs[0] : 0.0;",
                f"}}",
                "",
            ]

    # ---- Example main ----
    lines += [
        "/* ================================================",
        "   main() — example usage",
        "   Compile: gcc model_output.c -lm -o model && ./model",
        "   ================================================ */",
        "int main(void) {",
        "    model_init();",
        "    double t   = 0.0;",
        "    const double dt  = 0.001;",
        "    const double T   = 10.0;",
        "",
    ]

    if outports:
        for op in outports:
            lines.append(f"    Signal {_sn(op['name'])}_result = 0.0;")
        lines.append("")
        lines.append("    while (t < T) {")
        for ip in inports:
            lines.append(f"        Signal {_sn(ip['name'])}_val = 1.0;  /* TODO: set input */")

        call_args = [f"{_sn(ip['name'])}_val" for ip in inports] + \
                    [f"&{_sn(op['name'])}_result" for op in outports]
        lines.append(f"        model_step({', '.join(call_args)});")
        for op in outports:
            n = _sn(op['name'])
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


# ================================================================
# Block → C Code (all block types)
# ================================================================

def _to_c(bt, bn, out, in0, ins, params, block=None):

    # ---- Basic source blocks ----
    if bt in ['Inport', 'In']:
        return [f"{out} = {bn}_in;"]

    if bt in ['Outport', 'Out']:
        return ["/* output assigned after step */"]

    if bt == 'Constant':
        v = params.get('Value', '1.0')
        nums = re.findall(r'[-\d.e+]+', v)
        if nums and len(nums) == 1:
            return [f"{out} = {nums[0]};"]
        elif nums:
            return [f"{out} = {nums[0]};  /* vector constant — using first element */"]
        return [f"{out} = 1.0;  /* TODO: set constant value */"]

    if bt == 'Ground':
        return [f"{out} = 0.0;"]

    # ---- Math blocks ----
    if bt == 'Gain':
        v = params.get('Gain', '1.0')
        nums = re.findall(r'[-\d.e+]+', v)
        if nums and len(nums) == 1:
            return [f"{out} = GAIN_{bn.upper()} * {in0};"]
        return [f"{out} = GAIN_{bn.upper()} * {in0};  /* TODO: check matrix gain */"]

    if bt == 'Sum':
        signs = str(params.get('Inputs', params.get('Signs', '++')))
        signs = ''.join(c for c in signs if c in '+-')
        if not signs:
            signs = '+' * max(len(ins), 1)
        terms = []
        for i, sig in enumerate(ins):
            sign = signs[i] if i < len(signs) else '+'
            terms.append(f"-{sig}" if sign == '-' else sig)
        expr = ' + '.join(terms).replace('+ -', '- ') if terms else in0
        return [f"{out} = {expr};"]

    if bt == 'Product':
        op = params.get('Inputs', params.get('Multiplication', '**'))
        if '/' in op:
            # Division
            if len(ins) >= 2:
                return [f"{out} = ({ins[1]} != 0.0) ? {ins[0]} / {ins[1]} : 0.0;"]
            return [f"{out} = ({in0} != 0.0) ? 1.0 / {in0} : 0.0;"]
        expr = ' * '.join(ins) if len(ins) >= 2 else f"{in0} * {in0}"
        return [f"{out} = {expr};"]

    if bt == 'Abs':
        return [f"{out} = fabs({in0});"]

    if bt == 'Sqrt':
        return [f"{out} = sqrt(fabs({in0}));"]

    if bt == 'MathFunction':
        op = params.get('Operator', params.get('Function', 'exp')).lower()
        math_map = {
            'exp':   f"exp({in0})",
            'log':   f"log(fabs({in0}) + 1e-10)",
            'log10': f"log10(fabs({in0}) + 1e-10)",
            'square':f"({in0} * {in0})",
            'sqrt':  f"sqrt(fabs({in0}))",
            'pow':   f"pow({in0}, {ins[1] if len(ins)>1 else '2.0'})",
            'floor': f"floor({in0})",
            'ceil':  f"ceil({in0})",
            'round': f"round({in0})",
            'mod':   f"fmod({in0}, {ins[1] if len(ins)>1 else '1.0'})",
            'rem':   f"remainder({in0}, {ins[1] if len(ins)>1 else '1.0'})",
            'sign':  f"(({in0} > 0.0) ? 1.0 : (({in0} < 0.0) ? -1.0 : 0.0))",
            '10^u':  f"pow(10.0, {in0})",
        }
        expr = math_map.get(op, f"/* unknown math op: {op} */ {in0}")
        return [f"{out} = {expr};"]

    if bt == 'Trigonometry':
        op = params.get('Operator', 'sin').lower()
        trig_map = {
            'sin':   f"sin({in0})",
            'cos':   f"cos({in0})",
            'tan':   f"tan({in0})",
            'asin':  f"asin({in0})",
            'acos':  f"acos({in0})",
            'atan':  f"atan({in0})",
            'atan2': f"atan2({ins[0]}, {ins[1] if len(ins)>1 else '1.0'})",
            'sinh':  f"sinh({in0})",
            'cosh':  f"cosh({in0})",
            'tanh':  f"tanh({in0})",
        }
        expr = trig_map.get(op, f"sin({in0})")
        return [f"{out} = {expr};"]

    if bt == 'DotProduct':
        if len(ins) >= 2:
            return [f"{out} = {ins[0]} * {ins[1]};  /* DotProduct */"]
        return [f"{out} = {in0} * {in0};"]

    # ---- Signal routing ----
    if bt == 'Mux':
        n_inputs = int(_sf(params.get('Inputs', str(max(len(ins), 2))), '2'))
        code = []
        for i, sig in enumerate(ins[:n_inputs]):
            code.append(f"mux_{bn}[{i}] = {sig};")
        code.append(f"{out} = mux_{bn}[0];  /* Mux: array mux_{bn}[] holds all {n_inputs} signals */")
        return code

    if bt == 'Demux':
        n_outputs = int(_sf(params.get('Outputs', '2'), '2'))
        code = [f"/* Demux: splits {in0} into {n_outputs} signals */"]
        code.append(f"{out} = {in0};")
        for i in range(n_outputs):
            code.append(f"/* demux_{bn}_out{i+1} = component {i} of {in0} */")
        return code

    if bt == 'Concatenate':
        code = [f"/* Concatenate: joins {len(ins)} signals */"]
        code.append(f"{out} = {in0};  /* Using first input — extend for vector signals */")
        return code

    if bt == 'Selector':
        idx = params.get('Indices', params.get('Index', '1'))
        return [
            f"/* Selector: selecting index {idx} from {in0} */",
            f"{out} = {in0};  /* TODO: implement indexing */"
        ]

    if bt == 'Reshape':
        return [f"{out} = {in0};  /* Reshape: dimensions change but data preserved */"]

    if bt == 'BusCreator':
        code = [f"/* BusCreator: combines {len(ins)} signals into bus */"]
        code.append(f"{out} = {in0};  /* Using first signal */")
        return code

    if bt == 'BusSelector':
        code = [f"/* BusSelector: extracts signals from bus */"]
        code.append(f"{out} = {in0};")
        return code

    if bt == 'Goto':
        tag = _sn(params.get('GotoTag', params.get('Tag', bn)))
        return [f"gotobus_{tag} = {in0};  /* Goto tag: {tag} */"]

    if bt == 'From':
        tag = _sn(params.get('GotoTag', params.get('Tag', bn)))
        return [f"{out} = gotobus_{tag};  /* From tag: {tag} */"]

    if bt == 'Merge':
        return [f"{out} = {in0};  /* Merge: using first active input */"]

    # ---- Dynamic/State blocks ----
    if bt == 'Integrator':
        method = params.get('IntegratorMethod', 'Forward Euler')
        ic     = _sf(params.get('InitialCondition', '0.0'), '0.0')
        return [
            f"state_{bn} += {in0} * dt;  /* {method} integration */",
            f"{out} = state_{bn};"
        ]

    if bt == 'Derivative':
        return [
            f"{out} = ({in0} - prev_{bn}) / dt;",
            f"prev_{bn} = {in0};"
        ]

    if bt == 'UnitDelay':
        ic = _sf(params.get('InitialCondition', params.get('X0', '0.0')), '0.0')
        return [
            f"{out} = delay_{bn};",
            f"delay_{bn} = {in0};"
        ]

    if bt == 'ZeroOrderHold':
        return [
            f"delay_{bn} = {in0};",
            f"{out} = delay_{bn};"
        ]

    if bt == 'Memory':
        ic = _sf(params.get('InitialCondition', params.get('X0', '0.0')), '0.0')
        return [
            f"{out} = delay_{bn};  /* Memory block */",
            f"delay_{bn} = {in0};"
        ]

    if bt in ['TransferFcn', 'DiscreteTransferFcn']:
        num = params.get('Numerator', params.get('Numerator', '[1]'))
        den = params.get('Denominator', '[1 1]')
        num_coeffs = re.findall(r'[-\d.e+]+', num)
        den_coeffs = re.findall(r'[-\d.e+]+', den)
        code = [
            f"/* Transfer Function */",
            f"/* Numerator:   {num} */",
            f"/* Denominator: {den} */",
        ]
        if len(den_coeffs) >= 2:
            a1 = den_coeffs[1] if len(den_coeffs) > 1 else '1.0'
            a0 = den_coeffs[0]
            b0 = num_coeffs[0] if num_coeffs else '1.0'
            code += [
                f"tf_x_{bn}[0] += ({in0} - ({a1}/{a0})*tf_x_{bn}[0]) * dt;",
                f"{out} = ({b0}/{a0}) * tf_x_{bn}[0];"
            ]
        else:
            code.append(f"{out} = {in0};")
        return code

    if bt == 'DiscreteFilter':
        num = params.get('Numerator', '[1]')
        den = params.get('Denominator', '[1]')
        return [
            f"/* DiscreteFilter Num:{num} Den:{den} */",
            f"filt_x_{bn}[0] = {in0};",
            f"{out} = filt_x_{bn}[0];  /* TODO: implement full filter difference equation */",
            f"/* Shift state: memmove(&filt_x_{bn}[1], &filt_x_{bn}[0], 7*sizeof(Signal)); */"
        ]

    if bt == 'Quantizer':
        interval = _sf(params.get('QuantizationInterval', '1.0'), '1.0')
        return [f"{out} = round({in0} / {interval}) * {interval};  /* Quantizer */"]

    # ---- Control blocks ----
    if bt == 'Saturation':
        hi = _sf(params.get('UpperLimit', params.get('Upper', '1.0')),  '1.0')
        lo = _sf(params.get('LowerLimit', params.get('Lower', '-1.0')), '-1.0')
        return [
            f"{out} = {in0};",
            f"if ({out} > {hi}) {out} = {hi};",
            f"if ({out} < {lo}) {out} = {lo};"
        ]

    if bt == 'Switch':
        thr  = _sf(params.get('Threshold', '0.5'), '0.5')
        ctrl = ins[1] if len(ins) > 1 else in0
        in2  = ins[2] if len(ins) > 2 else '0.0'
        crit = params.get('Criteria', 'u2 >= Threshold')
        op   = '>=' if '>=' in crit else ('>' if '>' in crit else '!=')
        return [f"{out} = ({ctrl} {op} {thr}) ? {in0} : {in2};"]

    if bt == 'MultiPortSwitch':
        n = max(len(ins) - 1, 2)
        ctrl = ins[0] if ins else '0'
        code = [f"/* MultiPortSwitch: {n} inputs */"]
        code.append(f"switch ((int){ctrl}) {{")
        for i in range(n):
            sig = ins[i+1] if i+1 < len(ins) else '0.0'
            code.append(f"    case {i}: {out} = {sig}; break;")
        code.append(f"    default: {out} = {ins[1] if len(ins)>1 else '0.0'}; break;")
        code.append("}")
        return code

    if bt == 'PIDController':
        kp = _sf(params.get('P',  params.get('Kp', '1.0')),  '1.0')
        ki = _sf(params.get('I',  params.get('Ki', '0.1')),  '0.1')
        kd = _sf(params.get('D',  params.get('Kd', '0.01')), '0.01')
        return [
            f"pid_int_{bn}  += {in0} * dt;",
            f"Signal pid_d_{bn} = ({in0} - pid_prev_{bn}) / dt;",
            f"{out} = {kp}*{in0} + {ki}*pid_int_{bn} + {kd}*pid_d_{bn};",
            f"pid_prev_{bn}  = {in0};"
        ]

    if bt == 'RelationalOperator':
        op_map = {
            '==': '==', '!=': '!=', '<': '<', '>': '>',
            '<=': '<=', '>=': '>=',
            'isnan': 'isnan', 'isinf': 'isinf'
        }
        op_str = params.get('Operator', params.get('RelOp', '=='))
        cop    = op_map.get(op_str, '==')
        in1    = ins[1] if len(ins) > 1 else '0.0'
        if cop in ('isnan', 'isinf'):
            return [f"{out} = (Signal){cop}({in0});"]
        return [f"{out} = (Signal)({in0} {cop} {in1});"]

    if bt == 'LogicOperator':
        op_str = params.get('Operator', 'AND').upper()
        lop_map = {
            'AND':  ' && ', 'OR':   ' || ',
            'NAND': ' && ', 'NOR':  ' || ',
            'XOR':  ' != ', 'NOT':  ''
        }
        lop = lop_map.get(op_str, ' && ')
        if op_str == 'NOT':
            return [f"{out} = (Signal)(!{in0});"]
        expr = lop.join(f"(int){s}" for s in ins) if ins else f"(int){in0}"
        if op_str in ('NAND', 'NOR'):
            return [f"{out} = (Signal)!({expr});"]
        return [f"{out} = (Signal)({expr});"]

    # ---- Signal sources ----
    if bt == 'SineWave':
        amp  = _sf(params.get('Amplitude', '1.0'), '1.0')
        freq = _sf(params.get('Frequency', '1.0'), '1.0')
        bias = _sf(params.get('Bias',      '0.0'), '0.0')
        phase= _sf(params.get('Phase',     '0.0'), '0.0')
        return [
            f"{out} = {bias} + {amp} * sin(2.0*3.14159265358979*{freq}*time_{bn} + {phase});",
            f"time_{bn} += dt;"
        ]

    if bt == 'Step':
        st  = _sf(params.get('Time',   '1.0'), '1.0')
        bef = _sf(params.get('Before', '0.0'), '0.0')
        aft = _sf(params.get('After',  '1.0'), '1.0')
        return [
            f"{out} = (time_{bn} >= {st}) ? {aft} : {bef};",
            f"time_{bn} += dt;"
        ]

    if bt == 'DiscretePulseGenerator':
        amp    = _sf(params.get('Amplitude', '1.0'), '1.0')
        period = _sf(params.get('Period',    '1.0'), '1.0')
        duty   = _sf(params.get('PulseWidth', '50'), '50')
        return [
            f"/* DiscretePulseGenerator: period={period}, duty={duty}% */",
            f"{{",
            f"    double _phase = fmod(time_{bn}, {period});",
            f"    {out} = (_phase < ({period} * {duty} / 100.0)) ? {amp} : 0.0;",
            f"    time_{bn} += dt;",
            f"}}"
        ]

    # ---- Complex signal blocks ----
    if bt == 'ComplexToRealImag':
        return [
            f"/* ComplexToRealImag: splits complex signal */",
            f"sig_{bn}_re = creal((double complex){in0});  /* Real part */",
            f"sig_{bn}_im = cimag((double complex){in0});  /* Imaginary part */",
            f"{out} = sig_{bn}_re;"
        ]

    if bt == 'RealImagToComplex':
        in1 = ins[1] if len(ins) > 1 else '0.0'
        return [
            f"/* RealImagToComplex: combines real + imaginary */",
            f"{out} = {in0};  /* Real part stored — complex arithmetic needs <complex.h> */",
            f"/* Full: CREAL={in0}, CIMAG={in1} */"
        ]

    # ---- S-Function ----
    if bt == 'SFunction':
        sfname = _sn(params.get('FunctionName', params.get('Name', bn)))
        n_ins  = max(len(ins), 1)
        code   = [
            f"/* S-Function: {sfname} */",
            f"{{",
            f"    Signal _sfunc_inputs[{n_ins}] = {{{', '.join(ins) if ins else '0.0'}}};",
            f"    Signal _sfunc_state[4] = {{0}};",
            f"    {out} = sfunc_{bn}(_sfunc_inputs, {n_ins}, _sfunc_state, 4);",
            f"}}"
        ]
        return code

    # ---- Reference blocks ----
    if bt == 'Reference':
        ref  = params.get('SourceBlock', params.get('Name', bn))
        src  = params.get('SourceType', 'Unknown')
        return [
            f"/* Reference block: {ref} (type: {src}) */",
            f"/* This references an external library block */",
            f"{out} = {in0};  /* Pass-through — implement {_sn(ref)}() manually */"
        ]

    # ---- Data type blocks ----
    if bt == 'DataTypeConversion':
        dtype = params.get('OutDataTypeStr', params.get('OutputDataType', 'double'))
        return [f"{out} = (Signal)({in0});  /* DataTypeConversion to {dtype} */"]

    # ---- Sink blocks ----
    if bt == 'Scope':
        return [f'printf("SCOPE {bn}: %f\\n", (double){in0});']

    if bt == 'Display':
        return [f'printf("DISPLAY {bn}: %f\\n", (double){in0});']

    if bt == 'ToWorkspace':
        var = params.get('VariableName', bn)
        return [
            f"/* ToWorkspace: saving to variable '{var}' */",
            f"/* In C: log to file or array */",
            f"printf(\"WORKSPACE {var}: %f\\n\", (double){in0});"
        ]

    if bt == 'Terminator':
        return [f"(void){in0};  /* Terminator: signal discarded */"]

    if bt == 'EnablePort':
        return [f"{out} = {in0};  /* EnablePort */"]

    # ---- SubSystem ----
    if bt in ['SubSystem', 'Subsystem']:
        return [
            f"/* SubSystem: {bn} */",
            f"/* This subsystem contains nested blocks */",
            f"/* Expand subsystem or implement {bn}_step() */",
            f"{out} = {in0};  /* Pass-through placeholder */"
        ]

    # ---- Fallback ----
    return [
        f"/* Unimplemented block type: '{bt}' */",
        f"{out} = {in0};  /* Pass-through */"
    ]


# ================================================================
# Helpers
# ================================================================

def _sn(name):
    name = str(name)
    name = re.sub(r'[^a-zA-Z0-9_]', '_', name)
    if name and name[0].isdigit():
        name = 'b_' + name
    return name or 'unnamed'

def _sf(val, fallback):
    try:
        float(str(val).strip())
        return str(val).strip()
    except:
        return fallback

def _topo(blocks, conn_map):
    from collections import defaultdict, deque
    ids    = [str(b['id']) for b in blocks]
    in_deg = defaultdict(int)
    for src, dsts in conn_map.items():
        for d in dsts:
            in_deg[d] += 1
    queue  = deque(bid for bid in ids if in_deg[bid] == 0)
    order  = []
    by_id  = {str(b['id']): b for b in blocks}
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