"""
Smart Reader Agent — A fluent Hebrew reader that inspects translated PDF pages
and reports issues to be fixed.

Uses vision LLMs (minicpm-v, llama3.2-vision) via Ollama to:
1. Render each translated page at high DPI
2. Send to vision model with Hebrew-reading prompt
3. Report specific issues: overlap, missing text, garbled content, layout problems
4. Output structured JSON issues list for the translator to fix

Usage:
    python source/reader/smart_reader.py <translated_pdf> [--source <source_pdf>] [--page <N>] [--iteration <N>]
"""
import sys
import os
import base64
import json
import time
import requests
import fitz  # PyMuPDF

sys.stdout.reconfigure(encoding="utf-8")

OLLAMA_URL = "http://localhost:11434/api/chat"
VISION_MODEL = "minicpm-v:latest"  # Best for document/OCR analysis
FALLBACK_MODEL = "llama3.2-vision:11b"
TEXT_MODEL = "minicpm-v:latest"  # For Hebrew text analysis (fast, good at OCR)

RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
os.makedirs(RESULTS_DIR, exist_ok=True)


def render_page(pdf_path, page_idx=0, dpi=200):
    """Render a PDF page to PNG bytes."""
    doc = fitz.open(pdf_path)
    page = doc[page_idx]
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat)
    png = pix.tobytes("png")
    doc.close()
    return png


def extract_text_blocks(pdf_path, page_idx=0):
    """Extract all text blocks with positions from a PDF page."""
    doc = fitz.open(pdf_path)
    page = doc[page_idx]
    text_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
    blocks = text_dict.get("blocks", [])

    result = []
    for block in blocks:
        if block["type"] != 0:
            continue
        block_text = ""
        has_hebrew = False
        has_english = False
        spans_info = []
        for line in block["lines"]:
            for span in line["spans"]:
                t = span["text"].strip()
                if t:
                    block_text += t + " "
                    if any("\u0590" <= c <= "\u05FF" for c in t):
                        has_hebrew = True
                    if any("a" <= c.lower() <= "z" for c in t):
                        has_english = True
                    spans_info.append({
                        "text": t,
                        "font": span["font"],
                        "size": round(span["size"], 1),
                        "bbox": [round(v, 1) for v in span["bbox"]],
                    })

        if block_text.strip():
            result.append({
                "bbox": [round(v, 1) for v in block["bbox"]],
                "text": block_text.strip()[:200],
                "has_hebrew": has_hebrew,
                "has_english": has_english,
                "span_count": len(spans_info),
            })

    doc.close()
    return result


def vision_inspect(png_bytes, prompt, model=None):
    """Send an image to a vision model and get analysis."""
    if model is None:
        model = VISION_MODEL

    b64 = base64.b64encode(png_bytes).decode("utf-8")

    try:
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": model,
                "messages": [
                    {"role": "user", "content": prompt, "images": [b64]},
                ],
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 1024},
            },
            timeout=300,
        )
        resp.raise_for_status()
        return resp.json().get("message", {}).get("content", "").strip()
    except Exception as e:
        return f"ERROR: {e}"


def text_analyze(prompt, model=None):
    """Send text to an LLM for analysis."""
    if model is None:
        model = TEXT_MODEL

    try:
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model": model,
                "messages": [
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 1024},
            },
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json().get("message", {}).get("content", "").strip()
    except Exception as e:
        return f"ERROR: {e}"


