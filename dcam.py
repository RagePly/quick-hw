from typing import cast, Sequence
from quick_hw import *
from pathlib import Path
from datetime import datetime
from autoindent import autoindent
from math import log2, ceil
import vhdl_renderer

GLOBAL_SIGNAL = Signal()
GLOBAL_SYSTEM = System()

def parse_char(c: str, prefix: str | None = None) -> Component:
    assert len(c) == 1
    assert c.isascii()

    namespace = "" if prefix is None else f"{prefix}:"

    s = GLOBAL_SYSTEM

    name = f"{namespace}match_{hex(ord(c))}"

    clk = s.port(1, name=f"{name}:clk")
    c_bits = Bits.from_ascii(c)
    inp = s.port(8, name=f"{name}:input")
    cmps = [s.comb("XNOR", c_bit, inp_bit, name=f"{name}:comp_{hex(ord(c))}_{i}").dflipflop(clk, True).register_signal(GLOBAL_SIGNAL) for i, (c_bit, inp_bit) in enumerate(zip(c_bits.unwrap(), inp.unwrap()))]
    comp = s.comb("AND", *cmps, name=f"{name}:eval").shr(clk, signal_dffs=GLOBAL_SIGNAL, name=f"{name}:out")

    return Component([comp], [clk, inp])

def solve_match(sid: int, pattern: str, prefix: str | None = None) -> Component:
    namespace = "" if prefix is None else f"{prefix}:"
    s = GLOBAL_SYSTEM
    char_ports = [
        s.port(1, name=f"{namespace}match_p_{sid}_{len(pattern) - 1 - i}:match_{hex(ord(c))}")
        for i, c in enumerate(pattern)
    ]
    clk = s.port(1, name=f"{namespace}match_p_{sid}:clk")

    target = s.comb("AND", *char_ports, name=f"{namespace}match_p_{sid}:out").dflipflop(clk, True)
    target.register_signal(GLOBAL_SIGNAL)

    return Component([target], [clk, *char_ports])

def connect_parser_matcher(parsers: dict[str, Logic], match_logic: Component):
    for inp in match_logic.get_inputs():
        if not isinstance(inp, Port):
            continue
            
        name = inp.get_name()
        prefix, suffix = name.split(":")

        if suffix.startswith("match_"):
            index_of = int(prefix.split("_")[-1]) # TODO: this encoding of index is REALLY shitty
            output_name = f"{suffix}:out"
            assert output_name in parsers, \
                f"missing parser for {output_name}"
            parser_output = parsers[output_name]
            assert isinstance(parser_output, SHR), \
                f"decoder {output_name} has no output-shiftreg"
            inp.set_driver(parser_output.index(index_of))

def generate_decoders_from_patterns(patterns: list[str], prefix: str | None = None) -> dict[str, Component]:
    chars = set(c for pat in patterns for c in pat)
    return {c: parse_char(c, prefix) for c in chars}

def generate_parallel_decoders(degree: int, patterns: list[str]) -> dict[tuple[int, str], Component]:
    return {(i, c): dec for i in range(degree) for c, dec in generate_decoders_from_patterns(patterns, f"offset{i}").items()}

def generate_matchers_from_patterns(patterns: list[str], prefix: str | None = None) -> dict[str, Component]:
    return {pat: solve_match(i, pat, prefix) for i, pat in enumerate(patterns)}

def generate_parallel_matchers(degree: int, patterns: list[str]) -> dict[tuple[int, str], Component]:
    return {(i, pat): comp for i in range(degree) for pat, comp in generate_matchers_from_patterns(patterns, f"offset{i}").items()}

def connect_decoder_matcher_parallel(degree: int, decoders: dict[str, Logic], match_logic: Component):
    for inp in match_logic.get_inputs():
        if not isinstance(inp, Port):
            continue
            
        name = inp.get_name()
        offset, match_name, decoder_source = name.split(":")

        match_offset = int(offset.removeprefix("offset"))

        if decoder_source.startswith("match_"):
            pattern_offset = int(match_name.split("_")[-1]) # TODO: this encoding of index is REALLY shitty, and it's getting worse!

            global_offset = match_offset + pattern_offset 
            shr_index = global_offset // degree

            intra_packet_index = degree - 1 - (global_offset % degree) # reversed, since every packet is in order

            output_name = f"offset{intra_packet_index}:{decoder_source}:out"
            assert output_name in decoders, \
                f"missing parser for {output_name}"
            parser_output = decoders[output_name]
            assert isinstance(parser_output, SHR), \
                f"decoder {output_name} has no output-shiftreg"
            inp.set_driver(parser_output.index(shr_index))

