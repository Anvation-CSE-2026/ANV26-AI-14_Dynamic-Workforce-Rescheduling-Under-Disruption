"""Minimal, dependency-free .xlsx reading and writing (Office Open XML, first sheet).

Enough for import templates, imported rosters and the one-time temporary-password export, without
asking every deployment to install openpyxl. Cells are written as inline strings or numbers; reading
understands shared strings, inline strings, numbers and booleans. Excel serial dates/times are
converted by the importers that expect them (see ``excel_date`` / ``excel_time``).
"""

from __future__ import annotations

import io
import re
import zipfile
from datetime import date as Date, timedelta
from typing import Any, Iterable
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


class XlsxError(ValueError):
    pass


def _col(n: int) -> str:
    s = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _cell(ref: str, v: Any) -> str:
    if v is None or v == "":
        return ""
    if isinstance(v, bool):
        return f'<c r="{ref}" t="b"><v>{int(v)}</v></c>'
    if isinstance(v, (int, float)):
        return f'<c r="{ref}"><v>{v}</v></c>'
    text = escape(str(v))
    space = ' xml:space="preserve"' if text != text.strip() else ""
    return f'<c r="{ref}" t="inlineStr"><is><t{space}>{text}</t></is></c>'


def write(rows: Iterable[Iterable[Any]], sheet_name: str = "Sheet1") -> bytes:
    """One-sheet workbook; the first row is styled as a bold header."""
    body = []
    for r, row in enumerate(rows):
        cells = "".join(_cell(f"{_col(c)}{r + 1}", v) for c, v in enumerate(row))
        style = ' s="1"' if r == 0 else ""
        body.append(f'<row r="{r + 1}">{cells.replace("<c ", f"<c{style} ") if style else cells}</row>')
    sheet = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
             f'<sheetData>{"".join(body)}</sheetData></worksheet>')
    name = escape(sheet_name[:31])
    files = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            '</Types>'),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '</Relationships>'),
        "xl/workbook.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f'<sheets><sheet name="{name}" sheetId="1" r:id="rId1"/></sheets></workbook>'),
        "xl/_rels/workbook.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            '</Relationships>'),
        "xl/styles.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
            '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
            '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
            '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
            '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
            '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
            '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>'
            '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
            '</styleSheet>'),
        "xl/worksheets/sheet1.xml": sheet,
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for path, xml in files.items():
            z.writestr(path, xml)
    return buf.getvalue()


def _ref_col(ref: str) -> int:
    letters = re.match(r"[A-Z]+", ref or "A")
    n = 0
    for ch in letters.group(0) if letters else "A":
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def read(data: bytes) -> list[list[Any]]:
    """Rows of the first worksheet (values only)."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise XlsxError("Not a valid .xlsx file") from exc
    names = set(z.namelist())
    shared: list[str] = []
    if "xl/sharedStrings.xml" in names:
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
        for si in root.iter(f"{_NS}si"):
            shared.append("".join(t.text or "" for t in si.iter(f"{_NS}t")))
    sheet_path = "xl/worksheets/sheet1.xml"
    if "xl/workbook.xml" in names and "xl/_rels/workbook.xml.rels" in names:
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        first = next(wb.iter(f"{_NS}sheet"), None)
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        if first is not None:
            rid = first.get(f"{_REL}id")
            for rel in rels:
                if rel.get("Id") == rid:
                    target = rel.get("Target", "")
                    sheet_path = target.lstrip("/") if target.startswith("/") else "xl/" + target
    if sheet_path not in names:
        raise XlsxError("The workbook has no worksheet")
    root = ET.fromstring(z.read(sheet_path))
    rows: list[list[Any]] = []
    for row in root.iter(f"{_NS}row"):
        values: dict[int, Any] = {}
        for c in row.iter(f"{_NS}c"):
            t, v = c.get("t"), c.find(f"{_NS}v")
            if t == "inlineStr":
                val: Any = "".join(x.text or "" for x in c.iter(f"{_NS}t"))
            elif v is None or v.text is None:
                continue
            elif t == "s":
                val = shared[int(v.text)]
            elif t == "b":
                val = v.text == "1"
            elif t in ("str", "e"):
                val = v.text
            else:
                f = float(v.text)
                val = int(f) if f.is_integer() else f
            values[_ref_col(c.get("r", ""))] = val
        if values:
            width = max(values) + 1
            rows.append([values.get(i, "") for i in range(width)])
        else:
            rows.append([])
    return rows


def excel_date(v: Any) -> Any:
    """Excel serial day number → YYYY-MM-DD (other values unchanged)."""
    if isinstance(v, (int, float)) and not isinstance(v, bool) and 1 <= v < 100000:
        return (Date(1899, 12, 30) + timedelta(days=int(v))).isoformat()
    return v


def excel_time(v: Any) -> Any:
    """Excel time fraction → HH:MM (24-hour)."""
    if isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v < 1:
        minutes = int(round(v * 24 * 60)) % (24 * 60)
        return f"{minutes // 60:02d}:{minutes % 60:02d}"
    return v


def records(data: bytes) -> list[dict[str, Any]]:
    """First row = headers (lower-cased, trimmed); later rows → dicts. Empty rows are kept as {} so
    row numbers stay correct for error messages."""
    rows = read(data)
    if not rows:
        return []
    headers = [str(h).strip().lower() for h in rows[0]]
    out = []
    for r in rows[1:]:
        out.append({h: (r[i] if i < len(r) else "") for i, h in enumerate(headers) if h})
    return out
