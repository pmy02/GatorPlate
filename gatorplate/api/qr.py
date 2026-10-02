"""QR codes as server-side SVG (segno, error level M, quiet zone of 4 modules); no client library, no network."""

from __future__ import annotations

import io

import segno


def qr_svg(url: str) -> bytes:
    code = segno.make(url, error="m", micro=False)
    buffer = io.BytesIO()
    code.save(buffer, kind="svg", scale=8, border=4, xmldecl=False, dark="#000", light="#fff",
              title="QR code")
    return buffer.getvalue()
