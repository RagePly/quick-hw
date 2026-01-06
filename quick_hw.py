from typing import Any, Callable, cast
from collections.abc import Iterator
from functools import singledispatchmethod
from graphviz import Digraph
from io import StringIO
from quick_util import warn_once
from re import Pattern

class System:
    def __init__(self):
        self._values: dict[int, Bits] = {}
        self._state_comp: list[Logic] = []
        self._iota = 0
        self._trace = False
        self._tracefile = StringIO()
        self._refs: list[Logic] = []
        self._clk: Port | None = None
    
    def add_ref(self, ref: Logic):
        self._refs.append(ref)

    def enable_trace(self):
        self._trace = True
    
    def disable_trace(self):
        self._trace = False
    
    def has_trace(self) -> bool:
        return self._trace
    
    def tprint(self, *args, **kwargs):
        if self.has_trace():
            print(*args, **kwargs, file=self._tracefile)
    
    def get_trace(self) -> str:
        return self._tracefile.getvalue()

    def prepare(self):
        self.tprint("========== CLEAR CACHE ==========")
        self._values.clear()
    
    def _new(self) -> int:
        i = self._iota
        self._iota += 1

        return i
    
    def commit(self):
        for state_comp in self._state_comp:
            if isinstance(state_comp, DFlipFlop):
                prev = state_comp._val
                self.tprint(f"BEGIN COMMIT {state_comp.__class__}: {state_comp._name}")
                state_comp.commit()
                self.tprint(f"END COMMIT {prev} => {state_comp._val}")
            else:
                raise Exception("invalid state-less component added")

    def all_ports(self) -> Iterator[Port]:
        return cast(Iterator[Port], filter(lambda c: isinstance(c, Port), self._refs))

    @singledispatchmethod
    def find_ports(self, pattern) -> Iterator[Port]:
        raise ValueError(f"invalid pattern type: {type(pattern)}")

    @find_ports.register
    def _find_ports_str(self, pattern: str) -> Iterator[Port]:
        return filter(lambda p: p.has_name() and p.get_name().endswith(":" + pattern), 
                      self.all_ports())

    @find_ports.register
    def _find_ports_re(self, pattern: Pattern) -> Iterator[Port]:
        return filter(lambda p: p.has_name() and pattern.fullmatch(p.get_name()) is not None, 
                      self.all_ports())

    def set_global_clk(self, clk: Logic):
        for clk_port in self.find_ports("clk"):
            clk_port.set_driver(clk)
    
    def get_cached(self, i: int) -> Bits | None:
        return self._values.get(i, None)
    
    def update_cache(self, i: int, b: Bits):
        assert i not in self._values
        self._values[i] = b
    
    def wire(self, inp: Logic, index: int, **kwargs) -> Wire:
        system_id = self._new()
        _kwargs: dict[str, Any] = {"system": self, "system_id": system_id}
        _kwargs.update(kwargs)
        return Wire(inp, index, **_kwargs)
    
    def port(self, width: int, **kwargs) -> Port:
        system_id = self._new()
        _kwargs: dict[str, Any] = {"system": self, "system_id": system_id}
        _kwargs.update(kwargs)
        return Port(width, **_kwargs)

    def comb(self, var: str, *inputs: Logic, **kwargs) -> Comb:
        system_id = self._new()
        _kwargs: dict[str, Any] = {"system": self, "system_id": system_id}
        _kwargs.update(kwargs)
        return Comb(var, *inputs, **_kwargs)
    
    def dflipflop(self, input: Logic, clk: Logic, **kwargs) -> DFlipFlop:
        system_id = self._new()
        _kwargs: dict[str, Any] = {"system": self, "system_id": system_id}
        _kwargs.update(kwargs)
        dff = DFlipFlop(input, clk, **_kwargs)
        self._state_comp.append(dff)
        return dff
    
    def shr(self, input: Logic, clk: Logic, signal_dffs: Signal | None = None, **kwargs) -> SHR:
        system_id = self._new()
        _kwargs: dict[str, Any] = {"system": self, "system_id": system_id}
        _kwargs.update(kwargs)
        return SHR(input, clk, signal_dffs, **_kwargs)
    
    def mlutn(self, n: int, rules: Callable[[Bits], Bits], *inp: Logic, **kwargs) -> MLUTN:
        system_id = self._new()
        _kwargs: dict[str, Any] = {"system": self, "system_id": system_id}
        _kwargs.update(kwargs)
        return MLUTN(n, rules, *inp, **_kwargs)
    
    def not_(self, inp: Logic, **kwargs) -> Not:
        system_id = self._new()
        _kwargs: dict[str, Any] = {"system": self, "system_id": system_id}
        _kwargs.update(kwargs)
        return Not(inp, **_kwargs)
    
    def vector(self, *inp: Logic, **kwargs) -> Vector:
        system_id = self._new()
        _kwargs: dict[str, Any] = {"system": self, "system_id": system_id}
        _kwargs.update(kwargs)
        return Vector(*inp, **_kwargs)

    def mux(self, selector: Logic, *inp: Logic, **kwargs) -> Mux:
        system_id = self._new()
        _kwargs: dict[str, Any] = {"system": self, "system_id": system_id}
        _kwargs.update(kwargs)
        return Mux(selector, *inp, **_kwargs)


