"""
PDF English-to-Hebrew Translator
Uses local Ollama translategemma:12b to translate PDF pages while preserving format.
Handles RTL text, preserves equations and figure labels untouched.
"""

import sys
import os
import json
import requests
import fitz  # PyMuPDF
from bidi.algorithm import get_display
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

sys.stdout.reconfigure(encoding="utf-8")


_print_lock = threading.Lock()

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "translategemma:12b"
# Hebrew-capable font on Windows
HEBREW_FONT = "C:/Windows/Fonts/david.ttf"
HEBREW_FONT_BOLD = "C:/Windows/Fonts/davidbd.ttf"
# Font names that indicate equation/math content — never translate these
MATH_FONTS = {"PearsonMATH", "MathematicalPi"}


def translate_text(text: str) -> str:
    """Translate English text to Hebrew using Ollama translategemma:12b."""
    text = text.strip()
    if not text or len(text) < 2:
        return text
    # Skip if it's just numbers/symbols
    if not any(c.isalpha() for c in text):
        return text

    try:
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a professional English-to-Hebrew translator. "
                            "Translate the given English text to Hebrew. "
                            "Output ONLY the Hebrew translation, nothing else. "
                            "Do not explain, do not add notes, do not repeat the original."
                        ),
                    },
                    {"role": "user", "content": text},
                ],
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": max(512, len(text) * 3)},
            },
            timeout=120,
        )
        resp.raise_for_status()
        result = resp.json().get("message", {}).get("content", "").strip()
        # Validate: result must contain Hebrew characters
        if not any("\u0590" <= c <= "\u05FF" for c in result):
            print(f"  [Warning: No Hebrew in response, keeping original]")
            return text
        # Strip any leading/trailing quotes or markers the model may add
        result = result.strip('"\'`')
        return result if result else text
    except Exception as e:
        print(f"  [Translation error: {e}] Keeping original text.")
        return text


def _block_has_math_font(block):
    """Check if a text block contains math/equation font spans."""
    for line in block["lines"]:
        for span in line["spans"]:
            if any(mf in span["font"] for mf in MATH_FONTS):
                return True
    return False


def _block_alpha_count(block):
    """Count alphabetic chars in non-math-font spans of a block."""
    count = 0
    for line in block["lines"]:
        for span in line["spans"]:
            if not any(mf in span["font"] for mf in MATH_FONTS):
                count += sum(1 for c in span["text"] if c.isalpha())
    return count


def _block_full_text(block):
    """Get all text in a block concatenated."""
    parts = []
    for line in block["lines"]:
        for span in line["spans"]:
            if span["text"].strip():
                parts.append(span["text"].strip())
    return " ".join(parts)


def wrap_hebrew_text(text, font, fontsize, max_width):
    """Word-wrap Hebrew text (logical order) into lines fitting max_width."""
    words = text.split()
    if not words:
        return [text]

    lines = []
    current = words[0]

    for word in words[1:]:
        test = current + " " + word
        if font.text_length(test, fontsize=fontsize) <= max_width:
            current = test
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _tprint(*args, **kwargs):
    """Thread-safe print."""
    with _print_lock:
        print(*args, **kwargs)


