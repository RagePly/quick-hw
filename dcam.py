from quick_hw import *
from pathlib import Path
from datetime import datetime
from autoindent import autoindent

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

def connect_to_clock(clk: Logic, logic: list[Component]):
    for log in logic:
        _, clk_log = log.find_logic("clk")
        assert isinstance(clk_log, Port), \
            "expected clk connection to be a Port"
        clk_log.set_driver(clk)

class DecoderParser:
    def __init__(self, patterns: list[str]):
        self._matchers, self._decoders = generate_parsers(patterns)
        connect_decoder_matchers(self._matchers, self._decoders)
    
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
        output = {}
        for pat, mat in self._matchers.items():
            mat.eval_all()
            _, output[pat] = mat.find_logic("out")
        return output
    
    def simulate_step(self):
        self.eval_output()     
    
    def simulate(self, steps: int, input_str: str):
        s = GLOBAL_SYSTEM
        clk = s.port(1, name="clk")
        input_port = s.port(8, name="input")

        clk.register_signal(GLOBAL_SIGNAL)
        input_port.register_signal(GLOBAL_SIGNAL)

        self.add_clk(clk)
        self.set_input(input_port)

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
            self.eval_output()
            GLOBAL_SYSTEM.commit()

            GLOBAL_SIGNAL.step_time_ps(1)

def priority_id_encoder(count: int) -> Component:
    # TODO: ... 
    # Just look up how they work
    # It seems hard to figure out a match_x to id (int) type thing
    # Or that could be handled by HLS...  yeah, let HLS figure out that!
    ...
    
if __name__ == "__main__":
    patterns = open(".\\inputs\\overlap.txt").read().splitlines()

    # s = GLOBAL_SYSTEM
    decode_parser = DecoderParser(patterns)

    decode_parser.simulate(12, "abc")

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

    # input_bits = Bits(8, name="input")
    # input_clk = Bits(1, name="clk")
    # decode_parser = DecoderParser(patterns)
    # decode_parser.add_clk(input_clk)
    # decode_parser.set_input(input_bits)
    # graph = Digraph("dcam")
    # for parser in decode_parser._matchers.values():
    #     for out in parser.get_outputs():
    #         out.graph_bw(graph)
    # graph.render()