class Event:
    def __init__(self, name: str, width: int, value: "Bits"):
        self._name = name
        self._width = 0
        self._value = value
    
    def get_name(self) -> str:
        return self._name
    
    def get_width(self) -> int:
        return self._width
    
    def get_value(self) -> "Bits":
        return self._value
    
    def __repr__(self):
        return f"Event({repr(self._name)}, {repr(self._width)}, {repr(self._value)})"

class Timestamp:
    def __init__(self, ts: int):
        self._ts = ts
        self._events: list[Event] = []
        self._registerred: dict[str, int] = {}   

    def add_event(self, event: Event):
        if event.get_name() in self._registerred:
            self._events[self._registerred[event.get_name()]] = event
        else:
            self._registerred[event.get_name()] = len(self._events)
            self._events.append(event)
    
    def get_ts(self) -> int:
        return self._ts
    
    def get_events(self) -> list[Event]:
        return self._events

class Signal:
    def __init__(self):
        self._time = 0

        self._signals: dict[str, int] = dict()
        self._timestamps: list[Timestamp] = []
        self.step_time_ps(0)
    
    def add_signal(self, name: str, width: int):
        assert name not in self._signals, \
            "duplicate signal names"
        self._signals[name] = width
    
    def step_time_ps(self, amount: int):
        self._time += amount
        self._timestamps.append(Timestamp(self._time))

    def register_signal(self, name: str, value: "Bits"):
        self._timestamps[-1].add_event(Event(name, self._signals[name], value))
    
    def dump_vcd(self) -> str:
        lines: list[str] = []
        lines.append("$date")
        lines.append(f"Not yet implemented {__file__}")
        lines.append("$end")
        lines.append("$version")
        lines.append(" quick_hw.py 0.0.1")
        lines.append("$end")
        lines.append("$timescale 1ps $end")
        lines.append("$scope module logic $end")


        id_lookup: dict[str, str] = {}
        for i, (name, width) in enumerate(self._signals.items()):
            ident = f"%id{i}"
            id_lookup[name] = ident
            lines.append(f"$var wire {width} {ident} {name} $end")

        lines.append("$upscope $end")
        lines.append("$enddefinitions $end")
        lines.append("$dumpvars")

        for ts in self._timestamps:
            lines.append(f"#{ts.get_ts()}")

            for event in ts.get_events():
                ident = id_lookup[event.get_name()]
                if event.get_value().is_valid():
                    lines.append(f"b{''.join(reversed(['01'[b] for b in event.get_value().as_bitarray()]))} {ident}")
                else:
                    width = event.get_width()
                    lines.append(f"b{'x' * width} {ident}")
        lines.append(f"#{self._timestamps[-1].get_ts()+1}")
        return "\n".join(lines)


