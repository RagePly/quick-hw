from typing import cast
from quick_hw import *
from pathlib import Path
from datetime import datetime
from autoindent import autoindent
from math import log2, ceil

GLOBAL_SIGNAL = Signal()
GLOBAL_SYSTEM = System()

def parse_char(c: str) -> Component:
    assert len(c) == 1
    assert c.isascii()

    s = GLOBAL_SYSTEM

    name = f"match_{hex(ord(c))}"

    clk = s.port(1, name=f"{name}:clk")
    c_bits = Bits.from_ascii(c)
    inp = s.port(8, name=f"{name}:input")
    cmps = [s.comb("XNOR", c_bit, inp_bit, name=f"{name}:comp_{hex(ord(c))}_{i}").dflipflop(clk, True).register_signal(GLOBAL_SIGNAL) for i, (c_bit, inp_bit) in enumerate(zip(c_bits.unwrap(), inp.unwrap()))]
    comp = s.comb("AND", *cmps, name=f"{name}:eval").shr(clk, signal_dffs=GLOBAL_SIGNAL, name=f"{name}:out")

    return Component([comp], [clk, inp])

def solve_match(sid: int, pattern: str) -> Component:
    s = GLOBAL_SYSTEM
    char_ports = [
        s.port(1, name=f"match_p_{sid}_{len(pattern) - 1 - i}:match_{hex(ord(c))}")
        for i, c in enumerate(pattern)
    ]
    clk = s.port(1, name=f"match_p_{sid}:clk")

    target = s.comb("AND", *char_ports, name=f"match_p_{sid}:out").dflipflop(clk, True)
    target.register_signal(GLOBAL_SIGNAL)

    return Component([target], [clk, *char_ports])

def connect_parser_matcher(parsers: map[str, Logic], match_logic: Component):
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

def generate_decoders_from_patterns(patterns: list[str]) -> map[str, Component]:
    chars = set(c for pat in patterns for c in pat)
    return {c: parse_char(c) for c in chars}

def generate_matchers_from_patterns(patterns: list[str]) -> map[str, Component]:
    return {pat: solve_match(i, pat) for i, pat in enumerate(patterns)}

def generate_parsers(patterns: list[str]) -> tuple[dict[str, Component], dict[str, Component]]:
    decoders = generate_decoders_from_patterns(patterns)
    matchers = generate_matchers_from_patterns(patterns)
    return matchers, decoders

def connect_decoder_matchers(matchers: map[str, Component], decoders: map[str, Component]):
    decoder_output = dict(comp.find_logic("out") for comp in decoders.values())
    for matcher in matchers.values():
        connect_parser_matcher(decoder_output, matcher)

def generate_priority(patterns: list[str], tot_inp: int) -> dict[str, int]:
    return {p: tot_inp - 1 - i for i, p in enumerate(patterns)}

def generate_pe(patterns: list[str]) -> Component:
    required = 4**ceil(log2(len(patterns)) / 2)
    print(f"Generating Priority encoder with {required}-inputs")
    pe =  pe_n(required, f"PE")
    idx, vid = pe.get_outputs()
    idx.register_signal(GLOBAL_SIGNAL)
    vid.register_signal(GLOBAL_SIGNAL)

    return pe


def connect_matchers_pe(patterns: list[str], matchers: dict[str,Component], pe: Component):
    priority = generate_priority(patterns, len(pe.get_inputs()))
    missing = len(pe.get_inputs()) - len(matchers)

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

def connect_to_clock(clk: Logic, logic: list[Component]):
    for log in logic:
        _, clk_log = log.find_logic("clk")
        assert isinstance(clk_log, Port), \
            "expected clk connection to be a Port"
        clk_log.set_driver(clk)

class DecoderParser:
    def __init__(self, patterns: list[str]):
        self._matchers, self._decoders = generate_parsers(patterns)
        self._pe = generate_pe(patterns)
        connect_decoder_matchers(self._matchers, self._decoders)
        connect_matchers_pe(patterns, self._matchers, self._pe)
    
    def add_clk(self, clk: Logic):
        connect_to_clock(clk, list(self._decoders.values()))
        connect_to_clock(clk, list(self._matchers.values()))
    
    def set_input(self, input_bits: Logic):
        for dec in self._decoders.values():
            _, inp = dec.find_logic("input")
            assert isinstance(inp, Port), \
                "expected input to be a Port"
            inp.set_driver(input_bits)
    
    def eval_output(self) -> dict[str, bool]:
        idx, vid = self._pe.get_outputs()

        is_valid = vid.eval()
        idx_bits = idx.eval()

        return is_valid.as_bitarray()[0], idx_bits.to_int()
        
    def simulate_step(self):
        self.eval_output()     
    
    def simulate(self, steps: int, input_str: str) -> list[int]:
        s = GLOBAL_SYSTEM
        clk = s.port(1, name="clk")
        input_port = s.port(8, name="input")

        clk.register_signal(GLOBAL_SIGNAL)
        input_port.register_signal(GLOBAL_SIGNAL)

        self.add_clk(clk)
        self.set_input(input_port)

        patterns = []

        for i in range(steps):
            print(f"Simulating {i+1:3}/{steps:3}")
            if i < len(input_str):
                input_port.set_driver(Bits.from_ascii(input_str[i]))
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
    vid = s.comb("OR", t, i1, i0, name=f"{name}:PE_{4}:vid" if name is not None else None)

    idx = s.vector(o0, o1, name=f"{name}:PE_{4}:idx" if name is not None else None)

    return Component([idx, vid], [i0, i1, i2, i3])

def pe_n(n: int, name: str | None = None) -> Component:
    assert n >= 4
    if n == 4:
        return pe4(name)
    assert n % 4 == 0

    s = GLOBAL_SYSTEM
    nk = n // 4

    root = f"{name}:PE_{n}" if name is not None else f"PE_{n}"
    inp = []
    sub_idx = []
    vs = []
    for i in range(4):
        sub_pe = pe_n(nk, f"{root}:{i}") 
        inp.extend(sub_pe.get_inputs())
        sub_pe_idx, sub_v = sub_pe.get_outputs()
        sub_idx.append(sub_pe_idx)
        vs.append(sub_v)
    
    sel = pe4(None)
    for sel_i, v_out in zip(sel.get_inputs(), vs):
        assert isinstance(sel_i, Port)
        sel_i.set_driver(v_out)

    sel_idx, vid = sel.get_outputs()
    vid.set_name(f"{root}:vid")
    sel_idx.set_name(f"{root}:idx_upper")

    mux = s.mux(sel_idx, *sub_idx)
    idx = s.vector(mux, sel_idx, name=f"{root}:idx")
    
    return Component([idx, vid], inp)

if __name__ == "__main__":

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
    decode_parser = DecoderParser(patterns)

    # print("Generating graph")
    # graph = Digraph("dcam")
    # for out in decode_parser._pe.get_outputs():
    #     out.graph_bw(graph)
    # graph.render()

    # GLOBAL_SYSTEM.enable_trace()

    pattern_ids = decode_parser.simulate(32, "/environ.pl .pl")

    print("Saw patterns: ")
    for pid in pattern_ids:
        row = len(patterns) - pid
        index = row - 1
        print(f"{row:4}: {patterns[index]}")

    trace_root = Path(".\\trace")
    trace_root.mkdir(exist_ok=True)

    signal_root = Path(".\\signal")
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