def connect_decoder_matchers_parallel(degree: int, decoders: dict[tuple[int, str], Component], matchers: dict[tuple[int, str], Component]):
    decoder_output = dict(comp.find_logic("out") for comp in decoders.values())
    for matcher in matchers.values():
        connect_decoder_matcher_parallel(degree, decoder_output, matcher)

def generate_parsers(patterns: list[str]) -> tuple[dict[str, Component], dict[str, Component]]:
    decoders = generate_decoders_from_patterns(patterns)
    matchers = generate_matchers_from_patterns(patterns)
    return matchers, decoders

def generate_parsers_parallel(degree: int, patterns: list[str]) -> tuple[dict[tuple[int, str], Component], dict[tuple[int, str], Component]]:
    decoders = generate_parallel_decoders(degree, patterns)
    matchers = generate_parallel_matchers(degree, patterns)
    return matchers, decoders

def connect_decoder_matchers(matchers: dict[str, Component], decoders: dict[str, Component]):
    decoder_output = dict(comp.find_logic("out") for comp in decoders.values())
    for matcher in matchers.values():
        connect_parser_matcher(decoder_output, matcher)

def generate_priority(patterns: list[str], tot_inp: int) -> dict[str, int]:
    return {p: tot_inp - 1 - i for i, p in enumerate(patterns)}

def required_pe_ports(pattern_len: int) -> int:
    return 4**ceil(log2(pattern_len) / 2)

def generate_pe(patterns: list[str], prefix: str | None = None) -> Component:
    namespace = "" if prefix is None else f"{prefix}:"
    required = required_pe_ports(len(patterns))
    print(f"Generating Priority encoder with {required}-inputs")
    pe =  pe_n(required, f"{namespace}PE")
    idx, vid = pe.get_outputs()
    idx.register_signal(GLOBAL_SIGNAL)
    vid.register_signal(GLOBAL_SIGNAL)

    return pe


def connect_matchers_pe(patterns: list[str], matchers: dict[str,Component], pe: Component):
    priority = generate_priority(patterns, len(pe.get_inputs()))
    missing = len(pe.get_inputs()) - len(matchers)

    assert len(pe.get_inputs()) == required_pe_ports(len(patterns))
    assert len(priority) + missing == len(pe.get_inputs())

    pe_inputs = pe.get_inputs()

    set_i = set()
    for i in range(missing):
        set_i.add(i)

        pe_inputs_i = pe_inputs[i]
        assert isinstance(pe_inputs_i, Port)
        pe_inputs_i.set_driver(Bits(1, [False]))
    
    for p, i in priority.items():
        assert i not in set_i, f"Set up {i} multiple times: {priority}"
        pe_inputs_i = pe_inputs[i]
        assert isinstance(pe_inputs_i, Port)
        _, logic = matchers[p].find_logic("out")
        pe_inputs_i.set_driver(logic)
    
    assert all(cast(Port, i).has_driver() for i in pe.get_inputs())

