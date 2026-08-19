"""Patch pyrtlsdr/librtlsdr.py to wrap missing symbols in try/except.

pyrtlsdr 0.5.0 references symbols (dithering, GPIO) that are absent in
librtlsdr 2.0.1 shipped with Ubuntu 24.04.  This script makes those
bindings optional so the import does not crash.
"""

import pathlib
import sys

MISSING_SYMBOLS = [
    "rtlsdr_set_dithering",
    "rtlsdr_set_gpio_output",
    "rtlsdr_set_gpio_input",
    "rtlsdr_set_gpio_bit",
    "rtlsdr_get_gpio_bit",
    "rtlsdr_set_gpio_byte",
    "rtlsdr_get_gpio_byte",
    "rtlsdr_set_gpio_status",
]


def find_librtlsdr() -> pathlib.Path:
    search_roots = [pathlib.Path("/usr/local/lib"), pathlib.Path("/usr/lib")]
    # Also search the current Python's site-packages
    import site
    for sp in site.getsitepackages():
        search_roots.append(pathlib.Path(sp))
    # Deduplicate while preserving order
    seen = set()
    unique = []
    for r in search_roots:
        r = r.resolve()
        if r not in seen:
            seen.add(r)
            unique.append(r)
    for base in unique:
        for p in base.rglob("rtlsdr/librtlsdr.py"):
            return p
    sys.exit("ERROR: rtlsdr/librtlsdr.py not found")


def patch(text: str) -> str:
    for sym in MISSING_SYMBOLS:
        target = f"f = librtlsdr.{sym}"
        # already patched?
        if f"try:\n    {target}" in text:
            continue
        if target not in text:
            continue
        # find the two-line block:  f = librtlsdr.XX\nf.restype, f.argtypes = ...
        idx = text.index(target)
        line_end = text.index("\n", idx) + 1
        restype_line_end = text.index("\n", line_end) + 1
        block = text[idx:restype_line_end]
        indent = "    "
        indented_block = "".join(indent + line for line in block.splitlines(True))
        wrapped = f"try:\n{indented_block}except AttributeError:\n{indent}pass\n"
        text = text[:idx] + wrapped + text[restype_line_end:]
    return text


def main() -> None:
    path = find_librtlsdr()
    original = path.read_text()
    patched = patch(original)
    if patched == original:
        print(f"Already patched: {path}")
    else:
        path.write_text(patched)
        print(f"Patched: {path}")


if __name__ == "__main__":
    main()
