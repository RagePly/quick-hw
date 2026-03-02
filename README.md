# Quick HW

An RTL library.

This library was written as part of a master's course on reconfigurable computing and 
aids in algorithmically crafting clock gated VHDL components.

Design utilities as well as a primitive functional simulator is included in 
[quick_hw.py](./quick_hw.py), with VHDL component creation in [vhdl_renderer.py](./vhdl_renderer.py).

## Example application

[dcam.py](./dcam.py) is an implementation for a pipelined, parallel, string pattern matcher
based on pre-decoded content addressable memory [^1].

[^1]: Sourdis, I. (2007). Designs and algorithms for packet and content inspection.
