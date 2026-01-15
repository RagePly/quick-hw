from typing import NoReturn, Iterable
from quick_hw import *
from dataclasses import dataclass
from math import log2, ceil
from itertools import product
from collections import deque

def topo_sort(deps: dict[str, set[str]]) -> list[str]:
    # Not my solution, Ai-generated

    # All nodes (including ones that only appear as dependencies)
    nodes = set(deps) | {d for ds in deps.values() for d in ds}

    # In-degree count
    indeg = {n: 0 for n in nodes}
    for n, ds in deps.items():
        for _ in ds:
            indeg[n] += 1

    # Start with nodes that have no dependencies
    queue = deque(n for n in nodes if indeg[n] == 0)
    order = []

    while queue:
        n = queue.popleft()
        order.append(n)

        for m, ds in deps.items():
            if n in ds:
                indeg[m] -= 1
                if indeg[m] == 0:
                    queue.append(m)

    return [name for name in order if name in deps]


def set_join[T](i: Iterable[set[T]]) -> set[T]:
    s = set()
    for si in i:
        s.update(si)
    return s

def todo(s: str | None = None) -> NoReturn:
    if s is not None:
        raise Exception(f"not implemted: {s}")
    raise Exception(f"not implemted")

def unreachable(s: str | None = None) -> NoReturn:
    if s is not None:
        raise Exception(f"unreachable: {s}")
    raise Exception(f"unreachable")

def logic_vector(width: int) -> str:
    if width == 1:
        return "std_logic"
    return f"std_logic_vector({width-1} downto 0)"

class Work:
    ...

@dataclass
class Assignment(Work):
    name: str
    expr: Logic

@dataclass
class RisingEdgeAssign(Work):
    name: str
    expr: Logic

@dataclass
class Constant(Work):
    name: str
    data: list[bool]

@dataclass
class Input(Work):
    name: str
    width: int

@dataclass
class Output(Work):
    name: str
    expr: Logic

@dataclass
class AssignmentMux(Work):
    name: str
    expr: Mux
    sel: tuple[str, int]