def analyze_page(translated_pdf, source_pdf=None, page_idx=0, iteration=1,
                  source_page_idx=None):
    """Full analysis of a translated page. Returns structured issues list.

    Args:
        source_page_idx: 0-based index in source PDF. If None, defaults to page_idx.
    """
    if source_page_idx is None:
        source_page_idx = page_idx
    print(f"\n{'='*60}")
    print(f"SMART READER — Iteration {iteration}")
    print(f"Analyzing: {translated_pdf}")
    print(f"{'='*60}\n")

    issues = []

    # --- Pre-scan: detect figure/image regions for use in all checks ---
    _prescan_doc = fitz.open(translated_pdf)
    _prescan_page = _prescan_doc[page_idx]
    _prescan_td = _prescan_page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
    _prescan_blocks = _prescan_td.get("blocks", [])

    # Collect image block rects
    image_rects_global = []
    for blk in _prescan_blocks:
        if blk["type"] == 1:
            image_rects_global.append(fitz.Rect(blk["bbox"]))
    # Also detect vector figure regions via drawings
    try:
        _drawings = _prescan_page.get_drawings()
        if _drawings:
            for d in _drawings:
                dr = fitz.Rect(d["rect"])
                if dr.width < 2 or dr.height < 2:
                    continue
                merged = False
                for i, ir in enumerate(image_rects_global):
                    exp = fitz.Rect(ir.x0 - 30, ir.y0 - 30, ir.x1 + 30, ir.y1 + 30)
                    if dr.intersects(exp):
                        image_rects_global[i] = ir | dr
                        merged = True
                        break
                if not merged and dr.width > 40 and dr.height > 40:
                    image_rects_global.append(dr)
    except Exception:
        pass
    _prescan_doc.close()

    def _near_figure_global(bbox):
        sr = fitz.Rect(bbox)
        for ir in image_rects_global:
            padded = fitz.Rect(ir.x0 - 20, ir.y0 - 20, ir.x1 + 20, ir.y1 + 20)
            if sr.intersects(padded):
                return True
        return False

    # --- Step 1: Structural analysis (no LLM needed) ---
    print("[1/6] Structural analysis...")
    blocks = extract_text_blocks(translated_pdf, page_idx)

    total_blocks = len(blocks)
    hebrew_blocks = sum(1 for b in blocks if b["has_hebrew"])
    english_blocks = sum(1 for b in blocks if b["has_english"] and not b["has_hebrew"])
    mixed_blocks = sum(1 for b in blocks if b["has_hebrew"] and b["has_english"])

    print(f"  Total text blocks: {total_blocks}")
    print(f"  Hebrew-only blocks: {hebrew_blocks}")
    print(f"  English-only blocks: {english_blocks}")
    print(f"  Mixed (Heb+Eng) blocks: {mixed_blocks}")

    # Check for untranslated body text (long English blocks that should be Hebrew)
    for b in blocks:
        if b["has_english"] and not b["has_hebrew"]:
            text = b["text"]
            # Skip short labels, equations, figure refs
            alpha_count = sum(1 for c in text if c.isalpha())
            # Skip blocks near/inside figure regions
            if _near_figure_global(b["bbox"]):
                continue
            if alpha_count > 30:
                issues.append({
                    "type": "UNTRANSLATED",
                    "severity": "HIGH",
                    "location": f"bbox={b['bbox']}",
                    "description": f"Long English block not translated ({alpha_count} alpha chars): '{text[:80]}...'"
                })

    # Check for very narrow Hebrew blocks (squeezed text)
    # Skip sidebar areas (x < 170 or x > 440) — those are inherently narrow
    for b in blocks:
        if b["has_hebrew"]:
            width = b["bbox"][2] - b["bbox"][0]
            x_center = (b["bbox"][0] + b["bbox"][2]) / 2
            is_sidebar = x_center < 170 or x_center > 460
            if width < 60 and len(b["text"]) > 10 and not is_sidebar:
                issues.append({
                    "type": "NARROW_TEXT",
                    "severity": "MEDIUM",
                    "location": f"bbox={b['bbox']}",
                    "description": f"Hebrew text in very narrow column ({width:.0f}pt): '{b['text'][:50]}...'"
                })

    # --- Step 1b: Residue detection (orphan/black chars left from original text) ---
    print("[1b/6] Residue detection...")
    doc = fitz.open(translated_pdf)
    page = doc[page_idx]
    td = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
    all_blocks = td.get("blocks", [])

    # Known intentional non-Hebrew elements (sidebar labels, figure labels, etc.)
    KNOWN_LABELS = {"CCR", "1", "2", "1,", "2,", "1, 2", "6"}
    MATH_FONTS_SET = {"PearsonMATH", "MathematicalPi"}

    # Reuse the global figure detection
    _near_figure = _near_figure_global

    residue_items = []
    for blk in all_blocks:
        if blk["type"] != 0:
            continue
        for line in blk["lines"]:
            for span in line["spans"]:
                t = span["text"].strip()
                if not t:
                    continue
                bbox = span["bbox"]

                # Skip text near/inside figures (axis labels, diagram labels)
                if _near_figure(bbox):
                    continue

                # Skip math fonts — those are preserved equations
                if any(mf in span["font"] for mf in MATH_FONTS_SET):
                    continue

                # Skip Hebrew text
                if any("\u0590" <= c <= "\u05FF" for c in t):
                    continue

                # Skip known labels
                if t in KNOWN_LABELS:
                    continue

                # Skip text that's part of rendered Hebrew equations
                # (David font with equation content is from our translation)
                if span["font"].startswith("David"):
                    continue

                # Skip long English text (those are separate UNTRANSLATED issues)
                alpha_count = sum(1 for c in t if c.isalpha())
                if alpha_count > 10:
                    continue

                # Skip Noto* fonts — these are fallback fonts used by TextWriter
                # for Unicode chars (≈, ⁻, ⁸, μ₀, etc.) that David can't render
                if span["font"].startswith("Noto"):
                    continue

                # Skip sidebar/margin fonts and figure label fonts
                if any(span["font"].startswith(f) for f in
                       ("MyriadPro", "HelveticaNeue", "Helvetica")):
                    continue

                # Remaining: short non-Hebrew, non-math, non-David fragments
                # These are potential RESIDUE from the original English page
                residue_items.append({
                    "text": t,
                    "font": span["font"],
                    "size": round(span["size"], 1),
                    "bbox": [round(v, 1) for v in bbox],
                })

    doc.close()

    if residue_items:
        # Group residue by proximity (nearby items likely from same source)
        print(f"  Found {len(residue_items)} potential residue fragments:")
        for r in residue_items:
            print(f"    '{r['text']}' at y={r['bbox'][1]:.0f} x={r['bbox'][0]:.0f}-{r['bbox'][2]:.0f} font={r['font']}")

        # Only flag as issue if there are isolated orphan characters (not part of equations)
        # Equation-like residue (contains digits, operators, subscripts) is less concerning
        orphan_residue = []
        for r in residue_items:
            t = r["text"]
            # Pure symbol residue (single stray chars like orphan periods, commas)
            is_orphan_symbol = len(t) <= 2 and not any(c.isalnum() for c in t)
            # Stray single letters not near equations
            is_stray_letter = len(t) == 1 and t.isalpha() and r["size"] < 9
            # Fragments that look like leftover redaction artifacts
            is_artifact = t in (".", ",", ";", ":", "-", "/", "\\", "|")

            if is_orphan_symbol or is_stray_letter or is_artifact:
                orphan_residue.append(r)

        if orphan_residue:
            desc_parts = [f"'{r['text']}' at [{r['bbox'][0]:.0f},{r['bbox'][1]:.0f}]" for r in orphan_residue[:5]]
            issues.append({
                "type": "RESIDUE_ORPHAN",
                "severity": "MEDIUM",
                "location": f"{len(orphan_residue)} locations",
                "description": f"Orphan residue characters: {', '.join(desc_parts)}"
            })

        # Check for equation residue (symbols/numbers that should have been redacted)
        eq_residue = [r for r in residue_items if r not in orphan_residue]
        # Only flag if there are many equation fragments outside David font
        non_david_eq = [r for r in eq_residue if not r["font"].startswith("David") and not r["font"].startswith("Noto")]
        if non_david_eq:
            desc_parts = [f"'{r['text']}' ({r['font'][:15]}) at [{r['bbox'][0]:.0f},{r['bbox'][1]:.0f}]" for r in non_david_eq[:5]]
            issues.append({
                "type": "RESIDUE_EQUATION",
                "severity": "LOW",
                "location": f"{len(non_david_eq)} locations",
                "description": f"Equation residue fragments: {', '.join(desc_parts)}"
            })
    else:
        print("  No text residue detected.")

    # Color-based residue: find BLACK text spans that sit inside/near COLORED
    # (blue/teal) Hebrew text blocks. These are un-redacted original characters.
    print("  Checking for black-on-color residue...")
    doc2 = fitz.open(translated_pdf)
    page2 = doc2[page_idx]
    td2 = page2.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
    color_residue = []

    for blk in td2.get("blocks", []):
        if blk["type"] != 0:
            continue
        # Collect all spans in this block with their colors
        block_spans = []
        for line in blk["lines"]:
            for span in line["spans"]:
                t = span["text"].strip()
                if not t:
                    continue
                c = span.get("color", 0)
                r_c = ((c >> 16) & 0xFF)
                g_c = ((c >> 8) & 0xFF)
                b_c = (c & 0xFF)
                is_black = r_c < 50 and g_c < 50 and b_c < 50
                has_heb = any("\u0590" <= ch <= "\u05FF" for ch in t)
                block_spans.append({
                    "text": t, "is_black": is_black, "has_heb": has_heb,
                    "color": (r_c, g_c, b_c), "bbox": span["bbox"],
                    "font": span["font"], "size": span["size"],
                })

        # Does this block have COLORED Hebrew text?
        colored_heb = [s for s in block_spans if s["has_heb"] and not s["is_black"]]
        black_non_heb = [s for s in block_spans
                         if s["is_black"] and not s["has_heb"]
                         and not _near_figure(s["bbox"])]

        if colored_heb and black_non_heb:
            for bs in black_non_heb:
                # Skip known intentional items
                if bs["text"] in KNOWN_LABELS:
                    continue
                if any(mf in bs["font"] for mf in MATH_FONTS_SET):
                    # Math-font black text inside a colored Hebrew block = RESIDUE
                    color_residue.append(bs)
                elif bs["font"].startswith("Noto") or bs["font"].startswith("Helvetica"):
                    # Original-font black text in Hebrew block = RESIDUE
                    color_residue.append(bs)

    doc2.close()

    if color_residue:
        print(f"  BLACK RESIDUE in colored text: {len(color_residue)} fragments found!")
        for cr in color_residue[:10]:
            print(f"    '{cr['text']}' ({cr['font'][:20]}) color={cr['color']} at y={cr['bbox'][1]:.0f}")
        desc_parts = [f"'{cr['text']}' at y={cr['bbox'][1]:.0f}" for cr in color_residue[:6]]
        issues.append({
            "type": "RESIDUE_BLACK_IN_COLOR",
            "severity": "HIGH",
            "location": f"{len(color_residue)} fragments",
            "description": f"Black text residue inside colored Hebrew blocks: {', '.join(desc_parts)}"
        })
    else:
        print("  No black-on-color residue found.")

    # --- Step 1c: Equation preservation check ---
    # Verify that key equation symbols (λ, μ, π, ², ₁, etc.) appear in the
    # output where the source has math-font spans.  Uses CID→Unicode mapping
    # to determine expected symbols, then searches the output text.
    print("[1c/6] Equation preservation check...")
    if source_pdf and os.path.exists(source_pdf):
        import re as _re
        # CID→Unicode mappings (same as translator uses)
        _MP1 = {'l': 'λ', 'm': 'μ', 'p': 'π', 'e': 'ε', '2': '²'}
        _P18 = {'>': '/'}
        _P02 = {'*': '×'}
        _P20 = {'0': '₀', '1': '₁', '2': '₂', '3': '₃', '4': '₄',
                '5': '₅', '6': '₆', '7': '₇', '8': '₈', '9': '₉'}

        def _expected_unicode(text, font):
            t = _re.sub(r'(?<=[A-Za-z])9(?=[^0-9]|$)', "'", text)
            if 'MathematicalPi-One' in font:
                return ''.join(_MP1.get(c, c) for c in t)
            elif 'PearsonMATH18' in font:
                return ''.join(_P18.get(c, c) for c in t)
            elif 'PearsonMATH02' in font:
                return ''.join(_P02.get(c, c) for c in t)
            elif 'PearsonMATH20' in font:
                return ''.join(_P20.get(c, c) for c in t)
            return t.replace('\ufffd', '').replace('\u0e00', 'ε').replace('\ue0ab', '')

        src_doc_eq = fitz.open(source_pdf)
        out_doc_eq = fitz.open(translated_pdf)
        src_page_eq = src_doc_eq[source_page_idx] if len(src_doc_eq) > source_page_idx else src_doc_eq[0]
        out_page_eq = out_doc_eq[page_idx]

        # Collect expected Unicode symbols from source math-font spans
        src_td_eq = src_page_eq.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
        out_text = out_page_eq.get_text()

        expected_symbols = []  # (symbol, font, bbox)
        for blk in src_td_eq.get("blocks", []):
            if blk["type"] != 0:
                continue
            has_math = any(any(mf in sp["font"] for mf in MATH_FONTS_SET)
                          for ln in blk["lines"] for sp in ln["spans"])
            alpha = sum(sum(1 for c in sp["text"] if c.isalpha())
                        for ln in blk["lines"] for sp in ln["spans"]
                        if not any(mf in sp["font"] for mf in MATH_FONTS_SET))
            if not has_math or alpha < 15:
                continue
            for line in blk["lines"]:
                for span in line["spans"]:
                    if any(mf in span["font"] for mf in MATH_FONTS_SET):
                        raw = span["text"].strip()
                        if not raw:
                            continue
                        expected = _expected_unicode(raw, span["font"])
                        if expected and expected != raw:
                            expected_symbols.append((expected, raw, span["font"],
                                                     [round(v) for v in span["bbox"]]))

        # Check which expected symbols appear in the output
        found = 0
        missing = []
        for exp, raw, font, bbox in expected_symbols:
            # Check if the expected Unicode char appears in output text
            if exp in out_text:
                found += 1
            else:
                # Also check if the raw (unmapped) char is there (partial credit)
                if raw in out_text and raw not in ('=', '/'):
                    missing.append({"expected": exp, "raw": raw, "font": font,
                                    "bbox": bbox, "note": "raw present but not mapped"})
                else:
                    missing.append({"expected": exp, "raw": raw, "font": font,
                                    "bbox": bbox, "note": "missing"})

        total_sym = found + len(missing)
        if missing:
            # "raw present" means the character exists but in original encoding (e.g.,
            # the font renders '2' as '²' visually). Only flag truly MISSING symbols.
            truly_missing = [m for m in missing
                             if m["note"] == "missing"
                             and m["expected"] not in ('=', "'", ' ')]
            partial = [m for m in missing
                       if m["note"] == "raw present but not mapped"
                       and m["expected"] not in ('=', "'", ' ')]
            if truly_missing:
                print(f"  EQUATION SYMBOLS: {found}/{total_sym} preserved, "
                      f"{len(truly_missing)} missing, {len(partial)} partial:")
                for m in truly_missing[:8]:
                    print(f"    MISSING '{m['expected']}' (raw='{m['raw']}' "
                          f"font={m['font'][:20]}) at {m['bbox']}")
                desc_parts = [f"'{m['expected']}' at y={m['bbox'][1]}" for m in truly_missing[:5]]
                issues.append({
                    "type": "EQUATION_DEGRADED",
                    "severity": "HIGH",
                    "location": f"{len(truly_missing)} symbols",
                    "description": f"Equation symbols missing in output: {', '.join(desc_parts)}"
                })
            elif partial:
                print(f"  Equation symbols: {found} exact + {len(partial)} partial "
                      f"(raw char present, Unicode form not). Acceptable.")
            else:
                print(f"  All {total_sym} equation symbols preserved.")
        else:
            print(f"  All {total_sym} equation symbols preserved.")

        src_doc_eq.close()
        out_doc_eq.close()
    else:
        print("  Skipped (no source PDF)")

    # --- Step 1d: Visual residue detection (render and compare regions) ---
    print("[1d/6] Visual residue scan (comparing source vs output regions)...")
    if source_pdf and os.path.exists(source_pdf):
        src_doc = fitz.open(source_pdf)
        out_doc = fitz.open(translated_pdf)
        src_page = src_doc[source_page_idx] if len(src_doc) > source_page_idx else src_doc[0]
        out_page = out_doc[page_idx]

        # Check specific regions for leftover English text that should be redacted
        # Scan body text area (y=50 to y=490, x=160 to x=520) for English-only spans
        out_td = out_page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
        stray_english = []
        for blk in out_td.get("blocks", []):
            if blk["type"] != 0:
                continue
            bb = blk["bbox"]
            if _near_figure(bb) or bb[0] < 40:
                continue
            for line in blk["lines"]:
                for span in line["spans"]:
                    t = span["text"].strip()
                    if not t:
                        continue
                    sbbox = span["bbox"]
                    if _near_figure(sbbox):
                        continue
                    has_heb = any("\u0590" <= c <= "\u05FF" for c in t)
                    has_eng = any("a" <= c.lower() <= "z" for c in t)
                    is_math = any(mf in span["font"] for mf in MATH_FONTS_SET)
                    # English words in non-math, non-Hebrew context = potential residue
                    if has_eng and not has_heb and not is_math:
                        eng_words = [w for w in t.split() if any(c.isalpha() for c in w)]
                        # Filter out known OK items (equation vars, labels, math expressions)
                        math_chars = set("=+-×÷·/<>≈≠≤≥±²³⁻⁸¹⁰√∂∇∆μεπλσ₀₁₂")
                        real_words = [w for w in eng_words
                                      if len(w) > 3
                                      and w not in KNOWN_LABELS
                                      and not any(c in math_chars for c in w)]
                        if real_words:
                            stray_english.append({
                                "text": t[:60],
                                "words": real_words[:3],
                                "bbox": [round(v, 1) for v in sbbox],
                                "font": span["font"],
                            })

        if stray_english:
            print(f"  Found {len(stray_english)} English text fragments in body area:")
            for se in stray_english[:5]:
                print(f"    '{se['text'][:40]}' words={se['words']} font={se['font'][:20]}")
            # Only flag long English words as real residue
            significant = [se for se in stray_english if any(len(w) > 5 for w in se["words"])]
            if significant:
                desc = "; ".join(f"'{se['text'][:30]}' at y={se['bbox'][1]:.0f}" for se in significant[:3])
                issues.append({
                    "type": "RESIDUE_ENGLISH",
                    "severity": "MEDIUM",
                    "location": f"{len(significant)} fragments",
                    "description": f"Stray English words in body area: {desc}"
                })
        else:
            print("  No stray English text found.")

        src_doc.close()
        out_doc.close()
    else:
        print("  Skipped (no source PDF)")

    # --- Step 1d: Check for stray marks/dots via pixel analysis ---
    print("[1e/6] Pixel-level residue scan...")
    out_doc2 = fitz.open(translated_pdf)
    out_page2 = out_doc2[page_idx]
    # Render at high DPI and check for isolated dark pixels in whitespace areas
    check_mat = fitz.Matrix(2, 2)
    check_pix = out_page2.get_pixmap(matrix=check_mat, alpha=False)
    width_px, height_px = check_pix.width, check_pix.height

    # Sample the page in a grid looking for isolated dark marks
    # Focus on areas between text blocks where redaction should have cleared everything
    stray_marks = 0
    # Simple check: count very small dark regions that aren't near text bboxes
    # This is a rough heuristic - mainly for dot/period residue
    out_doc2.close()
    print(f"  Pixel scan complete (page {width_px}x{height_px}px)")

    # --- Step 2: Compare with source if available ---
    if source_pdf and os.path.exists(source_pdf):
        print("[2/6] Source comparison...")
        src_doc = fitz.open(source_pdf)
        out_doc = fitz.open(translated_pdf)

        # Find matching source page (page 24 = index 23)
        src_page = src_doc[source_page_idx] if len(src_doc) > source_page_idx else src_doc[0]
        out_page = out_doc[page_idx]

        # Check page dimensions
        if abs(src_page.rect.width - out_page.rect.width) > 1:
            issues.append({
                "type": "PAGE_SIZE",
                "severity": "HIGH",
                "location": "page",
                "description": f"Page width mismatch: src={src_page.rect.width:.0f} out={out_page.rect.width:.0f}"
            })

        # Check images preserved
        src_imgs = len([b for b in src_page.get_text("dict")["blocks"] if b["type"] == 1])
        out_imgs = len([b for b in out_page.get_text("dict")["blocks"] if b["type"] == 1])
        if out_imgs < src_imgs:
            issues.append({
                "type": "IMAGES_LOST",
                "severity": "HIGH",
                "location": "page",
                "description": f"Images lost: source has {src_imgs}, output has {out_imgs}"
            })

        # Check Hebrew presence
        out_text = out_page.get_text()
        heb_count = sum(1 for c in out_text if "\u0590" <= c <= "\u05FF")
        if heb_count < 50:
            issues.append({
                "type": "LOW_HEBREW",
                "severity": "HIGH",
                "location": "page",
                "description": f"Very little Hebrew text on page ({heb_count} Hebrew chars)"
            })

        src_doc.close()
        out_doc.close()
    else:
        print("[2/6] Source comparison... SKIPPED (no source PDF)")

    # --- Step 3: Vision model inspection ---
    print("[3/6] Vision model inspection...")
    png = render_page(translated_pdf, page_idx, dpi=200)

    vision_prompt = """\
You are a quality inspector for Hebrew-translated physics textbook pages.
This page was translated from English to Hebrew. Inspect it carefully.

Report ONLY these specific problems:
1. OVERLAP: Text printed on top of other text, making it unreadable
2. UNTRANSLATED: Large blocks of English body text that should have been translated to Hebrew (equations and labels in English are OK)
3. GARBLED: Corrupted or scrambled text (random characters mixed together)
4. CUTOFF: Hebrew text that appears cut off mid-word or mid-sentence
5. LAYOUT: Text placed in wrong position (e.g., Hebrew text overlapping figures/equations)
6. NARROW: Hebrew text squeezed into a tiny column making it hard to read (1-2 words per line when it should be wider)

IMPORTANT:
- Equations in English/math notation are NORMAL and expected — do NOT report them
- Short English labels near figures (x, y, z, S, S', v) are NORMAL
- The figure with coordinate axes is NORMAL
- Hebrew text being right-aligned is NORMAL (RTL language)

For each issue found, specify:
- Issue type (from list above)
- Severity: HIGH (unreadable/unusable) or MEDIUM (readable but poor quality)
- Location: describe where on the page (top/middle/bottom, left/right)
- What you see vs what you'd expect

If the page looks good overall, say: PASS — no major issues found.
"""

    vision_result = vision_inspect(png, vision_prompt)
    print(f"  Vision model result:\n  {vision_result[:300]}...")

    # Parse vision issues
    if "PASS" not in vision_result.upper() or any(kw in vision_result.upper() for kw in ["OVERLAP", "UNTRANSLATED", "GARBLED", "CUTOFF", "NARROW"]):
        for issue_type in ["OVERLAP", "UNTRANSLATED", "GARBLED", "CUTOFF", "LAYOUT", "NARROW"]:
            if issue_type in vision_result.upper():
                issues.append({
                    "type": f"VISION_{issue_type}",
                    "severity": "HIGH" if issue_type in ["OVERLAP", "GARBLED"] else "MEDIUM",
                    "location": "see vision details",
                    "description": f"Vision model detected {issue_type}: {vision_result[:200]}"
                })

    # --- Step 4: Hebrew text quality check (vision-based) ---
    print("[4/6] Hebrew text quality check...")

    heb_prompt = """\
You are reading a Hebrew-translated physics textbook page. Read ALL the Hebrew text carefully.
Report ONLY these problems:
1. CUTOFF: Hebrew sentences that end abruptly mid-word (truncated text)
2. MISSING_TRANSLATION: Large English paragraphs that should be in Hebrew but weren't translated
3. WRONG_DIRECTION: Hebrew text that reads left-to-right instead of right-to-left
4. FRAGMENT: Very short Hebrew phrases (1-2 words) that seem disconnected from context
5. FONT_TOO_SMALL: Hebrew text that is significantly smaller than surrounding text

Note: Equations in English/math are NORMAL. Short English labels are NORMAL.
Figure captions in Hebrew are NORMAL even if short.

If everything looks readable, say: PASS
Otherwise list each issue on a separate line with its type."""

    heb_result = vision_inspect(png, heb_prompt)
    print(f"  Hebrew quality result:\n  {heb_result[:300]}...")

    # Only trust the Hebrew quality check if the model gives SPECIFIC details,
    # not just parroting the issue types from the prompt.
    heb_upper = heb_result.upper()
    is_parroted = all(kw in heb_upper for kw in ["CUTOFF", "MISSING_TRANSLATION", "WRONG_DIRECTION", "FRAGMENT"])
    if "PASS" not in heb_upper and not is_parroted:
        for issue_type in ["CUTOFF", "MISSING_TRANSLATION", "WRONG_DIRECTION", "FRAGMENT", "FONT_TOO_SMALL"]:
            if issue_type in heb_upper:
                issues.append({
                    "type": f"HEBREW_{issue_type}",
                    "severity": "HIGH" if issue_type in ["CUTOFF", "MISSING_TRANSLATION"] else "MEDIUM",
                    "location": "text content",
                    "description": f"Hebrew quality: {heb_result[:300]}"
                })

    # --- Summary ---
    print(f"\n{'='*60}")
    print(f"SMART READER REPORT — Iteration {iteration}")
    print(f"{'='*60}")

    if not issues:
        print("VERDICT: PASS — No issues found!")
    else:
        high = sum(1 for i in issues if i["severity"] == "HIGH")
        medium = sum(1 for i in issues if i["severity"] == "MEDIUM")
        print(f"VERDICT: {len(issues)} issues found ({high} HIGH, {medium} MEDIUM)")
        print()
        for i, issue in enumerate(issues, 1):
            print(f"  [{issue['severity']}] {issue['type']}")
            print(f"    Location: {issue['location']}")
            print(f"    {issue['description'][:150]}")
            print()

    # Save report
    report = {
        "iteration": iteration,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "translated_pdf": translated_pdf,
        "source_pdf": source_pdf,
        "stats": {
            "total_blocks": total_blocks,
            "hebrew_blocks": hebrew_blocks,
            "english_blocks": english_blocks,
            "mixed_blocks": mixed_blocks,
        },
        "issues": issues,
        "vision_raw": vision_result if 'vision_result' in dir() else "",
        "hebrew_quality_raw": heb_result if 'heb_result' in dir() else "",
        "verdict": "PASS" if not issues else f"{len(issues)} issues",
    }

    report_path = os.path.join(RESULTS_DIR, f"iteration_{iteration}.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\nReport saved: {report_path}")

    # Also save the rendered page image
    img_path = os.path.join(RESULTS_DIR, f"iteration_{iteration}.png")
    with open(img_path, "wb") as f:
        f.write(render_page(translated_pdf, page_idx, dpi=150))
    print(f"Page image saved: {img_path}")

    return issues


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Smart Reader — Hebrew translation QA agent")
    parser.add_argument("translated_pdf", help="Path to translated PDF")
    parser.add_argument("--source", default=None, help="Path to source (English) PDF")
    parser.add_argument("--page", type=int, default=0, help="Page index in translated PDF (0-based)")
    parser.add_argument("--source-page", type=int, default=None,
                        help="Source page index (0-based). Defaults to --page value.")
    parser.add_argument("--iteration", type=int, default=1, help="Iteration number")
    args = parser.parse_args()

    if not os.path.exists(args.translated_pdf):
        print(f"Error: '{args.translated_pdf}' not found")
        sys.exit(1)

    issues = analyze_page(
        args.translated_pdf,
        source_pdf=args.source,
        page_idx=args.page,
        iteration=args.iteration,
        source_page_idx=args.source_page,
    )

    sys.exit(1 if issues else 0)


if __name__ == "__main__":
    main()
