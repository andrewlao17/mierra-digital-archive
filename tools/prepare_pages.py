#!/usr/bin/env python3
"""Turn pages of a scanned PDF into web-sized page images for one document.

Usage (from the repository root):

    python3 tools/prepare_pages.py SCAN.pdf JP-001 12-15
    python3 tools/prepare_pages.py SCAN.pdf JP-001 12-15 --numbers 3-6

This writes facsimiles/JP-001/1.jpg, 2.jpg, ... (one per PDF page, in order) and
prints the <facsimile> block and the matching <pb/> lines to paste into
tei/JP-001.xml. --numbers sets the page numbers printed in the book (n="...")
when they differ from the PDF page numbers.

Images are scaled to at most 1600 px on the long side and saved as JPEG at
quality 70, which keeps a typical page near 0.2-0.4 MB.

Needs either the `pdftoppm` command (poppler) or the PyMuPDF package
(pip install pymupdf), plus Pillow (pip install pillow).
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

MAX_SIDE = 1600
QUALITY = 70


def page_range(text):
    first, _, last = text.partition("-")
    first, last = int(first), int(last or first)
    if first < 1 or last < first:
        raise argparse.ArgumentTypeError("use a range like 12-15")
    return list(range(first, last + 1))


def render_pages(pdf, pages, workdir):
    """Render the given 1-based PDF pages to PNG files and return their paths."""
    if shutil.which("pdftoppm"):
        out = []
        for p in pages:
            prefix = Path(workdir) / ("p%05d" % p)
            subprocess.run(["pdftoppm", "-r", "150", "-f", str(p), "-l", str(p), "-png", "-singlefile",
                            str(pdf), str(prefix)], check=True)
            out.append(prefix.with_suffix(".png"))
        return out
    try:
        import fitz  # PyMuPDF
    except ImportError:
        sys.exit("Install poppler (for pdftoppm) or run: pip install pymupdf")
    doc = fitz.open(str(pdf))
    out = []
    for p in pages:
        pix = doc[p - 1].get_pixmap(dpi=150)
        path = Path(workdir) / ("p%05d.png" % p)
        pix.save(str(path))
        out.append(path)
    return out


def main():
    ap = argparse.ArgumentParser(description="Prepare page images for one document.")
    ap.add_argument("pdf", type=Path, help="the scanned PDF")
    ap.add_argument("doc_id", help="catalog id, e.g. JP-001 (also the TEI file name)")
    ap.add_argument("pages", type=page_range, help="PDF page range, e.g. 12-15")
    ap.add_argument("--numbers", type=page_range, help="printed page numbers, e.g. 3-6")
    ap.add_argument("--out", type=Path, default=Path("facsimiles"), help="output folder (default: facsimiles)")
    args = ap.parse_args()

    try:
        from PIL import Image
    except ImportError:
        sys.exit("Run: pip install pillow")

    numbers = args.numbers or args.pages
    if len(numbers) != len(args.pages):
        sys.exit("--numbers must cover the same number of pages as the PDF range")

    target = args.out / args.doc_id
    target.mkdir(parents=True, exist_ok=True)

    surfaces, breaks, total = [], [], 0
    with tempfile.TemporaryDirectory() as work:
        for i, png in enumerate(render_pages(args.pdf, args.pages, work), 1):
            img = Image.open(png).convert("RGB")
            img.thumbnail((MAX_SIDE, MAX_SIDE))
            dest = target / ("%d.jpg" % i)
            img.save(dest, "JPEG", quality=QUALITY, optimize=True, progressive=True)
            total += dest.stat().st_size
            n = numbers[i - 1]
            url = "%s/%s/%d.jpg" % (args.out.as_posix().strip("/"), args.doc_id, i)
            surfaces.append('    <surface xml:id="s%d" n="%d"><graphic url="%s"/></surface>' % (i, n, url))
            breaks.append('<pb n="%d" facs="#s%d"/>' % (n, i))

    print("Wrote %d images to %s (%.1f MB)\n" % (len(surfaces), target, total / 1e6))
    print("Paste into tei/%s.xml, after </teiHeader>:\n" % args.doc_id)
    print("  <facsimile>")
    print("\n".join(surfaces))
    print("  </facsimile>\n")
    print("Page breaks to place in the transcription:\n")
    print("\n".join(breaks))


if __name__ == "__main__":
    main()