_DEBUG_CONNECTED_EDGES: set[tuple[str, str]] = set()

def connect_edge(fr: Logic, to: Logic, graph: Digraph):
    fr_s = fr.node_name()
    to_s = to.node_name()

    if (fr_s, to_s) not in _DEBUG_CONNECTED_EDGES:
        _DEBUG_CONNECTED_EDGES.add((fr_s, to_s))
        graph.edge(fr_s, to_s)

class Logic:
    def __init__(self, /, name: str | None = None, system: System | None = None, system_id: int | None = None):
        self._name = name
        self._fw_con: list[Logic] = []
        self._bw_con: list[Logic] = []
        self._signal: Signal | None = None
        self._system = system
        self._system_id = system_id
        
        if self._system is not None:
            self._system.add_ref(self)
    
    def _register_fw(self, fw: "Logic"):
        self._fw_con.append(fw)

    def _register_bw(self, bw: "Logic"):
        self._bw_con.append(bw)
    
    def node_name(self) -> str:
        return f"{self.get_name().replace(":", ".")}@{self.__class__.__name__}" if self.has_name() else f"{id(self)}@{self.__class__.__name__}"

    def graph_bw(self, graph: Digraph, fr: Logic | None = None):
        # Set connections
        if fr is not None:
            connect_edge(self, fr, graph)

        # Recurse
        for bw_con in self._bw_con:
            bw_con.graph_bw(graph, self)
    
    @staticmethod
    def _register_con(fr: "Logic", to: "Logic"):
        fr._register_fw(to)
        to._register_bw(fr)

    def get_name(self) -> str:
        assert self._name is not None
        return self._name

    def set_name(self, name: str):
        self._name = name
    
    def unset_name(self):
        assert self._signal is None, \
            "Unset name for logic already registered"
        self._name = None 

    def has_name(self) -> bool:
        return self._name is not None

    def is_clk(self) -> bool:
        return isinstance(self, Port) and self.has_name() and (
                self.get_name().endswith(":clk") or self.get_name() == "clk")
    
    def register_signal(self, signal: Signal) -> "Logic":
        assert self._name is not None, \
            "Cannot register nameless signal"
        if self._signal is None:
            self._signal = signal
            signal.add_signal(self._name, self.width())
        return self
    

    def width(self) -> int:
        raise RuntimeError(f"width not implemented for {self.__class__}")
    
    def dflipflop(self, clk: "Logic", inherit_name: bool = False, **kwargs) -> DFlipFlop:
        if inherit_name:
            assert "name" not in kwargs, \
                "cannot inherit name if an explicit name is requested"
            kwargs["name"] = self.get_name()
            self.unset_name()

        if self._system is not None:
            dff = self._system.dflipflop(self, clk, **kwargs)
        else:
            dff = DFlipFlop(self, clk, **kwargs)
        return dff

    def dflipflop_vector(self, clk: "Logic", inherit_name: bool = False, **kwargs) -> Vector:
        assert self.width() > 1, \
                "You cannot add a vectored dflipflop to a logic-component with width 1"
        dffs = [c.dflipflop(clk) for c in self.unwrap()]

        if inherit_name:
            assert "name" not in kwargs, \
                "cannot inherit name if an explicit name is requested"
            kwargs["name"] = self.get_name()
            self.unset_name()

        if self._system is not None:
            dff_vec = self._system.vector(*dffs, **kwargs)
        else:
            assert False
            dff_vec = Vector(*dffs, **kwargs)

        return dff_vec
    
        
    def shr(self, clk: "Logic", inherit_name: bool = False, signal_dffs: Signal | None = None, **kwargs) -> "Logic":
        if inherit_name:
            assert "name" not in kwargs, \
                "cannot inherit name if an explicit name is requested"
            kwargs["name"] = self.get_name()
            self.unset_name()

        if self._system is not None:
            shr = self._system.shr(self, clk, signal_dffs, **kwargs)
        else:
            shr = SHR(self, clk, signal_dffs, **kwargs)
        return shr

    def not_(self, **kwargs) -> Not:
        if self._system is not None:
            n = self._system.not_(self, **kwargs)
        else:
            n = Not(self, **kwargs)
        return n
    
    def count_logic_instances(self, visited: set[int] | None = None) -> int:
        self_id = id(self)
        if visited is None:
            visited = set()
            visited.add(self_id)
            this = 1
        elif self_id not in visited:
            visited.add(self_id)
            this =  1
        else:
            this = 0
        return this + sum(sublog.count_logic_instances(visited) for sublog in self._bw_con)
    
    def signal_event(self, value: "Bits") -> "Bits":
        assert value is not None
        if self._signal is None:
            return value
        self._signal.register_signal(self.get_name(), value) 
        return value
    
    def tprint(self, *args, **kwargs):
        if self._system is not None:
            self._system.tprint(*args, **kwargs)
    
    def eval(self) -> Bits:
        self.tprint(f"BEGIN EVAL {self.__class__}: {self._name}")
        if self._system is not None and self._system_id is not None and (res := self._system.get_cached(self._system_id)) is not None:
            self.tprint(f"END EVAL {self.__class__}: {self._name} CACHE {res}")
            return res
        b = self.signal_event(self._eval_impl())
        self.tprint(f"END EVAL {self.__class__}: {self._name} = {b}")
        if self._system is not None and self._system_id is not None:
            self._system.update_cache(self._system_id, b)
        return b
    
    def _eval_impl(self) -> Bits:
        raise RuntimeError(f"eval not implemented for {self.__class__}")
    
    def unwrap(self) -> list["Logic"]:
        if self._system is not None:
            return [self._system.wire(self, i) for i in range(self.width())]
        return [Wire(self, i) for i in range(self.width())]
    
    def _name_repr(self) -> str:
        if self._name is not None:
            return f", name={repr(self._name)}"
        return ""
    
