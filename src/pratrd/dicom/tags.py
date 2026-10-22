"""Compact, UI-friendly dump of a DICOM header (for the tag browser)."""

from typing import Any

from pydicom.dataelem import DataElement
from pydicom.dataset import Dataset

_MAX_VALUE = 240
_MAX_DEPTH = 3
_MAX_ITEMS = 20  # per sequence; enhanced multi-frame has one item per frame


def _value(elem: DataElement) -> str:
    if elem.VR in ("OB", "OW", "OF", "OD", "OL", "OV", "UN"):
        n = len(elem.value) if elem.value is not None else 0
        return f"<binarne, {n} B>"
    v = elem.value
    s = "\\".join(str(x) for x in v) if isinstance(v, (list, tuple)) or elem.VM > 1 else str(v)
    return s if len(s) <= _MAX_VALUE else s[: _MAX_VALUE - 1] + "…"


def dump(ds: Dataset, depth: int = 0) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for elem in ds:
        if elem.tag == 0x7FE00010:  # PixelData
            continue
        row: dict[str, Any] = {
            "tag": f"{elem.tag.group:04X},{elem.tag.element:04X}",
            "name": elem.keyword or elem.name,
            "vr": elem.VR,
            "depth": depth,
        }
        if elem.VR == "SQ":
            row["value"] = f"[{len(elem.value)} elem.]"
            rows.append(row)
            if depth < _MAX_DEPTH:
                for n, item in enumerate(elem.value[:_MAX_ITEMS]):
                    rows.append(
                        {
                            "tag": "",
                            "name": f"Element {n + 1}",
                            "vr": "",
                            "value": "",
                            "depth": depth + 1,
                        }
                    )
                    rows.extend(dump(item, depth + 2))
                if len(elem.value) > _MAX_ITEMS:
                    rows.append(
                        {
                            "tag": "",
                            "name": f"… i {len(elem.value) - _MAX_ITEMS} więcej",
                            "vr": "",
                            "value": "",
                            "depth": depth + 1,
                        }
                    )
        else:
            row["value"] = _value(elem)
            rows.append(row)
    return rows
