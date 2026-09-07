from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise SystemExit(f"marker not found in {path}: {old!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "vehreg/entities.py",
    'class Variant:\n    """One รุ่นย่อย, priced for the catalog year it belongs to."""',
    'class Variant:\n    """One analytical spec line used to classify registration volume.\n\n    This is deliberately not the retail trim list. Multiple marketed grades may\n    fold into one Variant when DLT cannot distinguish them; exact retail grades\n    live in ``MarketTrim``.\n    """',
)
replace_once(
    "vehreg/entities.py",
    '    name: str                                 # trim as marketed, e.g. "1.2 Smart"',
    '    name: str                                 # analytical line, e.g. "1.2 ICE"',
)
replace_once(
    "vehreg/entities.py",
    '    #: Set when the trim exists so a real registration has somewhere to land\n',
    '    #: Set when the analytical spec line exists so a real registration has somewhere to land\n',
)
replace_once(
    "vehreg/entities.py",
    '    #: powertrain, so model-grain volume inherits the consensus of the trims\n    #: the catalog happens to list; that consensus is only trustworthy when\n',
    '    #: powertrain, so model-grain volume inherits the consensus of the analytical\n    #: variants the catalog happens to list; that consensus is only trustworthy when\n',
)
replace_once(
    "vehreg/authoring.py",
    'This module accepts one wide row per รุ่นย่อย\nand builds the brand/model/generation/variant nesting underneath, so the catalog\n',
    'This module accepts one wide row per analytical spec line\nand builds the brand/model/generation/variant nesting underneath, so the catalog\n',
)
