import re
from collections import defaultdict, deque

# ================================================================
# SimToC — C Code Generator
# Faithful Simulink-equivalent implementations
# ================================================================

def generate_c_code(blocks, connections):
    lines = []

    # ---- Header ----
    lines += [
        "/*",
        " * ================================================",
        " * Auto-generated C Code — SimToC Converter",
        " * Faithful Simulink-equivalent implementation",
        " * ================================================",
        " */",
        "",
        "#include <stdio.h>",
        "#include <math.h>",
        "#include <stdlib.h>",
        "#include <string.h>",
        "#include <complex.h>",
        "#include <stdint.h>",
        "#include <stdbool.h>",
        "",
        "#ifndef M_PI",
        "#define M_PI 3.14159265358979323846",
        "#endif",
        "",
        "typedef double   Signal;",
        "typedef double _Complex CSignal;",
        "typedef int      Bool;",
        "",
    ]

    # ---- Build maps ----
    block_by_id   = {str(b['id']): b for b in blocks}
    block_by_name = {b['name']: b for b in blocks}

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

    inports  = [b for b in blocks if b['type'] in ['Inport',  'In']]
    outports = [b for b in blocks if b['type'] in ['Outport', 'Out']]

    # ---- Categorize blocks ----
    state_types = [
        'Integrator', 'Derivative', 'UnitDelay', 'ZeroOrderHold',
        'TransferFcn', 'DiscreteTransferFcn', 'DiscreteFilter',
        'PIDController', 'SineWave', 'Step', 'DiscretePulseGenerator',
        'Memory', 'RateLimiter', 'DiscreteStateSpace',
    ]
    state_blocks  = [b for b in blocks if b['type'] in state_types]
    sfunc_blocks  = [b for b in blocks if b['type'] == 'SFunction']
    mux_blocks    = [b for b in blocks if b['type'] == 'Mux']
    ref_blocks    = [b for b in blocks if b['type'] == 'Reference']
    goto_blocks   = [b for b in blocks if b['type'] == 'Goto']
    from_blocks   = [b for b in blocks if b['type'] == 'From']

    # ---- Global state variables ----
    lines.append("/* ================================================")
    lines.append("   Global State Variables")
    lines.append("   ================================================ */")

    for b in state_blocks:
        n = _sn(b['name'])
        t = b['type']
        p = b.get('params', {})
        if t == 'Integrator':
            ic = _sf(p.get('InitialCondition', '0.0'), '0.0')
            lines.append(f"static Signal state_{n}     = {ic};  /* Integrator state */")
        elif t == 'Derivative':
            lines.append(f"static Signal prev_in_{n}  = 0.0;  /* Derivative: previous input */")
            lines.append(f"static Signal prev_out_{n} = 0.0;  /* Derivative: previous output */")
        elif t in ['UnitDelay', 'Memory']:
            ic = _sf(p.get('InitialCondition', p.get('X0', '0.0')), '0.0')
            lines.append(f"static Signal delay_{n}     = {ic};  /* {t} state */")
        elif t == 'ZeroOrderHold':
            lines.append(f"static Signal zoh_{n}       = 0.0;  /* ZeroOrderHold held value */")
            lines.append(f"static double zoh_timer_{n} = 0.0;  /* ZeroOrderHold sample timer */")
        elif t in ['TransferFcn', 'DiscreteTransferFcn']:
            num = p.get('Numerator', '[1]')
            den = p.get('Denominator', '[1 1]')
            nc  = len(re.findall(r'[-\d.e+]+', num))
            dc  = len(re.findall(r'[-\d.e+]+', den))
            order = max(dc - 1, 1)
            lines.append(f"static Signal tf_x_{n}[{order}]  = {{0}};  /* TransferFcn states  num={num} den={den} */")
            lines.append(f"static Signal tf_y_{n}[{order}]  = {{0}};  /* TransferFcn outputs */")
        elif t == 'DiscreteFilter':
            num = p.get('Numerator', '[1]')
            den = p.get('Denominator', '[1]')
            nc  = max(len(re.findall(r'[-\d.e+]+', num)), 1)
            dc  = max(len(re.findall(r'[-\d.e+]+', den)), 1)
            order = max(nc, dc)
            lines.append(f"static Signal df_x_{n}[{order}] = {{0}};  /* DiscreteFilter input buffer  num={num} */")
            lines.append(f"static Signal df_y_{n}[{order}] = {{0}};  /* DiscreteFilter output buffer den={den} */")
        elif t == 'PIDController':
            lines.append(f"static Signal pid_integral_{n}  = 0.0;  /* PID integral accumulator */")
            lines.append(f"static Signal pid_prev_err_{n}  = 0.0;  /* PID previous error (for derivative) */")
            lines.append(f"static Signal pid_filter_{n}    = 0.0;  /* PID derivative filter state */")
        elif t in ['SineWave', 'Step', 'DiscretePulseGenerator']:
            lines.append(f"static double sim_time_{n}      = 0.0;  /* {t} simulation time */")
        elif t == 'RateLimiter':
            lines.append(f"static Signal rl_prev_{n}       = 0.0;  /* RateLimiter previous output */")
        elif t == 'DiscreteStateSpace':
            nx = int(_sf(p.get('NumStates', '2'), '2'))
            lines.append(f"static Signal dss_x_{n}[{nx}]  = {{0}};  /* DiscreteStateSpace state vector */")

    lines.append("")

    # ---- Mux buffers ----
    if mux_blocks:
        lines.append("/* --- Mux Signal Buffers --- */")
        for b in mux_blocks:
            n  = _sn(b['name'])
            ni = max(int(_sf(b['params'].get('Inputs', str(max(len(in_map.get(str(b['id']), [])), 2))), '2')), 2)
            lines.append(f"static Signal mux_{n}[{ni}];  /* Mux buffer ({ni} inputs) */")
        lines.append("")

    # ---- Goto/From bus ----
    if goto_blocks or from_blocks:
        lines.append("/* --- Goto/From Virtual Bus --- */")
        tags = {}
        for b in goto_blocks + from_blocks:
            tag = b['params'].get('GotoTag', b['params'].get('Tag', b['name']))
            tags[_sn(tag)] = tag
        for sn_tag, raw_tag in sorted(tags.items()):
            lines.append(f"static Signal bus_{sn_tag} = 0.0;  /* Goto/From tag: {raw_tag} */")
        lines.append("")

    # ---- Constants ----
    const_blocks = [b for b in blocks if b['type'] == 'Constant']
    if const_blocks:
        lines.append("/* --- Constants --- */")
        for b in const_blocks:
            n = _sn(b['name'])
            v = b['params'].get('Value', '1.0')
            nums = re.findall(r'[-\d.eE+]+', v)
            if nums and len(nums) == 1:
                lines.append(f"#define K_{n.upper()} ({nums[0]})  /* Constant: {b['name']} */")
            elif nums:
                arr = ', '.join(nums)
                lines.append(f"static const Signal K_{n.upper()}[{len(nums)}] = {{{arr}}};  /* Constant vector */")
            else:
                lines.append(f"#define K_{n.upper()} (1.0)  /* Constant: {b['name']} = {v} (parse manually) */")
        lines.append("")

    # ---- Gain parameters ----
    gain_blocks = [b for b in blocks if b['type'] == 'Gain']
    if gain_blocks:
        lines.append("/* --- Gain Parameters --- */")
        for b in gain_blocks:
            n = _sn(b['name'])
            v = b['params'].get('Gain', '1.0')
            nums = re.findall(r'[-\d.eE+]+', v)
            if nums and len(nums) == 1:
                lines.append(f"static const Signal G_{n.upper()} = {nums[0]};  /* Gain: {b['name']} */")
            elif nums:
                arr = ', '.join(nums)
                lines.append(f"static const Signal G_{n.upper()}[{len(nums)}] = {{{arr}}};  /* Matrix gain */")
            else:
                lines.append(f"static const Signal G_{n.upper()} = 1.0;  /* Gain: {b['name']} = {v} */")
        lines.append("")

    # ---- S-Function forward declarations ----
    if sfunc_blocks:
        lines.append("/* --- S-Function Forward Declarations --- */")
        for b in sfunc_blocks:
            n      = _sn(b['name'])
            sfname = b['params'].get('FunctionName', b['params'].get('SFunctionName', n))
            nparams = b['params'].get('Parameters', '')
            lines.append(f"/* S-Function '{b['name']}' → C function: sfunc_{n}() */")
            lines.append(f"/* Original Simulink S-function name: {sfname} */")
            if nparams:
                lines.append(f"/* Parameters: {nparams} */")
            lines.append(f"Signal sfunc_{n}(Signal *u, int nu, Signal *x, int nx, double t);")
        lines.append("")

    # ---- Reference block declarations ----
    if ref_blocks:
        lines.append("/* --- Reference Block Declarations --- */")
        lines.append("/* These are library blocks — implement each as a C function */")
        seen_refs = set()
        for b in ref_blocks:
            n       = _sn(b['name'])
            srcblk  = b['params'].get('SourceBlock', '')
            srctype = b['params'].get('SourceType',  b['name'])
            fn      = _sn(srctype)
            if fn not in seen_refs:
                seen_refs.add(fn)
                lines.append(f"/* Library: {srcblk} */")
                lines.append(f"Signal ref_{fn}(Signal *u, int nu, double t);")
        lines.append("")

    # ---- model_step function ----
    lines += [
        "/* ================================================",
        "   model_step()",
        "   Call this function at every sample time step.",
        "   Mirrors Simulink's mdlOutputs + mdlUpdate.",
        "   ================================================ */",
        "void model_step(",
    ]

    sig_params = []
    for ip in inports:
        sig_params.append(f"    Signal {_sn(ip['name'])}_in")
    for op in outports:
        sig_params.append(f"    Signal* {_sn(op['name'])}_out")
    sig_params.append("    double t")
    sig_params.append("    double dt")

    lines.append(',\n'.join(sig_params) if sig_params else "    void")
    lines += [") {", ""]

    # ---- Wire declarations ----
    lines.append("    /* --- Internal signal wires --- */")
    for b in blocks:
        n = _sn(b['name'])
        t = b['type']
        if t == 'Mux':
            ni = max(int(_sf(b['params'].get('Inputs', '2'), '2')), 2)
            lines.append(f"    Signal sig_{n}[{ni}];")
        elif t == 'ComplexToRealImag':
            lines.append(f"    Signal sig_{n}_re = 0.0, sig_{n}_im = 0.0;")
        elif t == 'RealImagToComplex':
            lines.append(f"    CSignal sig_{n}_cx = 0.0;")
            lines.append(f"    Signal  sig_{n}    = 0.0;")
        else:
            lines.append(f"    Signal sig_{n} = 0.0;")
    lines.append("")

    # ---- Signal flow ----
    ordered = _topo(blocks, conn_map)
    lines.append("    /* --- Signal flow (topologically ordered) --- */")

    for b in ordered:
        bid    = str(b['id'])
        bt     = b['type']
        bn     = _sn(b['name'])
        bp     = b.get('params', {})
        src_ids = in_map.get(bid, [])

        insigs = []
        for sid in src_ids:
            sb = block_by_id.get(sid)
            if sb:
                insigs.append(f"sig_{_sn(sb['name'])}")

        in0 = insigs[0] if insigs else "0.0"
        out = f"sig_{bn}"

        lines.append(f"")
        lines.append(f"    /* [{bt}]  {b['name']} */")
        for cl in _block_to_c(bt, bn, out, in0, insigs, bp):
            lines.append(f"    {cl}")

    lines.append("")

    # ---- Output assignment ----
    lines.append("    /* --- Assign outputs --- */")
    for op in outports:
        on   = _sn(op['name'])
        srcs = in_map.get(str(op['id']), [])
        if srcs:
            sb = block_by_id.get(srcs[0])
            src_sig = f"sig_{_sn(sb['name'])}" if sb else f"sig_{on}"
        else:
            src_sig = "0.0"
        lines.append(f"    *{on}_out = {src_sig};")

    lines += ["}", ""]

    # ---- model_init ----
    lines += [
        "/* ================================================",
        "   model_init()",
        "   Call once before starting simulation.",
        "   Mirrors Simulink's mdlInitializeSizes + mdlStart.",
        "   ================================================ */",
        "void model_init(void) {",
    ]
    for b in state_blocks:
        n = _sn(b['name'])
        t = b['type']
        p = b.get('params', {})
        if t == 'Integrator':
            ic = _sf(p.get('InitialCondition', '0.0'), '0.0')
            lines.append(f"    state_{n}    = {ic};")
        elif t == 'Derivative':
            lines.append(f"    prev_in_{n}  = 0.0;")
            lines.append(f"    prev_out_{n} = 0.0;")
        elif t in ['UnitDelay', 'Memory']:
            ic = _sf(p.get('InitialCondition', p.get('X0', '0.0')), '0.0')
            lines.append(f"    delay_{n}    = {ic};")
        elif t == 'ZeroOrderHold':
            lines.append(f"    zoh_{n}      = 0.0;")
            lines.append(f"    zoh_timer_{n}= 0.0;")
        elif t in ['TransferFcn', 'DiscreteTransferFcn']:
            order = 4
            lines.append(f"    memset(tf_x_{n}, 0, sizeof(tf_x_{n}));")
            lines.append(f"    memset(tf_y_{n}, 0, sizeof(tf_y_{n}));")
        elif t == 'DiscreteFilter':
            lines.append(f"    memset(df_x_{n}, 0, sizeof(df_x_{n}));")
            lines.append(f"    memset(df_y_{n}, 0, sizeof(df_y_{n}));")
        elif t == 'PIDController':
            lines.append(f"    pid_integral_{n} = 0.0;")
            lines.append(f"    pid_prev_err_{n} = 0.0;")
            lines.append(f"    pid_filter_{n}   = 0.0;")
        elif t in ['SineWave', 'Step', 'DiscretePulseGenerator']:
            lines.append(f"    sim_time_{n} = 0.0;")
        elif t == 'RateLimiter':
            lines.append(f"    rl_prev_{n}  = 0.0;")
        elif t == 'DiscreteStateSpace':
            nx = int(_sf(p.get('NumStates', '2'), '2'))
            lines.append(f"    memset(dss_x_{n}, 0, {nx}*sizeof(Signal));")
    lines += ["}", ""]

    # ---- S-Function stubs ----
    if sfunc_blocks:
        lines += [
            "/* ================================================",
            "   S-Function Implementations",
            "   Replace stub bodies with your actual logic.",
            "   Signature matches Simulink Level-2 C S-function",
            "   mdlOutputs signature pattern.",
            "   ================================================ */",
        ]
        for b in sfunc_blocks:
            n      = _sn(b['name'])
            sfname = b['params'].get('FunctionName', b['params'].get('SFunctionName', n))
            nparams = b['params'].get('Parameters', '')
            lines += [
                f"Signal sfunc_{n}(Signal *u, int nu, Signal *x, int nx, double t) {{",
                f"    /*",
                f"     * S-Function: {b['name']}",
                f"     * Simulink function: {sfname}",
            ]
            if nparams:
                lines.append(f"     * Parameters: {nparams}")
            lines += [
                f"     * u[0..nu-1] = input ports",
                f"     * x[0..nx-1] = discrete states",
                f"     * t          = current simulation time",
                f"     * Returns    = primary output (port 0)",
                f"     */",
                f"    (void)x; (void)nx; (void)t;",
                f"    /* TODO: implement {sfname} logic here */",
                f"    return (nu > 0) ? u[0] : 0.0;",
                f"}}",
                "",
            ]

    # ---- Reference block stubs ----
    if ref_blocks:
        lines += [
            "/* ================================================",
            "   Reference Block Implementations",
            "   Each corresponds to a Simulink library block.",
            "   ================================================ */",
        ]
        seen_refs = set()
        for b in ref_blocks:
            srctype = b['params'].get('SourceType', b['name'])
            fn      = _sn(srctype)
            srcblk  = b['params'].get('SourceBlock', '')
            if fn in seen_refs:
                continue
            seen_refs.add(fn)
            lines += [
                f"Signal ref_{fn}(Signal *u, int nu, double t) {{",
                f"    /*",
                f"     * Library block: {srctype}",
                f"     * Source: {srcblk}",
                f"     * Implement the mathematical behaviour of this block here.",
                f"     */",
                f"    (void)t;",
                f"    return (nu > 0) ? u[0] : 0.0;",
                f"}}",
                "",
            ]

    # ---- main ----
    lines += [
        "/* ================================================",
        "   main() — Example simulation loop",
        "   Compile: gcc model_output.c -lm -o model && ./model",
        "   ================================================ */",
        "int main(void) {",
        "    model_init();",
        "    const double DT  = 0.001;   /* sample period (s) */",
        "    const double T   = 10.0;    /* simulation end time (s) */",
        "    double t = 0.0;",
        "",
    ]
    for op in outports:
        lines.append(f"    Signal {_sn(op['name'])}_result = 0.0;")
    lines.append("")
    lines.append("    while (t < T) {")
    for ip in inports:
        lines.append(f"        Signal {_sn(ip['name'])}_val = 1.0;  /* TODO: supply real input */")
    call_args  = [f"{_sn(ip['name'])}_val"   for ip in inports]
    call_args += [f"&{_sn(op['name'])}_result" for op in outports]
    call_args += ["t", "DT"]
    lines.append(f"        model_step({', '.join(call_args)});")
    for op in outports:
        n = _sn(op['name'])
        lines.append(f'        printf("t=%8.4f  {n} = %12.6f\\n", t, {n}_result);')
    lines += [
        "        t += DT;",
        "    }",
        "    return 0;",
        "}",
    ]

    return '\n'.join(lines)


