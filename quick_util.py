from io import StringIO 
from sys import stderr
_WARNINGS: set[str] = set()

def warn_once(*args, **kwargs):
    assert "file" not in kwargs
    assert "end" not in kwargs or kwargs["end"].endswith("\n")

    sio = StringIO()
    print("WARNING: ", *args, **kwargs, file=sio)
    
    s = sio.getvalue()
    if s in _WARNINGS:
        return
    _WARNINGS.add(s)

    print(s, end="", file=stderr)

if __name__ == "__main__":
    warn_once("Test 1", "this is first")
    warn_once("Test 2", "this is second")
    warn_once("Test 1", "this is first")

