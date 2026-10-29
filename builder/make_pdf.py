"""Dependency-free PDF generator for the 'wkład własny' (own-contribution) report.

Builds a multi-page A4 PDF with wrapped text lines (Helvetica), from a list of
(style, text) blocks. No third-party libraries.
"""

from __future__ import annotations

import zlib
from pathlib import Path

PAGE_W, PAGE_H = 595, 842  # A4 in points
MARGIN = 54
SIZES = {"h1": 20, "h2": 14, "p": 10.5, "small": 9}
LEADING = {"h1": 26, "h2": 20, "p": 15, "small": 13}

# Polish glyphs are not in WinAnsi; map each to a free byte code + Adobe glyph name
# and declare them via the font's /Encoding /Differences.
POLISH = {
    "ą": (0x80, "aogonek"), "ć": (0x81, "cacute"), "ę": (0x82, "eogonek"),
    "ł": (0x83, "lslash"), "ń": (0x84, "nacute"), "ó": (0x85, "oacute"),
    "ś": (0x86, "sacute"), "ź": (0x87, "zacute"), "ż": (0x88, "zdotaccent"),
    "Ą": (0x89, "Aogonek"), "Ć": (0x8A, "Cacute"), "Ę": (0x8B, "Eogonek"),
    "Ł": (0x8C, "Lslash"), "Ń": (0x8D, "Nacute"), "Ó": (0x8E, "Oacute"),
    "Ś": (0x8F, "Sacute"), "Ź": (0x90, "Zacute"), "Ż": (0x91, "Zdotaccent"),
}


def _differences() -> str:
    parts = []
    for _, (code, name) in sorted(POLISH.items(), key=lambda kv: kv[1][0]):
        parts.append(f"{code} /{name}")
    return "[ " + " ".join(parts) + " ]"


def encode_stream(s: str) -> bytes:
    out = bytearray()
    for ch in s:
        if ch in POLISH:
            out.append(POLISH[ch][0])
        elif ord(ch) < 256:
            out.append(ord(ch))
        else:
            out.append(ord("?"))
    return bytes(out)


def _esc(s: str) -> str:
    return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _wrap(text: str, size: float, max_w: float) -> list[str]:
    max_chars = max(8, int(max_w / (size * 0.52)))
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        if len(cur) + len(w) + 1 <= max_chars:
            cur = f"{cur} {w}".strip()
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or [""]


def build_pdf(blocks: list[tuple[str, str]], path: str | Path) -> Path:
    # Lay out into pages of content streams.
    pages: list[str] = []
    y = PAGE_H - MARGIN
    parts: list[str] = []

    def flush() -> None:
        if parts:
            pages.append("".join(parts))

    for style, text in blocks:
        size = SIZES.get(style, SIZES["p"])
        lead = LEADING.get(style, LEADING["p"])
        for line in _wrap(text, size, PAGE_W - 2 * MARGIN):
            if y < MARGIN + lead:
                flush()
                parts = []
                y = PAGE_H - MARGIN
            parts.append(
                f"BT /F1 {size} Tf {MARGIN} {y:.1f} Td ({_esc(line)}) Tj ET\n"
            )
            y -= lead
        y -= 4  # paragraph spacing
    flush()
    if not pages:
        pages = [""]

    # Assemble PDF objects.
    objs: list[bytes] = []

    def add(obj: bytes) -> int:
        objs.append(obj)
        return len(objs)

    enc_id = add(
        ("<< /Type /Encoding /BaseEncoding /WinAnsiEncoding /Differences "
         + _differences() + " >>").encode()
    )
    font_id = add(
        ("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding %d 0 R >>" % enc_id).encode()
    )
    page_ids: list[int] = []
    content_ids: list[int] = []
    for stream in pages:
        data = zlib.compress(encode_stream(stream))
        cid = add(
            b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(data) + data + b"\nendstream"
        )
        content_ids.append(cid)
    parent_placeholder = len(objs) + len(pages) + 1  # pages tree id (set after)
    for cid in content_ids:
        pid = add(
            (
                "<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %d %d] "
                "/Resources << /Font << /F1 %d 0 R >> >> /Contents %d 0 R >>"
                % (parent_placeholder, PAGE_W, PAGE_H, font_id, cid)
            ).encode()
        )
        page_ids.append(pid)
    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    pages_id = add(f"<< /Type /Pages /Count {len(page_ids)} /Kids [{kids}] >>".encode())
    catalog_id = add(f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode())

    # Serialize with xref.
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, obj in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objs) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objs) + 1} /Root {catalog_id} 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF"
    ).encode()
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(bytes(out))
    return p


if __name__ == "__main__":
    import sys

    build_pdf([("h1", "Test"), ("p", "Zawartość testowa.")], sys.argv[1] if len(sys.argv) > 1 else "test.pdf")