class DecoderParserParallel:
    def __init__(self, degree: int, patterns: list[str]):
        self._degree = degree
        self._matchers , self._decoders = generate_parsers_parallel(degree, patterns)
        self._pes = [generate_pe(patterns, f"offset{i}") for i in range(degree)]
        self._patterns = patterns
        connect_decoder_matchers_parallel(degree, self._decoders, self._matchers)

        for i, pe in enumerate(self._pes):
            valid_matchers = {pat: comp for (offset, pat), comp in self._matchers.items() if offset == i}
            connect_matchers_pe(patterns, valid_matchers, pe)

    def set_input(self, input_bits: Sequence[Logic]):
        for (dec_offset, _), dec in self._decoders.items():
            inp = input_bits[dec_offset]
            _, input_port = dec.find_logic("input")
            assert isinstance(input_port, Port)
            input_port.set_driver(inp)

    def eval_output(self) -> list[tuple[bool, int]]:
        matches = []
        for pe in self._pes:
            idx, vid = pe.get_outputs()

            is_valid = vid.eval()
            idx_bits = idx.eval()

            matches.append((is_valid.as_bitarray()[0], idx_bits.to_int()))
        return matches
    
    def simulate_step(self):
        self.eval_output()     

    def simulate(self, steps: int, input_str: bytes) -> list[list[tuple[int, int, str]]]:
        s = GLOBAL_SYSTEM
        clk = s.port(1, name="clk")
        input_ports = [s.port(8, name=f"input{i}") for i in range(self._degree)]

        clk.register_signal(GLOBAL_SIGNAL)
        for input_port in input_ports:
            input_port.register_signal(GLOBAL_SIGNAL)

        s.set_global_clk(clk)
        self.set_input(input_ports)
        valid_patterns: list[list[tuple[int, int, str]]] = []

        for i in range(steps):
            print(f"Simulating {i+1:3}/{steps:3}")


            for j in range(self._degree):
                input_index = i * self._degree + j

                if input_index < len(input_str):
                    input_ports[j].set_driver(Bits.from_int(input_str[input_index]))
                else:
                    input_ports[j].set_driver(Bits(8, [False for _ in range(8)]))

            # falling edge simulation
            clk.set_driver(Bits(1, [False]))
            GLOBAL_SYSTEM.prepare()
            self.eval_output()
            GLOBAL_SYSTEM.commit()

            # Clk low simulation
            GLOBAL_SYSTEM.prepare()
            self.eval_output()
            GLOBAL_SYSTEM.commit()

            GLOBAL_SIGNAL.step_time_ps(1)

            # rising edge simulation 
            clk.set_driver(Bits(1, [True]))
            GLOBAL_SYSTEM.prepare()
            self.eval_output()
            GLOBAL_SYSTEM.commit()

            # clk high simulation
            GLOBAL_SYSTEM.prepare()
            valids = [(v, idx) for v, idx in self.eval_output() if v]
            GLOBAL_SYSTEM.commit()

            GLOBAL_SIGNAL.step_time_ps(1)

            if valids:
                round_patterns = []
                for _, idx in valids:
                    pattern_idx = required_pe_ports(len(self._patterns)) - 1 - idx
                    line_nr = pattern_idx + 1
                    round_patterns.append((idx, line_nr, self._patterns[pattern_idx]))
                valid_patterns.append(round_patterns)

        return valid_patterns

class DecoderParser:
    def __init__(self, patterns: list[str]):
        self._matchers, self._decoders = generate_parsers(patterns)
        self._pe = generate_pe(patterns)
        connect_decoder_matchers(self._matchers, self._decoders)
        connect_matchers_pe(patterns, self._matchers, self._pe)
    
    def set_input(self, input_bits: Logic):
        for dec in self._decoders.values():
            _, inp = dec.find_logic("input")
            assert isinstance(inp, Port), \
                "expected input to be a Port"
            inp.set_driver(input_bits)
    
    def eval_output(self) -> tuple[bool, int]:
        idx, vid = self._pe.get_outputs()

        is_valid = vid.eval()
        idx_bits = idx.eval()

        return is_valid.as_bitarray()[0], idx_bits.to_int()
        
    def simulate_step(self):
        self.eval_output()     
    
    def simulate(self, steps: int, input_str: bytes) -> list[int]:
        s = GLOBAL_SYSTEM
        clk = s.port(1, name="clk")
        input_port = s.port(8, name="input")

        clk.register_signal(GLOBAL_SIGNAL)
        input_port.register_signal(GLOBAL_SIGNAL)

        s.set_global_clk(clk)
        self.set_input(input_port)

        patterns = []

        for i in range(steps):
            print(f"Simulating {i+1:3}/{steps:3}")
            if i < len(input_str):
                input_port.set_driver(Bits.from_int(input_str[i]))
            else:
                input_port.set_driver(Bits(8, [False for _ in range(8)]))

            # falling edge simulation
            clk.set_driver(Bits(1, [False]))
            GLOBAL_SYSTEM.prepare()
            self.eval_output()
            GLOBAL_SYSTEM.commit()

            # Clk low simulation
            GLOBAL_SYSTEM.prepare()
            self.eval_output()
            GLOBAL_SYSTEM.commit()

            GLOBAL_SIGNAL.step_time_ps(1)

            # rising edge simulation 
            clk.set_driver(Bits(1, [True]))
            GLOBAL_SYSTEM.prepare()
            self.eval_output()
            GLOBAL_SYSTEM.commit()

            # clk high simulation
            GLOBAL_SYSTEM.prepare()
            valid, pattern_id = self.eval_output()
            GLOBAL_SYSTEM.commit()

            GLOBAL_SIGNAL.step_time_ps(1)

            if valid:
                patterns.append(pattern_id)

        return patterns