class VHDLRenderer:
    def __init__(self, entity_name: str):
        self._signals: dict[str, int] = {}
        self._ports: dict[str, tuple[int, bool]] = {}
        self._constants: dict[str, list[bool]] = {}
        self._depends: dict[str, set[str]] = {}
        self._assignments: dict[str, str] = {}
        self._clk_assignments: dict[str, str] = {}
        self._work_stack: list[Work] = []
        self._sio: StringIO | None = None
        self._entity_name = entity_name
        self._dependency_cache: dict[str, set[str]] = {}
    

        self._iota_n = 0
    def _begin_render(self):
        assert self._sio is None
        self._sio = StringIO()
    
    def _end_render(self) -> str:
        assert self._sio is not None
        s = self._sio.getvalue()
        self._sio = None
        return s

    def _print(self, *args: object, end="\n"):
        print(*args, end=end, file=self._sio)

    def _iota(self) -> int:
        i = self._iota_n
        self._iota_n += 1
        return i

    def feed_assignment(self, dest: str, expr: Logic):
        self._work_stack.append(Assignment(dest, expr))    
    
    def feed_output(self, name: str, expr: Logic):
        assert ":" not in name, "invalid name"
        self._work_stack.append(Output(name, expr))
    
    def process(self):
        while len(self._work_stack) > 0:
            top = self._work_stack.pop()

            match top:
                case Assignment(name, expr):
                    if name in self._assignments:
                        continue

                    assert name not in self._assignments
                    assert name not in self._depends
                    assert name not in self._signals
                    self._depends[name] = self._get_dependencies(expr)
                    self._signals[name] = expr.width()
                    self._assignments[name] = self._render_expr(expr)
                    continue

                case Constant(name, data):
                    assert name not in self._constants
                    assert len(data) >= 1
                    self._constants[name] = data
                    continue

                case Output(name, expr):
                    assert name not in self._assignments
                    assert name not in self._depends
                    assert name not in self._ports
                    self._ports[name] = (expr.width(), False)
                    self._depends[name] = self._get_dependencies(expr)
                    self._assignments[name] = self._render_expr(expr)
                    continue

                case Input(name, width):
                    if name in self._ports:
                        continue
                    self._ports[name] = (width, True)
                    continue

                case RisingEdgeAssign(name, expr):
                    if name in self._clk_assignments:
                        continue
                    assert name not in self._assignments
                    assert name not in self._depends
                    assert name not in self._signals

                    self._work_stack.append(Input("clk", 1))
                    self._work_stack.append(Input("ce", 1))
                    # self._work_stack.append(Input("resetclk", 1))
                    self._clk_assignments[name] = self._render_expr(expr)
                    self._signals[name] = expr.width()
                    self._depends[name] = self._get_dependencies(expr)
                    continue
                    
                case AssignmentMux(name, mux, (sel_name, sel_width)):
                    assert name not in self._assignments
                    assert name not in self._depends
                    assert name not in self._signals


                    selector_literals = [f'"{''.join(i)}"' for i in product("01", repeat=sel_width)]
                    assert len(selector_literals) >= len(mux._inp)
                    parts = []
                    for i, (inp, sel) in enumerate(zip(mux._inp, selector_literals)):
                        if i + 1 == len(mux._inp):
                            parts.append(self._render_expr(inp))
                        else:
                            parts.append(f"{self._render_expr(inp)} when {sel_name} = {sel}")
                    self._assignments[name] = " else ".join(parts)
                    self._depends[name] = self._get_dependencies(mux._sel) | set_join(self._get_dependencies(i) for i in mux._inp)
                    self._signals[name] = mux.width()
                    continue
                case _:
                    todo(f"{top}")
    
    def _render_imports(self):
        self._print("library ieee;")
        self._print("use ieee.std_logic_1164.all;")
        self._print("use ieee.numeric_std.all;")

    def _render_entity(self):
        self._print(f"entity {self._entity_name} is")
        self._print(f"\tport(")
        is_first = True
        for name, (width, is_input) in self._ports.items():
            if not is_first:
                self._print(";")
            is_first = False
            self._print(f"\t\t{name} : {'in' if is_input else 'out'} {logic_vector(width)}", end="")
        self._print(f"\n\t);")
        self._print(f"end entity;")
    
    def _render_architecture_header(self):
        self._print(f"architecture dataflow of {self._entity_name} is")

        for name, width in self._signals.items():
            self._print(f"\tsignal {name} : {logic_vector(width)};")
        
        self._print()

        for name, data in self._constants.items():
            if len(data) == 1:
                self._print(f"\tconstant {name} : std_logic := '{int(data[0])}';")
            else:
                literal = "".join(map(str, map(int, data)))
                self._print(f"\tconstant {name} : {logic_vector(len(data))} := {literal};");
        self._print("begin")
    
    def _render_architecture_end(self):
        self._print("end architecture;")
    
    def _render_architecture_body(self):

        # NOTE: might not be necessary
        ordered_assignments = topo_sort(self._depends)

        # Dataflow assignments
        for target in ordered_assignments:
            if target in self._assignments:
                self._print(f"\t{target} <= {self._assignments[target]};") 

        # Rising-edge (D-flip-flop)
        self._print("\tprocess(clk)")
        self._print("\tbegin")
        # self._print("\t\t if resetclk /= '1' then")
        # for target in ordered_assignments:
        #     if target in self._clk_assignments:
        #         if self._signals[target] == 1:
        #             self._print(f"\t\t\t{target} <= '0';")
        #         else:
        #             self._print(f"\t\t\t{target} <= (others => '0');") 
        # self._print("\t\t elsif rising_edge(clk) then")
        self._print("\t\tif rising_edge(clk) then")
        self._print("\t\t\tif ce = '1' then")
        for target in ordered_assignments:
            if target in self._clk_assignments:
                self._print(f"\t\t\t\t{target} <= {self._clk_assignments[target]};") 
        self._print("\t\t\tend if;")
        self._print("\t\t end if;")
        self._print("\tend process;")

    def _render_script_notion(self):
        import datetime
        self._print(f"-- Generated by {__file__} on {datetime.datetime.today().ctime()}")

    def render(self) -> str:
        self._begin_render()
        self._render_script_notion()
        self._render_imports()
        self._render_entity()
        self._render_architecture_header()
        self._render_architecture_body()
        self._render_architecture_end()

        return self._end_render()
    
    def _get_name(self, logic: Logic):
        if logic._name is None:
            if logic._system_id is None:
                return f"r_anon_{self._iota()}"
            else:
                return f"r_sid_{logic._system_id}"
        return f"r_{logic._name.replace(":", "_")}"

    def _render_expr(self, log: Logic) -> str:
        operators = {
            "AND": "and",
            "OR": "or",
            "XNOR": "xnor"
        }
        match log:
            case Comb() as c:
                oper = operators[c._var]
                return "(" + (" " + oper + " ").join(self._render_expr(inp) for inp in log._inputs) + ")"
            case Bits() as b:
                name = self._get_name(b)
                self._work_stack.append(Constant(name, b.as_bitarray()))
                return name
            case DFlipFlop() as dff:
                name = self._get_name(dff)
                self._work_stack.append(RisingEdgeAssign(name, dff._input))
                return name
            case Port() as port:
                if port._driver is None:
                    port_name = self._get_name(port)
                    self._work_stack.append(Input(port_name, port.width()))
                    return port_name
                return self._render_expr(port._driver)
            case Wire() as wire:
                inp = wire._inp
                inp_name = self._get_name(inp) + "_wire"
                self._work_stack.append(Assignment(inp_name, wire._inp));
                return f"{inp_name}({wire._index})"
            case Vector() as vector:
                return "(" + " & ".join(self._render_expr(e) for e in reversed(vector._inp)) + ")"
            case Mux() as mux:
                sel_width = ceil(log2(len(mux._inp)))
                assert mux._sel.width() == sel_width

                sel_name = self._get_name(mux._sel)
                self._work_stack.append(Assignment(sel_name, mux._sel))

                mux_name = self._get_name(mux)
                self._work_stack.append(AssignmentMux(mux_name, mux, (sel_name, sel_width)))

                return mux_name 
            case Not() as n:
                return f"(not {self._render_expr(n._inp)})"
            case _:
                todo(f"render {log}")
    
    def _get_dependencies(self, expr: Logic) -> set[str]:
        expr_name = self._get_name(expr)

        if expr_name in self._dependency_cache:
            return self._dependency_cache[expr_name]
        
        deps = set()
        match expr:
            case Comb() as c:
                deps = set_join(self._get_dependencies(arg) for arg in c._inputs)
            case Bits() as b:
                deps = set([self._get_name(b)])
            case DFlipFlop() as dff:
                deps = self._get_dependencies(dff._input) | set([self._get_name(dff)])
            case Port() as port:
                if port._driver is None:
                    deps = set([self._get_name(port)])
                else:
                    deps = set(self._get_dependencies(port._driver))
            case Wire() as wire:
                deps = set(self._get_dependencies(wire._inp))
            case Vector() as vector:
                deps = set_join(self._get_dependencies(arg) for arg in vector._inp)
            case Mux() as mux:
                deps = self._get_dependencies(mux._sel) | set_join(self._get_dependencies(i) for i in mux._inp) | set([self._get_name(mux), self._get_name(mux._sel)])
            case Not() as n:
                deps = set(self._get_dependencies(n._inp))
            case _:
                todo(f"{expr}")

        self._dependency_cache[expr_name] = deps
        return deps