class Bits(Logic):
    def __init__(self, width: int, value: list[bool] | None = None, **kwargs):
        super().__init__(**kwargs)
        assert value is None or len(value) == width
        self._width = width
        self._value = value
    
    def width(self):
        return self._width

    def graph_bw(self, graph, fr = None):
        if self.has_name() and self.get_name().endswith("clk"):
            return
        if self._value is not None:
            graph.node(self.node_name(), "".join(str(int(b)) for b in self._value), shape="parallelogram")
        return super().graph_bw(graph, fr)

    def is_valid(self) -> bool:
        return self._value is not None

    def as_bitarray(self) -> list[bool]:
        assert self._value is not None, \
            "invalid bits"
        return list(self._value)
    
    def to_int(self) -> int:
        assert self._value is not None, \
            "invalid bits"
        i = 0
        for off, b in enumerate(self._value):
            i |= int(b) << off
        
        return i
    def count_logic_instances(self, visited: set[int] | None = None) -> int:
        if visited is None:
            visited = set()
        visited.add(id(self))
        return super().count_logic_instances(visited)

    
    @staticmethod
    def from_int(n: int) -> Bits:
        bits = Bits(8, [bool(1 & (n >> i)) for i in range(8)])
        return bits
    
    def _eval_impl(self):
        return Bits(self._width, list(self._value) if self._value is not None else None)
    
    @staticmethod
    def from_ascii(s: str) -> "Bits":
        assert len(s) == 1, \
            "only single bytes supported TODO: add multibyte"
        
        cn = ord(s)
        bits = Bits(8, [bool(1 & (cn >> i)) for i in range(8)])

        return bits
    
    def unwrap(self) -> list["Logic"]:
        assert self.is_valid, \
            "can't unwrap unitialized bits"
        return [Bits(1, [b]) for b in self.as_bitarray()]
    
    def __repr__(self) -> str:
        return f"Bits({repr(self._width)}, {repr(self._value)}{self._name_repr()})"