def pe4(name: str | None = None) -> Component:
    s = GLOBAL_SYSTEM

    i0, i1, i2, i3 = [s.port(1) for _ in range(4)]

    o0 = s.comb("OR", i3, s.comb("AND", i2.not_(), i1))
    t = s.comb("OR", i3, i2)

    o1 = s.port(1)
    o1.set_driver(t)
    clk = s.port(1, name=f"{name}:PE_{4}:clk")
    vid = s.comb("OR", t, i1, i0, name=f"{name}:PE_{4}:vid" if name is not None else None) \
            .dflipflop(clk, name is not None) \
            .register_signal(GLOBAL_SIGNAL)

    idx = s.vector(o0, o1, name=f"{name}:PE_{4}:idx" if name is not None else None) \
            .dflipflop_vector(clk, name is not None) \
            .register_signal(GLOBAL_SIGNAL)

    return Component([idx, vid], [i0, i1, i2, i3, clk])

def pe_n(n: int, name: str | None = None) -> Component:
    r"""
Pipelining logic:

*  /[n] width of wire
*  ->|  input to component
*  |>-  output of component
* -[s]- name of wire
*  -D*- multiple D-flip-flops
*  -D-  single D-flip-flops


| Stage 1                                | Stage 2                  | Stage 3      | Stage 4
 
              +-----+>--idx--/log2(n÷4)--D*-------------------------D*-\
      /-/n÷4->|PEn÷4|                                                   \   |\
     /        +-----+>--vid--/1----------D----\                          \->| \
    /         +-----+>-------------------D*---|---------------------D*-\    |  \
  -/  /-/n÷4->|PEn÷4|                         |                         \-->|  |
D*---/        +-----+>-------------------D*--\|                             |  |>--D*----+===>
  ---\        +-----+>-------------------D---||---------------------D*----->|  |         |
  -\  \-/n÷4->|PEn÷4|                        ||                             |  /         |
    \         +-----+>-------------------D--\||                         /-->| /          |
     \        +-----+>-------------------D*-|||---------------------D*-/    |/^          |
      \-/n÷4->|PEn÷4|                       |||                               |          |
              +-----+>-------------------D-\|||                               |          |
                                            \\\\                              |          |
                                             \\\\->+---+                      +----D*----/
                                              \\\->|PE4|>--idx--/2--D*--------/
                                               \\->|   |>--v----/1--D--------------D--------->
                                                \->+---+

"""
    assert n >= 4, n
    if n == 4:
        return pe4(name)
    assert n % 4 == 0

    s = GLOBAL_SYSTEM
    nk = n // 4

    root = f"{name}:PE_{n}" if name is not None else f"PE_{n}"
    clk = s.port(1, name=f"{root}:clk")
    inp = []
    sub_idx = []
    vs = []
    for i in range(4):
        sub_pe = pe_n(nk, f"{root}:{i}")
        inp.extend(sub_pe.get_inputs())
        sub_pe_idx, sub_v = sub_pe.get_outputs()
        # Delay the signal with a single flip flop to await
        # the multiplexer-selector
        # (stage 3)
        sub_idx.append(
                sub_pe_idx.dflipflop_vector(clk))
        vs.append(sub_v)
    
    sel = pe4(f"{root}:selector")
    for sel_i, v_out in zip(sel.get_inputs(), vs):
        assert isinstance(sel_i, Port)
        sel_i.set_driver(v_out)

    sel_idx, vid = sel.get_outputs()

    sel_idx_ff = sel_idx.dflipflop_vector(clk, name=f"{root}:idx_upper").register_signal(GLOBAL_SIGNAL)
    vid_ff = vid.dflipflop(clk, name=f"{root}:vid").register_signal(GLOBAL_SIGNAL)

    mux = s.mux(sel_idx, *sub_idx, name=f"{root}:idx_lower") \
            .dflipflop_vector(clk, True) \
            .register_signal(GLOBAL_SIGNAL)
    idx = s.vector(mux, sel_idx_ff, name=f"{root}:idx") \
            .register_signal(GLOBAL_SIGNAL)

    return Component([idx, vid_ff], inp)