# ================================================================
# Block → C  (faithful Simulink equivalents)
# ================================================================

def _block_to_c(bt, bn, out, in0, ins, p):

    # ---- Inport / Outport ----
    if bt in ('Inport', 'In'):
        return [f"{out} = {bn}_in;"]
    if bt in ('Outport', 'Out'):
        return ["/* output assigned below */"]
    if bt == 'Ground':
        return [f"{out} = 0.0;"]

    # ---- Constant ----
    if bt == 'Constant':
        v = p.get('Value', '1.0')
        nums = re.findall(r'[-\d.eE+]+', v)
        if nums and len(nums) == 1:
            return [f"{out} = {nums[0]};"]
        return [f"{out} = K_{bn.upper()}[0];  /* vector constant — use K_{bn.upper()}[] directly */"]

    # ---- Gain  (y = K*u) ----
    if bt == 'Gain':
        mul = p.get('Multiplication', 'Element-wise(K.*u)')
        if 'Matrix' in mul:
            return [f"{out} = G_{bn.upper()} * {in0};  /* matrix gain — expand manually for vectors */"]
        return [f"{out} = G_{bn.upper()} * {in0};"]

    # ---- Sum  (y = +/-u1 +/- u2 ...) ----
    if bt == 'Sum':
        signs = ''.join(c for c in str(p.get('Inputs', p.get('Signs', '++'))) if c in '+-')
        if not signs:
            signs = '+' * max(len(ins), 1)
        terms = []
        for i, sig in enumerate(ins):
            s = signs[i] if i < len(signs) else '+'
            terms.append(f"- {sig}" if s == '-' else sig)
        expr = ' + '.join(terms) if terms else in0
        return [f"{out} = {expr};"]

    # ---- Product  (y = u1*u2 or u1/u2) ----
    if bt == 'Product':
        op_str = p.get('Inputs', p.get('Multiplication', '**'))
        if '/' in op_str:
            if len(ins) >= 2:
                return [f"{out} = ({ins[1]} != 0.0) ? {ins[0]} / {ins[1]} : 0.0;  /* divide-by-zero guard */"]
            return [f"{out} = ({in0} != 0.0) ? 1.0 / {in0} : 0.0;"]
        expr = ' * '.join(ins) if len(ins) >= 2 else f"{in0} * {in0}"
        return [f"{out} = {expr};"]

    # ---- Abs ----
    if bt == 'Abs':
        return [f"{out} = fabs({in0});"]

    # ---- Sqrt ----
    if bt == 'Sqrt':
        func = p.get('Function', 'sqrt')
        fn_map = {'sqrt': f"sqrt(fabs({in0}))",
                  'rSqrt': f"(({in0} != 0.0) ? 1.0/sqrt(fabs({in0})) : 0.0)",
                  'signedSqrt': f"(({in0} >= 0.0) ? sqrt({in0}) : -sqrt(-{in0}))"}
        return [f"{out} = {fn_map.get(func, f'sqrt(fabs({in0}))')};"]

    # ---- Math Function ----
    if bt == 'MathFunction':
        op = p.get('Operator', p.get('Function', 'exp')).lower()
        fn_map = {
            'exp':    f"exp({in0})",
            'log':    f"log(fabs({in0}) + 1e-300)",
            'log10':  f"log10(fabs({in0}) + 1e-300)",
            'log2':   f"(log(fabs({in0}) + 1e-300) / log(2.0))",
            'square': f"(({in0}) * ({in0}))",
            'sqrt':   f"sqrt(fabs({in0}))",
            'pow':    f"pow({in0}, {ins[1] if len(ins) > 1 else '2.0'})",
            '10^u':   f"pow(10.0, {in0})",
            '2^u':    f"pow(2.0, {in0})",
            'floor':  f"floor({in0})",
            'ceil':   f"ceil({in0})",
            'round':  f"round({in0})",
            'fix':    f"trunc({in0})",
            'mod':    f"fmod({in0}, {ins[1] if len(ins) > 1 else '1.0'})",
            'rem':    f"remainder({in0}, {ins[1] if len(ins) > 1 else '1.0'})",
            'sign':   f"(({in0} > 0.0) - ({in0} < 0.0))",
            'conj':   f"creal({in0})",
            'hermitian': f"creal({in0})",
            'transpose': f"{in0}",
        }
        expr = fn_map.get(op, f"{op}({in0})")
        return [f"{out} = {expr};  /* MathFunction: {op} */"]

    # ---- Trigonometry ----
    if bt == 'Trigonometry':
        op = p.get('Operator', 'sin').lower()
        fn_map = {
            'sin':   f"sin({in0})",
            'cos':   f"cos({in0})",
            'tan':   f"tan({in0})",
            'asin':  f"asin(fmax(-1.0, fmin(1.0, {in0})))",
            'acos':  f"acos(fmax(-1.0, fmin(1.0, {in0})))",
            'atan':  f"atan({in0})",
            'atan2': f"atan2({ins[0]}, {ins[1] if len(ins) > 1 else '1.0'})",
            'sinh':  f"sinh({in0})",
            'cosh':  f"cosh({in0})",
            'tanh':  f"tanh({in0})",
            'asinh': f"asinh({in0})",
            'acosh': f"acosh(fmax(1.0, {in0}))",
            'atanh': f"atanh(fmax(-1.0, fmin(1.0, {in0})))",
            'sincos':f"sin({in0})",
        }
        return [f"{out} = {fn_map.get(op, f'sin({in0})')};  /* Trigonometry: {op} */"]

    # ---- Relational Operator ----
    if bt == 'RelationalOperator':
        op_raw = p.get('Operator', p.get('RelOp', '=='))
        op_map = {'==':'==','!=':'!=','<':'<','>':'>','<=':'<=','>=':'>=',
                  'isnan':'isnan','isinf':'isinf','isfinite':'isfinite'}
        cop = op_map.get(op_raw, '==')
        in1 = ins[1] if len(ins) > 1 else '0.0'
        if cop in ('isnan', 'isinf', 'isfinite'):
            return [f"{out} = (Signal){cop}({in0});"]
        return [f"{out} = (Signal)({in0} {cop} {in1});  /* RelationalOperator: {op_raw} */"]

    # ---- Logic Operator ----
    if bt == 'LogicOperator':
        op = p.get('Operator', 'AND').upper()
        lop_map = {'AND':' && ','OR':' || ','XOR':' ^ ','NAND':' && ','NOR':' || '}
        lop = lop_map.get(op, ' && ')
        if op == 'NOT':
            return [f"{out} = (Signal)(!(int){in0});"]
        expr = lop.join(f"(int){s}" for s in ins) if ins else f"(int){in0}"
        if op in ('NAND', 'NOR'):
            return [f"{out} = (Signal)!({expr});"]
        return [f"{out} = (Signal)({expr});  /* LogicOperator: {op} */"]

    # ---- Integrator (Forward Euler: x[k+1] = x[k] + dt*u[k]) ----
    if bt == 'Integrator':
        method = p.get('IntegratorMethod', 'ForwardEuler')
        ic     = _sf(p.get('InitialCondition', '0.0'), '0.0')
        upper  = p.get('UpperSaturationLimit', '')
        lower  = p.get('LowerSaturationLimit', '')
        code = [f"state_{bn} += {in0} * dt;  /* Integrator ({method}): x(k+1)=x(k)+dt*u(k) */"]
        if upper:
            code.append(f"if (state_{bn} > {upper}) state_{bn} = {upper};  /* upper saturation */")
        if lower:
            code.append(f"if (state_{bn} < {lower}) state_{bn} = {lower};  /* lower saturation */")
        code.append(f"{out} = state_{bn};")
        return code

    # ---- Derivative (Tustin: y = (2/dt)*(u-u_prev)/(1+y_prev ... ) approx) ----
    if bt == 'Derivative':
        return [
            f"{out} = (dt > 0.0) ? ({in0} - prev_in_{bn}) / dt : 0.0;  /* Derivative: dy/dt */",
            f"prev_in_{bn}  = {in0};",
            f"prev_out_{bn} = {out};",
        ]

    # ---- Unit Delay (y[k] = u[k-1]) ----
    if bt == 'UnitDelay':
        return [
            f"{out} = delay_{bn};        /* UnitDelay: y[k] = u[k-1] */",
            f"delay_{bn} = {in0};        /* update state */",
        ]

    # ---- Memory (same as UnitDelay at base rate) ----
    if bt == 'Memory':
        return [
            f"{out} = delay_{bn};        /* Memory: y[k] = u[k-1] */",
            f"delay_{bn} = {in0};",
        ]

    # ---- Zero-Order Hold ----
    if bt == 'ZeroOrderHold':
        ts = _sf(p.get('SampleTime', '0.01'), '0.01')
        return [
            f"zoh_timer_{bn} += dt;",
            f"if (zoh_timer_{bn} >= {ts}) {{  /* ZeroOrderHold: sample every {ts}s */",
            f"    zoh_{bn}       = {in0};",
            f"    zoh_timer_{bn} = 0.0;",
            f"}}",
            f"{out} = zoh_{bn};",
        ]

    # ---- Transfer Function (continuous, state-space form) ----
    if bt in ('TransferFcn', 'DiscreteTransferFcn'):
        num_str = p.get('Numerator', '[1]')
        den_str = p.get('Denominator', '[1 1]')
        num = re.findall(r'[-\d.eE+]+', num_str)
        den = re.findall(r'[-\d.eE+]+', den_str)
        order = max(len(den) - 1, 1)
        label = 'TransferFcn' if bt == 'TransferFcn' else 'DiscreteTransferFcn'
        code = [
            f"/* {label}: H(s) = {num_str} / {den_str} */",
            f"/* Implemented as observable canonical state-space form */",
            f"{{",
            f"    Signal _u = {in0};",
        ]
        a0 = den[0] if den else '1.0'
        if bt == 'TransferFcn':
            # Continuous: Euler integration of state equations
            if order == 1 and len(den) >= 2:
                a1 = den[1]
                b0 = num[0] if num else '1.0'
                code += [
                    f"    /* First-order: a0*dy/dt + a1*y = b0*u */",
                    f"    tf_x_{bn}[0] += ((_u - ({a1}/{a0}) * tf_x_{bn}[0]) / {a0}) * dt;",
                    f"    {out} = ({b0}/{a0}) * tf_x_{bn}[0];",
                ]
            elif order == 2 and len(den) >= 3:
                a1, a2 = den[1], den[2]
                b0 = num[0] if num else '1.0'
                code += [
                    f"    /* Second-order state equations */",
                    f"    Signal _x0_dot = tf_x_{bn}[1];",
                    f"    Signal _x1_dot = (_u/{a0}) - ({a2}/{a0})*tf_x_{bn}[0] - ({a1}/{a0})*tf_x_{bn}[1];",
                    f"    tf_x_{bn}[0] += _x0_dot * dt;",
                    f"    tf_x_{bn}[1] += _x1_dot * dt;",
                    f"    {out} = ({b0}/{a0}) * tf_x_{bn}[0];",
                ]
            else:
                code += [f"    {out} = tf_x_{bn}[0];  /* TODO: extend for order {order} */"]
        else:
            # Discrete: difference equation
            if num and den:
                b0 = num[0]; a0d = den[0]
                rest_a = ' - '.join(f"({den[i]}/{a0d})*tf_y_{bn}[{i-1}]" for i in range(1, len(den)))
                rest_b = ' + '.join(f"({num[i]}/{a0d})*tf_x_{bn}[{i-1}]" for i in range(1, len(num)))
                out_expr = f"({b0}/{a0d})*_u"
                if rest_a: out_expr += f" - {rest_a}"
                if rest_b: out_expr += f" + {rest_b}"
                code += [
                    f"    /* Discrete difference equation */",
                    f"    Signal _y = {out_expr};",
                    f"    memmove(&tf_x_{bn}[1], &tf_x_{bn}[0], ({order}-1)*sizeof(Signal));",
                    f"    memmove(&tf_y_{bn}[1], &tf_y_{bn}[0], ({order}-1)*sizeof(Signal));",
                    f"    tf_x_{bn}[0] = _u;  tf_y_{bn}[0] = _y;",
                    f"    {out} = _y;",
                ]
            else:
                code.append(f"    {out} = _u;")
        code.append("}")
        return code

    # ---- Discrete Filter (difference equation) ----
    if bt == 'DiscreteFilter':
        num_str = p.get('Numerator', '[1]')
        den_str = p.get('Denominator', '[1]')
        num = re.findall(r'[-\d.eE+]+', num_str)
        den = re.findall(r'[-\d.eE+]+', den_str)
        a0  = den[0] if den else '1.0'
        code = [
            f"/* DiscreteFilter: B={num_str} / A={den_str} */",
            f"/* Direct Form II Transposed */",
            f"{{",
            f"    Signal _u = {in0};",
            f"    Signal _y = ({num[0] if num else '1.0'}/{a0}) * _u + df_x_{bn}[0];",
        ]
        order = max(len(num), len(den)) - 1
        for i in range(order):
            b_i = num[i+1] if i+1 < len(num) else '0.0'
            a_i = den[i+1] if i+1 < len(den) else '0.0'
            nxt = f"df_x_{bn}[{i+1}]" if i+1 < order else "0.0"
            code.append(f"    df_x_{bn}[{i}] = ({b_i}/{a0})*_u - ({a_i}/{a0})*_y + {nxt};")
        code += [f"    {out} = _y;", "}"]
        return code

    # ---- PID Controller ----
    if bt == 'PIDController':
        kp  = _sf(p.get('P',  p.get('Kp', '1.0')),  '1.0')
        ki  = _sf(p.get('I',  p.get('Ki', '0.0')),  '0.0')
        kd  = _sf(p.get('D',  p.get('Kd', '0.0')),  '0.0')
        n   = _sf(p.get('N',  p.get('FilterCoefficient', '100.0')), '100.0')
        form = p.get('TimeDomain', 'Continuous')
        code = [f"/* PID Controller: Kp={kp} Ki={ki} Kd={kd} N={n} */"]
        if 'Discrete' in form or 'discrete' in form:
            code += [
                f"pid_integral_{bn} += {in0} * dt;",
                f"Signal _pid_d = ({in0} - pid_prev_err_{bn}) / dt;",
                f"pid_prev_err_{bn} = {in0};",
                f"{out} = {kp}*{in0} + {ki}*pid_integral_{bn} + {kd}*_pid_d;",
            ]
        else:
            # Continuous PID with derivative filter: D*N/(1+N/s)
            code += [
                f"pid_integral_{bn} += {in0} * dt;",
                f"pid_filter_{bn} += ({n}*({in0} - pid_filter_{bn})) * dt;",
                f"{out} = {kp}*{in0} + {ki}*pid_integral_{bn} + {kd}*{n}*({in0} - pid_filter_{bn});",
                f"pid_prev_err_{bn} = {in0};",
            ]
        return code

    # ---- Rate Limiter ----
    if bt == 'RateLimiter':
        rising  = _sf(p.get('RisingSlewLimit',  '1.0'), '1.0')
        falling = _sf(p.get('FallingSlewLimit', '-1.0'), '-1.0')
        return [
            f"/* RateLimiter: rising={rising} falling={falling} */",
            f"{{",
            f"    Signal _delta = {in0} - rl_prev_{bn};",
            f"    Signal _rate  = _delta / dt;",
            f"    if (_rate >  {rising})  _delta =  {rising}  * dt;",
            f"    if (_rate < {falling}) _delta = {falling} * dt;",
            f"    {out} = rl_prev_{bn} + _delta;",
            f"    rl_prev_{bn} = {out};",
            f"}}",
        ]

    # ---- Saturation ----
    if bt == 'Saturation':
        hi = _sf(p.get('UpperLimit', p.get('UpperSaturationLimit', '1.0')),   '1.0')
        lo = _sf(p.get('LowerLimit', p.get('LowerSaturationLimit', '-1.0')), '-1.0')
        return [
            f"{out} = fmax({lo}, fmin({hi}, {in0}));  /* Saturation [{lo}, {hi}] */",
        ]

    # ---- Switch (y = u1 if u2 op thresh else u3) ----
    if bt == 'Switch':
        thr  = _sf(p.get('Threshold', '0.5'), '0.5')
        crit = p.get('Criteria', 'u2 >= Threshold')
        cop  = '>=' if '>=' in crit else ('>' if '>' in crit else '!=')
        ctrl = ins[1] if len(ins) > 1 else in0
        u3   = ins[2] if len(ins) > 2 else '0.0'
        return [f"{out} = ({ctrl} {cop} {thr}) ? {ins[0] if ins else in0} : {u3};  /* Switch */"]

    # ---- Multiport Switch ----
    if bt == 'MultiPortSwitch':
        ctrl = ins[0] if ins else '0'
        n_cases = max(len(ins) - 1, 2)
        code = [f"/* MultiPortSwitch: {n_cases} data inputs */",
                f"switch ((int)round({ctrl})) {{"]
        for i in range(n_cases):
            sig = ins[i+1] if i+1 < len(ins) else '0.0'
            code.append(f"    case {i}: {out} = {sig}; break;")
        code.append(f"    default: {out} = {ins[1] if len(ins) > 1 else '0.0'}; break;")
        code.append("}")
        return code

    # ---- Quantizer (y = Q*round(u/Q)) ----
    if bt == 'Quantizer':
        q = _sf(p.get('QuantizationInterval', '1.0'), '1.0')
        return [f"{out} = {q} * round({in0} / {q});  /* Quantizer: interval={q} */"]

    # ---- Dead Zone ----
    if bt == 'DeadZone':
        lo = _sf(p.get('LowerValue', '-0.5'), '-0.5')
        hi = _sf(p.get('UpperValue',  '0.5'),  '0.5')
        return [
            f"/* DeadZone [{lo}, {hi}] */",
            f"if ({in0} > {hi})       {out} = {in0} - {hi};",
            f"else if ({in0} < {lo})  {out} = {in0} - {lo};",
            f"else                     {out} = 0.0;",
        ]

    # ---- Sine Wave source ----
    if bt == 'SineWave':
        amp   = _sf(p.get('Amplitude', '1.0'), '1.0')
        bias  = _sf(p.get('Bias',      '0.0'), '0.0')
        freq  = _sf(p.get('Frequency', '1.0'), '1.0')
        phase = _sf(p.get('Phase',     '0.0'), '0.0')
        st    = p.get('SampleTime', '0')
        if st == '0':
            return [f"{out} = {bias} + {amp} * sin(2.0*M_PI*{freq}*t + {phase});  /* SineWave (continuous) */"]
        return [
            f"{out} = {bias} + {amp} * sin(2.0*M_PI*{freq}*sim_time_{bn} + {phase});  /* SineWave (discrete) */",
            f"sim_time_{bn} += dt;",
        ]

    # ---- Step source ----
    if bt == 'Step':
        st  = _sf(p.get('Time',   '1.0'), '1.0')
        bef = _sf(p.get('Before', '0.0'), '0.0')
        aft = _sf(p.get('After',  '1.0'), '1.0')
        return [f"{out} = (t >= {st}) ? {aft} : {bef};  /* Step: t_step={st} */"]

    # ---- Discrete Pulse Generator ----
    if bt == 'DiscretePulseGenerator':
        amp    = _sf(p.get('Amplitude', '1.0'), '1.0')
        period = _sf(p.get('Period',    '1.0'), '1.0')
        duty   = _sf(p.get('PulseWidth', '50'), '50')
        delay  = _sf(p.get('PhaseDelay', '0.0'), '0.0')
        return [
            f"/* DiscretePulseGenerator: A={amp} T={period}s duty={duty}% delay={delay}s */",
            f"{{",
            f"    double _ph = fmod(sim_time_{bn} - {delay}, {period});",
            f"    if (_ph < 0.0) _ph += {period};",
            f"    {out} = (_ph < ({period} * {duty} / 100.0)) ? {amp} : 0.0;",
            f"    sim_time_{bn} += dt;",
            f"}}",
        ]

    # ---- Chirp Signal ----
    if bt == 'Chirp':
        f0 = _sf(p.get('InitialFrequency', '0.1'), '0.1')
        f1 = _sf(p.get('TargetFrequency',  '1.0'), '1.0')
        t1 = _sf(p.get('TargetTime',       '10.0'),'10.0')
        return [f"{out} = cos(2.0*M_PI*t*({f0} + ({f1}-{f0})/(2.0*{t1})*t));  /* Chirp */"]

    # ---- Mux ----
    if bt == 'Mux':
        code = [f"/* Mux: bundle {len(ins)} signals into array mux_{bn}[] */"]
        for i, s in enumerate(ins):
            code.append(f"mux_{bn}[{i}] = {s};")
        code.append(f"{out} = mux_{bn}[0];  /* primary output = first element */")
        return code

    # ---- Demux ----
    if bt == 'Demux':
        no = int(_sf(p.get('Outputs', str(max(len(ins), 2))), '2'))
        code = [f"/* Demux: split into {no} outputs */",
                f"{out} = {in0};  /* out[0] = primary */"]
        for i in range(1, no):
            code.append(f"/* demux_{bn}_out{i+1}: manually route additional outputs */")
        return code

    # ---- Concatenate ----
    if bt == 'Concatenate':
        mode = p.get('Mode', 'Multidimensional array')
        code = [f"/* Concatenate ({mode}): joins {len(ins)} signals */"]
        if ins:
            code.append(f"{out} = {ins[0]};  /* primary; extend for matrix concatenation */")
        else:
            code.append(f"{out} = 0.0;")
        return code

    # ---- Selector ----
    if bt == 'Selector':
        idx = p.get('Indices', p.get('Index', '1'))
        return [
            f"/* Selector: extract index {idx} */",
            f"{out} = {in0};  /* scalar proxy; use array indexing for vectors */",
        ]

    # ---- Reshape / Transpose ----
    if bt in ('Reshape', 'Transpose'):
        return [f"{out} = {in0};  /* {bt}: data unchanged, shape changes */"]

    # ---- Dot Product ----
    if bt == 'DotProduct':
        if len(ins) >= 2:
            return [f"{out} = {ins[0]} * {ins[1]};  /* DotProduct (scalar proxy) */"]
        return [f"{out} = {in0} * {in0};"]

    # ---- Bus Creator / Selector ----
    if bt == 'BusCreator':
        code = [f"/* BusCreator: packs {len(ins)} signals */",
                f"{out} = {in0};"]
        return code
    if bt == 'BusSelector':
        return [f"{out} = {in0};  /* BusSelector: extract named signal */"]

    # ---- Goto / From ----
    if bt == 'Goto':
        tag = _sn(p.get('GotoTag', p.get('Tag', bn)))
        return [f"bus_{tag} = {in0};  /* Goto [{tag}] */"]
    if bt == 'From':
        tag = _sn(p.get('GotoTag', p.get('Tag', bn)))
        return [f"{out} = bus_{tag};  /* From [{tag}] */"]

    # ---- Merge ----
    if bt == 'Merge':
        return [f"{out} = {in0};  /* Merge: first active input */"]

    # ---- Complex To Real/Imag ----
    if bt == 'ComplexToRealImag':
        return [
            f"sig_{bn}_re = creal((double _Complex){in0});",
            f"sig_{bn}_im = cimag((double _Complex){in0});",
            f"{out} = sig_{bn}_re;  /* ComplexToRealImag: primary = real part */",
        ]

    # ---- Real/Imag To Complex ----
    if bt == 'RealImagToComplex':
        im = ins[1] if len(ins) > 1 else '0.0'
        return [
            f"sig_{bn}_cx = {ins[0] if ins else in0} + {im} * _Complex_I;  /* RealImagToComplex */",
            f"{out} = creal(sig_{bn}_cx);  /* store real part as Signal proxy */",
        ]

    # ---- Data Type Conversion ----
    if bt == 'DataTypeConversion':
        dtype = p.get('OutDataTypeStr', p.get('OutputDataType', 'double'))
        cast_map = {
            'int8': '(int8_t)', 'uint8': '(uint8_t)',
            'int16': '(int16_t)', 'uint16': '(uint16_t)',
            'int32': '(int32_t)', 'uint32': '(uint32_t)',
            'single': '(float)', 'double': '(double)',
            'boolean': '(bool)',
        }
        cast = cast_map.get(dtype.lower().split(':')[-1].strip(), '(Signal)')
        return [f"{out} = (Signal){cast}{in0};  /* DataTypeConversion → {dtype} */"]

    # ---- S-Function ----
    if bt == 'SFunction':
        n_ins = max(len(ins), 1)
        arr   = ', '.join(ins) if ins else '0.0'
        sfname = p.get('FunctionName', p.get('SFunctionName', bn))
        return [
            f"/* S-Function: {sfname} */",
            f"{{",
            f"    Signal _u[{n_ins}] = {{{arr}}};",
            f"    {out} = sfunc_{bn}(_u, {n_ins}, NULL, 0, t);",
            f"}}",
        ]

    # ---- Reference block ----
    if bt == 'Reference':
        srctype = p.get('SourceType', bn)
        fn      = _sn(srctype)
        n_ins   = max(len(ins), 1)
        arr     = ', '.join(ins) if ins else '0.0'
        return [
            f"/* Reference: {srctype} (from {p.get('SourceBlock','?')}) */",
            f"{{",
            f"    Signal _u[{n_ins}] = {{{arr}}};",
            f"    {out} = ref_{fn}(_u, {n_ins}, t);",
            f"}}",
        ]

    # ---- Scope / Display / ToWorkspace (sink only, no output) ----
    if bt == 'Scope':
        return [f'printf("SCOPE [{bn}] t=%f  u=%f\\n", t, (double){in0});']
    if bt == 'Display':
        return [f'printf("DISPLAY [{bn}] = %f\\n", (double){in0});']
    if bt == 'ToWorkspace':
        var = p.get('VariableName', bn)
        return [f'printf("WORKSPACE [{var}] t=%f  u=%f\\n", t, (double){in0});',
                f'/* TODO: store {in0} into a buffer array for post-processing */']
    if bt == 'Terminator':
        return [f"(void){in0};  /* Terminator: intentionally discarded */"]
    if bt in ('EnablePort', 'TriggerPort'):
        return [f"{out} = {in0};  /* {bt} */"]

    # ---- SubSystem ----
    if bt in ('SubSystem', 'Subsystem'):
        n_ins = max(len(ins), 1)
        arr   = ', '.join(ins) if ins else '0.0'
        return [
            f"/* SubSystem: {bn} */",
            f"{{",
            f"    Signal _u[{n_ins}] = {{{arr}}};",
            f"    /* Call {bn}_step(_u, {n_ins}, &{out}, t, dt) if you extract this subsystem */",
            f"    {out} = _u[0];  /* pass-through until subsystem is extracted */",
            f"}}",
        ]

    # ---- Fallback ----
    return [
        f"/* TODO: implement block type '{bt}' */",
        f"{out} = {in0};",
    ]


# ================================================================
# Utilities
# ================================================================

def _sn(name):
    s = re.sub(r'[^a-zA-Z0-9_]', '_', str(name))
    return ('b_' + s) if s and s[0].isdigit() else (s or 'unnamed')

def _sf(val, fallback):
    try: float(str(val).strip()); return str(val).strip()
    except: return fallback

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