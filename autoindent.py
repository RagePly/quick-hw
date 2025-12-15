from io import StringIO
def autoindent(src: str) -> str:
    depth = 0
    sio = StringIO()

    for line in src.splitlines():
        if line.startswith("END"):
            depth -= 4
        print(" "*depth + line, file=sio)

        if line.startswith("BEGIN"):
            depth += 4
        
        assert depth >= 0
    assert depth == 0, "unbalanced"

    return sio.getvalue()