class Vector(Logic):
    def __init__(self, *inp: Logic, **kwargs):
        super().__init__(**kwargs)

        self._inp = inp
        self._w = sum(i.width() for i in self._inp)

        for i in self._inp:
            self._register_con(i, self)
    
    def count_logic_instances(self, visited: set[int] | None = None) -> int:
        if visited is None:
            visited = set()
        visited.add(id(self))
        return super().count_logic_instances(visited)

    def width(self):
        return self._w
    
    def _eval_impl(self):
        return Bits(self.width(), [b for i in self._inp for b in i.eval().as_bitarray()])
    
    def __repr__(self) -> str:
        return f"Vector({', '.join(map(repr, self._inp))}{self._name_repr()})"

class Mux(Logic):
    def __init__(self, selector: Logic, *inp: Logic, **kwargs):
        super().__init__(**kwargs)

        self._sel = selector
        self._inp = inp
        self._w = inp[0].width()

        assert 2**self._sel.width() == len(self._inp)
        assert all(i.width() == self._w for i in self._inp)

        self._register_con(selector, self)
        for i in self._inp:
            self._register_con(i, self)

    
    def width(self):
        return self._w

    def _eval_impl(self):
        idx = self._sel.eval().to_int()
        inps = [i.eval() for i in self._inp]
        return inps[idx]
    
    def __repr__(self) -> str:
        return f"Mux({repr(self._sel)}, {', '.join(map(repr, self._inp))}{self._name_repr()})"

class Wire(Logic):
    def __init__(self, inp: Logic, index: int, **kwargs):
        super().__init__(**kwargs)

        self._inp = inp
        self._index = index

        self._register_con(inp, self)
    
    def count_logic_instances(self, visited: set[int] | None = None) -> int:
        if visited is None:
            visited = set()
        visited.add(id(self))
        return super().count_logic_instances(visited)

    def node_name(self):
        return super().node_name() + f"({self._index})"
    
    def _eval_impl(self) -> "Bits":
        sub = self._inp.eval()
        return Bits(1, [sub.as_bitarray()[self._index]])
    
    def width(self):
        return 1

    def __repr__(self) -> str:
        return f"Wire({repr(self._inp)}, {repr(self._index)}{self._name_repr()})"

class SHR(Logic):
    def __init__(self, inp: Logic, clk: Logic, signal_dffs: Signal | None = None, **kwargs):
        super().__init__(**kwargs)
        
        self._inp = inp
        self._clk = clk
        self._signal_dffs = signal_dffs
        self._layers: list[DFlipFlop] = [inp.dflipflop(clk, name=self._shift_name(0))]

        if self._signal_dffs is not None:
            self._layers[-1].register_signal(self._signal_dffs)
    
    def _shift_name(self, index: int) -> str | None:
        if self.has_name():
            return f"{self.get_name()}:{index}"

    def index(self, index: int) -> DFlipFlop:
        while index >= len(self._layers):
            layer_index = len(self._layers)
            layer_name = self._shift_name(layer_index)
            self._layers.append(self._layers[-1].dflipflop(self._clk, name=layer_name))

            if self._signal_dffs is not None:
                self._layers[-1].register_signal(self._signal_dffs)

        return self._layers[index]
    
    def width(self):
        return 1
    
    def node_name(self):
        raise Exception("tried to get the node-name for a shift register, you probably tried to connect to it without selecting an offset")


    def graph_bw(self, graph, fr = None):
        raise Exception(f"tried to build a graph from a shift register (came from {repr(fr)}), you probably tried to connect to it without selecting an offset")

    def _eval_impl(self):
        raise Exception("tried to eval meta-logic shift register, you probably tried to connect to it without selecting an offset")

    def __repr__(self) -> str:
        return f"SHR({repr(self._inp)}, {repr(self._clk)}{self._name_repr()})"
    