def gen_random(length: int, patterns_in: list[str]) -> tuple[bytes, list[int]]:
    import random
    length = int(length)
    random.seed(0)
    patterns: list[bytes] = []

    for line in patterns_in:
        patterns.append(line.encode("ascii"))
    
    stream: bytearray = bytearray()

    while len(stream) < length:
        if random.random() < 0.2:
            seq_len = random.randint(8, 64)
            random_bytes = random.randbytes(seq_len)
            stream += random_bytes 
        else:
            pattern_id = random.randint(1, len(patterns))
            pattern = patterns[pattern_id-1]
            stream += pattern
        
    # truncate
    stream = stream[:length]

    # patch with 0s
    pkt_size = 512 // 8
    rem = len(stream) % pkt_size
    if rem > 0:
        stream += bytes(0 for _ in range(pkt_size - rem))
    
    # Run brute force version of the algorithm
    order = []
    window = bytes()
    for b in stream:
        window = bytes([b]) + window
        # This simulates our approach
        for i, pattern in enumerate(patterns):
            if window.startswith(bytes(reversed(pattern))):
                order.append(i)
                break
    
    return bytes(stream), order

def main_single():
    # print("Generating PE component")

    # pe = pe_n(4**6) 

    # print("Approximate number of Components:", sum(map(Logic.count_logic_instances, pe.get_outputs())))

    # print("Generating graph")
    # graph = Digraph("PE4", engine="sfdp")
    
    # idx, vid = pe.get_outputs()
    # for i, inp in enumerate(pe.get_inputs()):
    #     inp.set_name(f"in:{i}")

    # idx.graph_bw(graph)
    # vid.graph_bw(graph)

    # graph.render()

    patterns = open(".\\inputs\\MINI_pattern_match_snort3_content.txt").read().splitlines()

    # s = GLOBAL_SYSTEM
    # decode_parser = DecoderParser(patterns)

    # print("Generating graph")
    # graph = Digraph("dcam")
    # for out in decode_parser._pe.get_outputs():
    #     out.graph_bw(graph)
    # graph.render()

    # GLOBAL_SYSTEM.enable_trace()

    pattern_stream, _ = gen_random(1024, patterns)    
    open("temp.txt", "w").write(repr(pattern_stream))
    exit(0)
    # print(pattern_stream)
    # print("Saving expected order in order.txt")
    # with open("order.txt", "w") as order_txt:
    #     for pid in id_order:
    #         row = pid + 1
    #         print(f"{row:4}: {patterns[pid]}", file=order_txt)
    # exit(0)
    # pattern_ids = decode_parser.simulate(1032, pattern_stream)

    # if len(pattern_ids) != len(id_order):
    #     print("ERROR: mismatch between the two orders")

    # print("Saving seen order in actual.txt")
    # with open("actual.txt", "w") as actual_txt:
    #     for pid in pattern_ids:
    #         row = len(patterns) - pid
    #         index = row - 1
    #         print(f"{row:4}: {patterns[index]}", file=actual_txt)

    # trace_root = Path(".\\trace")
    # trace_root.mkdir(exist_ok=True)

    # signal_root = Path(".\\signal")
    # signal_root.mkdir(exist_ok=True)

    # d = datetime.today()
    # date_portion = d.strftime("%y%m%d")
    # time_portion = d.hour * 3600 + d.minute * 60 + d.second

    # if GLOBAL_SYSTEM.has_trace():
    #     trace_file = f"{date_portion}_{time_portion}.trace"
    #     with open(trace_root / trace_file, "w", encoding="utf-8") as fp:
    #         fp.write(autoindent(GLOBAL_SYSTEM.get_trace()))

    # signal_file = f"{date_portion}_{time_portion}.vcd" 
    # with open(signal_root / signal_file, "w", encoding="utf-8") as fp:
    #     fp.write(GLOBAL_SIGNAL.dump_vcd())