def translate_page(page: fitz.Page, page_num: int):
    """Translate text on a page from English to Hebrew, preserving equations and layout."""
    _tprint(f"Processing page {page_num}...")

    text_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
    blocks = text_dict.get("blocks", [])

    # Phase 1: Classify blocks, collect translatable units.
    # Each "unit" = one entire block merged into a single paragraph.
    # This prevents Hebrew text from overflowing into adjacent equation blocks.
    units = []

    for block in blocks:
        if block["type"] != 0:
            continue

        full_text = _block_full_text(block)

        # Skip: empty or no alpha
        if not full_text or not any(c.isalpha() for c in full_text):
            continue

        # Skip: short labels (axis labels like y, S, x, z, v, S')
        if len(full_text.replace(" ", "")) <= 3:
            continue

        # Skip: equation blocks (math fonts) — both pure equations and mixed
        # text+equation blocks. Inline math is interleaved with text on the
        # same lines, so placing Hebrew over them causes visual overlap.
        if _block_has_math_font(block):
            continue
        line_entries = []
        all_spans = []
        for line in block["lines"]:
            lt = ""
            spans = []
            for span in line["spans"]:
                if not span["text"].strip():
                    continue
                lt += span["text"]
                spans.append(span)
            lt_stripped = lt.strip()
            if lt_stripped:
                y_vals = [s["bbox"][1] for s in spans]
                y_top = min(y_vals) if y_vals else 0
                y_bottom = max(s["bbox"][3] for s in spans) if spans else 0
                line_entries.append({
                    "text": lt_stripped,
                    "y_top": y_top,
                    "y_bottom": y_bottom,
                })
                all_spans.extend(spans)

        if not line_entries:
            continue

        # Merge ALL lines in the block into one paragraph (handling hyphenation)
        paragraph = ""
        for entry in line_entries:
            lt = entry["text"]
            if paragraph.endswith("-"):
                paragraph = paragraph[:-1] + lt  # remove hyphen, join
            elif paragraph:
                paragraph += " " + lt
            else:
                paragraph = lt

        if not paragraph.strip() or not any(c.isalpha() for c in paragraph):
            continue

        # Block margins and line positions
        block_x0 = min(s["bbox"][0] for s in all_spans)
        block_x1 = max(s["bbox"][2] for s in all_spans)
        first_span = all_spans[0]

        units.append({
            "text": paragraph.strip(),
            "spans": all_spans,
            "y_tops": [e["y_top"] for e in line_entries],
            "y_bottoms": [e["y_bottom"] for e in line_entries],
            "font_size": first_span["size"],
            "color": first_span.get("color", 0),
            "is_bold": bool(first_span.get("flags", 0) & (2**4)),
            "block_x0": block_x0,
            "block_x1": block_x1,
        })

    if not units:
        _tprint(f"  No translatable text on page {page_num}.")
        return

    # Phase 2: Translate all units
    translations = {}
    for i, unit in enumerate(units):
        ut = unit["text"]
        if ut not in translations:
            _tprint(f"  [p{page_num}] Translating ({i+1}/{len(units)}): "
                  f"{ut[:60]}{'...' if len(ut)>60 else ''}")
            translations[ut] = translate_text(ut)

    # Phase 3: Redact original text for all units
    for unit in units:
        for span in unit["spans"]:
            rect = fitz.Rect(span["bbox"])
            page.add_redact_annot(rect, text="", fill=(1, 1, 1))
    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)

    # Phase 4: Insert translated Hebrew text
    MIN_FONT_SIZE = 6.0

    for unit in units:
        translated = translations.get(unit["text"], unit["text"])
        font_size = unit["font_size"]
        is_bold = unit["is_bold"]
        block_x1 = unit["block_x1"]
        block_x0 = unit["block_x0"]
        block_width = block_x1 - block_x0
        y_tops = unit["y_tops"]
        y_bottoms = unit["y_bottoms"]
        n_available = len(y_tops)  # number of original line slots

        # Convert integer color to RGB tuple
        c = unit["color"]
        r_c = ((c >> 16) & 0xFF) / 255.0
        g_c = ((c >> 8) & 0xFF) / 255.0
        b_c = (c & 0xFF) / 255.0

        font_path = HEBREW_FONT_BOLD if is_bold else HEBREW_FONT
        if not os.path.exists(font_path):
            font_path = HEBREW_FONT
        font = fitz.Font(fontfile=font_path)

        # Word-wrap translation to fit in block width.
        # If wrapped lines exceed available slots, scale font down to fit.
        actual_size = font_size
        wrapped = wrap_hebrew_text(translated, font, actual_size, block_width)

        while len(wrapped) > n_available and actual_size > MIN_FONT_SIZE:
            actual_size *= 0.92
            wrapped = wrap_hebrew_text(translated, font, actual_size, block_width)

        # Hard cap: never exceed available line slots (prevents overlap)
        wrapped = wrapped[:n_available]

        # Compute line spacing from original positions
        if len(y_tops) >= 2:
            line_spacing = (y_tops[-1] - y_tops[0]) / (len(y_tops) - 1)
        else:
            line_spacing = actual_size * 1.2

        # Place each wrapped line at its original y position
        for j, wline in enumerate(wrapped):
            visual = get_display(wline)
            tl = font.text_length(visual, fontsize=actual_size)

            # Right-align to this block's right edge
            x_pos = block_x1 - tl
            if x_pos < 0:
                x_pos = 0

            # Use original line position
            if j < len(y_tops):
                y_pos = y_bottoms[j] - (y_bottoms[j] - y_tops[j]) * 0.15
            else:
                y_pos = y_bottoms[-1] + (j - len(y_tops) + 1) * line_spacing

            tw = fitz.TextWriter(page.rect)
            try:
                tw.append(fitz.Point(x_pos, y_pos), visual,
                          font=font, fontsize=actual_size)
                tw.write_text(page, color=(r_c, g_c, b_c))
            except Exception as e:
                _tprint(f"  [p{page_num} Insert error: {e}]")


def _translate_page_worker(src_pdf_path: str, orig_page_idx: int) -> bytes:
    """Worker function: open source PDF, extract one page, translate it, return PDF bytes.

    Each worker operates on its own fitz.Document — fully thread-safe.
    """
    page_num = orig_page_idx + 1
    doc = fitz.open(src_pdf_path)
    tmp_doc = fitz.open()
    tmp_doc.insert_pdf(doc, from_page=orig_page_idx, to_page=orig_page_idx)
    doc.close()

    translate_page(tmp_doc[0], page_num)

    pdf_bytes = tmp_doc.tobytes(garbage=4, deflate=True)
    tmp_doc.close()
    return pdf_bytes