class Port(Logic):
    def __init__(self, width: int, **kwargs):
        super().__init__(**kwargs)
        self._width = width
        self._driver: Logic | None = None
    
    def graph_bw(self, graph: Digraph, fr: Logic | None = None):
        if self._driver is not None:
            self._driver.graph_bw(graph, fr)
        elif fr is not None:
            connect_edge(self, fr, graph)
        else:
            graph.node(self.node_name())

    def count_logic_instances(self, visited: set[int] | None = None) -> int:
        if visited is None:
            visited = set()
        visited.add(id(self))
        return super().count_logic_instances(visited)

    def set_driver(self, driver: Logic):
        self._driver = driver
    
    def remove_driver(self):
        self._driver = None
    
    def has_driver(self) -> bool:
        return self._driver is not None
    
    def width(self):
        return self._width
    
    def _eval_impl(self):
        assert self._driver is not None, \
            "tried to eval port which is not connected"
        return self._driver.eval()

    def __repr__(self) -> str:
        return f"Port({self._width}{self._name_repr()})"

class Not(Logic):
    def __init__(self, inp: Logic, **kwargs):
        super().__init__(**kwargs)
        self._inp = inp

        self._register_con(self._inp, self)
    
    def width(self):
        return self._inp.width()
    
    def _eval_impl(self):
        inverted = [(not b) for b in self._inp.eval().as_bitarray()]
        return Bits(len(inverted), inverted)
    
    def __repr__(self) -> str:
        return f"Not({repr(self._inp)}{self._name_repr()})"

class Comb(Logic):
    OPERATORS = ["XNOR", "AND", "OR", "XOR", "NAND", "NOR"]
    def __init__(self, var: str, *inputs: Logic, **kwargs):
        super().__init__(**kwargs)
        self._var = var
        self._inputs = inputs

        for inp in self._inputs:
            Logic._register_con(inp, self)

        assert len(self._inputs) > 0
        if len(self._inputs) > 1 and not all(i.width() == 1 for i in self._inputs):
            raise ValueError("multi-input logic needs to be one bit each for combinator")
        assert self._var.upper() in Comb.OPERATORS
    
    def node_name(self):
        return super().node_name() + f"({self._var})"
    
    def width(self):
        return 1
    
    def count_logic_instances(self, visited: set[int] | None = None) -> int:
        import math
        self_id = id(self)
        approx = sum(8**i for i in range(math.ceil(math.log2(len(self._inputs)) / 3)))
        if visited is None:
            visited = set()
            visited.add(self_id)
            this = approx
        elif self_id not in visited:
            visited.add(self_id)
            this =  approx
        else:
            this = 0
        return this + sum(sublog.count_logic_instances(visited) for sublog in self._bw_con)
    
    def _eval_impl(self):
        inputs = [l.eval() for l in self._inputs]
        if len(inputs) == 1:
            bits = inputs[0].as_bitarray()
        else:
            bits = [i.as_bitarray()[0] for i in inputs]
        match self._var:
            case "XNOR":
                prev = None
                for b in bits:
                    if prev is None:
                        prev = b
                    elif prev != b:
                        return Bits(1, [False])
                return Bits(1, [True])
            case "AND":
                for b in bits:
                    if not b:
                        return Bits(1, [False])
                return Bits(1, [True])
            case "OR":
                for b in bits:
                    if b:
                        return Bits(1, [True])
                return Bits(1, [False])
            case _:
                raise RuntimeError(f"unimplemented type {self._var}")
        assert False

    def __repr__(self) -> str:
        return f"Comb({repr(self._var)}, {', '.join(map(repr, self._inputs))}{self._name_repr()})"