def main_parallel(degree: int, pattern_path: str):
    GLOBAL_SYSTEM.enable_trace()

    patterns = open(pattern_path).read().splitlines()
    parsers = DecoderParserParallel(degree, patterns)

    # print("Generating graph")
    # graph = Digraph("dcam")
    # for m in parsers._pes:
    #     for out in m.get_outputs():
    #         out.graph_bw(graph)
    # graph.render()

    print(parsers.simulate(24, b"brownquickthe"))

    trace_root = Path("./trace")
    trace_root.mkdir(exist_ok=True)

    signal_root = Path("./signal")
    signal_root.mkdir(exist_ok=True)

    d = datetime.today()
    date_portion = d.strftime("%Y%m%d")
    time_portion = d.hour * 3600 + d.minute * 60 + d.second

    if GLOBAL_SYSTEM.has_trace():
        trace_file = f"{date_portion}_{time_portion}.trace"
        with open(trace_root / trace_file, "w", encoding="utf-8") as fp:
            fp.write(autoindent(GLOBAL_SYSTEM.get_trace()))

    signal_file = f"{date_portion}_{time_portion}.vcd" 
    with open(signal_root / signal_file, "w", encoding="utf-8") as fp:
        fp.write(GLOBAL_SIGNAL.dump_vcd())

def vhdl_parallel(degree: int, source: Path | str):
    patterns = open(source).read().splitlines()
    s = GLOBAL_SYSTEM
    
    clk = s.port(1, name="clk")
    inputs = [s.port(8, name=f"input_{i}") for i in range(degree)]
    parsers = DecoderParserParallel(degree, patterns)

    s.set_global_clk(clk)
    parsers.set_input(inputs)

    dofile = StringIO()
    dofile_outputs = []
    render = vhdl_renderer.VHDLRenderer("krnl_proj")
    for pe in parsers._pes:
        for out in pe.get_outputs():
            name = out.get_name().replace(":", "_")
            render.feed_output(name, out)
            dofile_outputs.append(name)
    
    dofile_inputs = [f"r_input_{i}" for i in range(degree)] 

    print("restart -f -nowave", file=dofile)
    print("add wave -position insertpoint \\", file=dofile)
    print("sim:/krnl_proj/clk \\", file=dofile)
    print(" \\\n".join(f"sim:/krnl_proj/{n}" for n in [*dofile_inputs, *dofile_outputs]), file=dofile)
    print("", file=dofile)    
    print("force clk 0 0, 1 10ns -repeat 20ns", file=dofile)

    msg = "Hello...@@@"

    for i in range(16):
        print("", file=dofile)
        for j in range(4):
            jj = i*degree + j
            if jj < len(msg):
                c = msg[jj]
            else:
                c = '\0'
            
            print(f"force r_input_{j} 10#{ord(c)}", file=dofile)
        print("run 20ns", file=dofile)

    render.process()
    outdir = Path("bin")
    outdir.mkdir(exist_ok=True)
    with open(outdir / "krnl_proj.vhd", "w") as fp:
        fp.write(render.render())

    with open(outdir / "krnl_proj.do", "w") as fp:
        fp.write(dofile.getvalue())

def simple_vhdl():
    s = GLOBAL_SYSTEM

    clk = s.port(1, name="clk")
    expr1 = s.comb("AND", Bits(1, [True]), Bits(1, [False]))
    expr1_reg = expr1.dflipflop(clk, name="expr1")

    expr2 = s.comb("OR", expr1_reg, Bits(1, [True]))

    renderer = vhdl_renderer.VHDLRenderer("test_design")
    renderer.feed_assignment("expr2", expr2)

    renderer.process()    

    print(renderer.render())

if __name__ == "__main__":
    vhdl_parallel(4, "./inputs/MINI_pattern_match_snort3_content.txt")