def parse_page_range(range_str: str, max_pages: int) -> list[int]:
    """Parse page range string like '1-5' or '3,5,7-10' into list of 0-based page indices."""
    pages = set()
    for part in range_str.split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-", 1)
            start = max(1, int(start.strip()))
            end = min(max_pages, int(end.strip()))
            for p in range(start, end + 1):
                pages.add(p - 1)  # convert to 0-based
        else:
            p = int(part.strip())
            if 1 <= p <= max_pages:
                pages.add(p - 1)
    return sorted(pages)


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Translate PDF pages from English to Hebrew.",
        usage="%(prog)s [pdf_path] [page_range] [--workers N]",
    )
    parser.add_argument("pdf_path", nargs="?", default=None, help="Path to source PDF")
    parser.add_argument("page_range", nargs="?", default=None, help="Page range (e.g. 1-5 or 3,7,10-12)")
    parser.add_argument("--workers", "-w", type=int, default=1,
                        help="Number of parallel page workers (default: 1, max recommended: 4)")
    args = parser.parse_args()

    pdf_path = args.pdf_path or input("Enter PDF file name/path: ").strip()
    page_range_str = args.page_range or input("Enter page range (e.g. 1-5 or 3,7,10-12): ").strip()
    num_workers = max(1, args.workers)

    if not os.path.exists(pdf_path):
        # Try in current directory
        alt = os.path.join(os.path.dirname(os.path.abspath(__file__)), pdf_path)
        if os.path.exists(alt):
            pdf_path = alt
        else:
            print(f"Error: File '{pdf_path}' not found.")
            sys.exit(1)

    pdf_path = os.path.abspath(pdf_path)

    # Verify Ollama is running and model is available
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=5)
        models = [m["name"] for m in r.json().get("models", [])]
        if MODEL not in models:
            print(f"Error: Model '{MODEL}' not found in Ollama. Pull it with: ollama pull {MODEL}")
            sys.exit(1)
    except requests.ConnectionError:
        print("Error: Cannot connect to Ollama. Make sure it's running on localhost:11434")
        sys.exit(1)

    # Open PDF to get page count
    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    doc.close()
    print(f"Opened '{pdf_path}' ({total_pages} pages)")

    pages = parse_page_range(page_range_str, total_pages)
    if not pages:
        print("Error: No valid pages in the specified range.")
        sys.exit(1)

    print(f"Will translate pages: {[p+1 for p in pages]}")

    if num_workers > 1 and len(pages) > 1:
        # ── Parallel mode ──
        actual_workers = min(num_workers, len(pages))
        print(f"Using {actual_workers} parallel workers")

        # Each worker opens the PDF independently and translates one page
        results = {}  # page_idx -> pdf_bytes
        with ThreadPoolExecutor(max_workers=actual_workers) as executor:
            future_to_page = {
                executor.submit(_translate_page_worker, pdf_path, page_idx): page_idx
                for page_idx in pages
            }
            for future in as_completed(future_to_page):
                page_idx = future_to_page[future]
                try:
                    results[page_idx] = future.result()
                    _tprint(f"  Page {page_idx + 1} done.")
                except Exception as e:
                    _tprint(f"  ERROR on page {page_idx + 1}: {e}")

        # Merge results in page order
        out_doc = fitz.open()
        for page_idx in pages:
            if page_idx in results:
                tmp = fitz.open("pdf", results[page_idx])
                out_doc.insert_pdf(tmp)
                tmp.close()
            else:
                # Fallback: include original untranslated page
                src = fitz.open(pdf_path)
                out_doc.insert_pdf(src, from_page=page_idx, to_page=page_idx)
                src.close()
    else:
        # ── Sequential mode (original behavior) ──
        doc = fitz.open(pdf_path)
        out_doc = fitz.open()
        for orig_page in pages:
            out_doc.insert_pdf(doc, from_page=orig_page, to_page=orig_page)
        doc.close()

        for i in range(len(out_doc)):
            orig_page_num = pages[i] + 1
            translate_page(out_doc[i], orig_page_num)

    # Save output
    base, ext = os.path.splitext(os.path.basename(pdf_path))
    output_path = os.path.join(
        os.path.dirname(pdf_path),
        f"{base}_hebrew_p{page_range_str.replace(',','_').replace(' ','')}.pdf",
    )

    try:
        out_doc.save(output_path, garbage=4, deflate=True)
    except Exception:
        base_out, ext_out = os.path.splitext(output_path)
        # Try _new, then timestamp fallback
        for suffix in ["_new", f"_{int(__import__('time').time())}"]:
            try:
                output_path = f"{base_out}{suffix}{ext_out}"
                out_doc.save(output_path, garbage=4, deflate=True)
                break
            except Exception:
                continue
    out_doc.close()

    print(f"\nDone! Translated PDF saved to: {output_path}")


if __name__ == "__main__":
    main()