class DFlipFlop(Logic):
    def __init__(self, input: Logic, clk: Logic, **kwargs):
        super().__init__(**kwargs)
        assert clk.width() == 1
        self._clk = clk
        self._input = input
        self._low = True
        warn_once("initializing FlipFlops with default values")
        self._val = Bits(self._input.width(), [False for _ in range(self._input.width())])

        Logic._register_con(input, self)
        Logic._register_con(clk, self)
    
    def count_logic_instances(self, visited: set[int] | None = None) -> int:
        if visited is None:
            visited = set()
        visited.add(id(self))
        return super().count_logic_instances(visited)

    def graph_bw(self, graph, fr = None):
        graph.node(self.node_name(), shape="box")
        return super().graph_bw(graph, fr)
    
    def width(self) -> int:
        return self._input.width()
    
    def _eval_impl(self) -> Bits:
        # Force cache both inputs
        self._clk.eval()
        self._input.eval()

        # use old
        return self._val.eval()
    
    def commit(self):
        clk = self._clk.eval()
        inp = self._input.eval()

        if clk.as_bitarray()[0] and self._low:
            self._low = False
            self._val = inp
        elif not clk.as_bitarray()[0] and not self._low:
            self._low = True
        
        self.signal_event(self._val)
    
    def __repr__(self) -> str:
        return f"DFlipFlop({repr(self._input)}, {repr(self._clk)}{self._name_repr()})"

class MLUTN(Logic):
    def __init__(self, n: int, rules: Callable[[Bits], Bits], *inp: Logic, **kwargs):
        super().__init__(**kwargs)
        self._m = len(inp)
        self._inp = inp
        self._n = n

        for i in inp:
            self._register_con(i, self)

        self._table: dict[tuple[bool, ...], Bits] = {
            pat: rules(Bits(len(pat), list(pat)))
            for pat in (
                tuple(bool((idx >> i) & 1) for i in range(8))
                for idx in range(2**self._m)
            )
        }

        assert all(b._value is not None and len(b._value) == self._n for b in self._table.values())

    def _eval_impl(self):
        inp = Bits(self._m, [i.eval().as_bitarray()[0] for i in self._inp])
        return self._table[tuple(inp.as_bitarray())]
    
    def width(self):
        return self._n
    
    def __repr__(self) -> str:
        return f"MLUTN({self._m}, {self._n}, {repr(self._inp)}, <ruleset>{self._name_repr()})"

            
class Component:
    def __init__(self, outputs: list[Logic], inputs: list[Logic]):
        self._inputs = inputs
        self._outputs = outputs
    
    def get_porti(self, name: str) -> Port:
        logic = self.by_namei(name)
        if not isinstance(logic, Port):
            raise ValueError(\
                f"another logic component with the name {name} was found instead of port")
        return logic

    def by_namei(self, name: str) -> Logic:
        for inp in self._inputs:
            if inp.has_name() and inp.get_name() == name:
                return inp
        raise KeyError(f"logic by name \'{name}\' does not exist")
    
    def find_logic(self, pattern: str) -> tuple[str, Logic]:
        matches = []
        for log in [*self._inputs, *self._outputs]:
            if log.has_name() and (name := log.get_name()).endswith(pattern):
                matches.append((name, log))
        assert len(matches) > 0, \
            f"no match found for pattern {pattern}"
        assert len(matches) == 1, \
            f"multiple matches found for pattern {pattern}"
        
        return matches[0]

    def get_outputs(self) -> list[Logic] :
        return self._outputs
    
    def get_inputs(self, skip_clk: bool = True) -> list[Logic]:
        return list(i for i in self._inputs if not skip_clk or not i.is_clk())

    def eval_all(self) -> list[Bits]:
        return [out.eval() for out in self._outputs]
