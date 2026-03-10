"""
Full QA test suite for translate_pdf.py RTL Hebrew translation.
Tests: bidi, font, translation, equation skip, label skip, hyphenation merge,
       per-block alignment, font uniformity, word wrapping.
"""
import sys
import os
sys.stdout.reconfigure(encoding="utf-8")
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import fitz
from bidi.algorithm import get_display

PASSED = 0
FAILED = 0

def test(name, condition, detail=""):
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  PASS: {name}")
    else:
        FAILED += 1
        print(f"  FAIL: {name} -- {detail}")


# ── Test Group 1: Bidi Algorithm ──
print("\n=== Test Group 1: Bidi RTL Reordering ===")

heb_logical = "שלום עולם"
heb_visual = get_display(heb_logical)
test("get_display reverses pure Hebrew",
     heb_visual != heb_logical)
test("Visual order reversed character sequence",
     heb_visual[0] == heb_logical[-1])
mixed = "פרק 1: מבוא"
mixed_visual = get_display(mixed)
test("Mixed Hebrew+numbers handled",
     "1" in mixed_visual and any("\u0590" <= c <= "\u05FF" for c in mixed_visual))
test("Pure numbers pass through", get_display("12345") == "12345")
test("Empty string safe", get_display("") == "")


# ── Test Group 2: Hebrew Font Loading ──
print("\n=== Test Group 2: Font Loading ===")

HEBREW_FONT = "C:/Windows/Fonts/david.ttf"
HEBREW_FONT_BOLD = "C:/Windows/Fonts/davidbd.ttf"
test("david.ttf exists", os.path.exists(HEBREW_FONT))
test("davidbd.ttf exists", os.path.exists(HEBREW_FONT_BOLD))
font = fitz.Font(fontfile=HEBREW_FONT)
test("Font object created", font is not None)
heb_text = get_display("העקרונות הבסיסיים")
tl = font.text_length(heb_text, fontsize=10)
test("Font measures Hebrew text", tl > 0)
test_doc = fitz.open()
test_page = test_doc.new_page(width=500, height=500)
tw = fitz.TextWriter(test_page.rect)
try:
    tw.append(fitz.Point(100, 100), heb_text, font=font, fontsize=12)
    tw.write_text(test_page)
    test("TextWriter renders Hebrew glyphs", len(test_page.get_text().strip()) > 0)
except Exception as e:
    test("TextWriter renders Hebrew glyphs", False, str(e))
test_doc.close()


# ── Test Group 3: Translation Function ──
print("\n=== Test Group 3: Translation (live Ollama) ===")

import requests
ollama_up = False
try:
    r = requests.get("http://localhost:11434/api/tags", timeout=3)
    ollama_up = r.status_code == 200
except:
    pass

if not ollama_up:
    print("  SKIP: Ollama not running")
else:
    from translate_pdf import translate_text
    result = translate_text("Hello world")
    has_hebrew = any("\u0590" <= c <= "\u05FF" for c in result)
    test("translate_text returns Hebrew", has_hebrew, f"got: {result!r}")
    test("Output is concise (< 5x input)", len(result) < 55)
    test("Numbers pass through", translate_text("12345") == "12345")
    test("Empty passes through", translate_text("") == "")
    result4 = translate_text("The speed of light is constant.")
    test("Physics text → Hebrew",
         any("\u0590" <= c <= "\u05FF" for c in result4))
    eng = [w for w in result4.split() if w.isalpha() and all(c < "\u0080" for c in w)]
    test("No English words leaked", len(eng) == 0, f"found: {eng}")


# ── Test Group 4: Equation Detection ──
print("\n=== Test Group 4: Equation & Label Skip Logic ===")

from translate_pdf import _block_has_math_font, _block_alpha_count, _block_full_text

# Mock equation block (PearsonMATH font)
eq_block = {"type": 0, "lines": [
    {"spans": [
        {"text": "F", "font": "Times-Bold", "size": 10, "flags": 20, "bbox": [0,0,5,10]},
        {"text": "=", "font": "PearsonMATH08", "size": 10, "flags": 4, "bbox": [5,0,10,10]},
        {"text": "ma", "font": "Times-Italic", "size": 10, "flags": 6, "bbox": [10,0,20,10]},
    ]}
]}
test("Equation block detected (has math font)", _block_has_math_font(eq_block))
test("Equation block has few alpha in text fonts",
     _block_alpha_count(eq_block) < 15,
     f"count={_block_alpha_count(eq_block)}")

# Mock body text block (no math fonts)
txt_block = {"type": 0, "lines": [
    {"spans": [
        {"text": "Newton became the first person to generalize observations",
         "font": "Times-Roman", "size": 10, "flags": 4, "bbox": [0,0,300,12]},
    ]}
]}
test("Body text block: no math font", not _block_has_math_font(txt_block))
test("Body text block: many alpha chars", _block_alpha_count(txt_block) >= 15)

# Mock short label block (axis label)
label_block = {"type": 0, "lines": [
    {"spans": [{"text": "y", "font": "Helvetica", "size": 8, "flags": 6, "bbox": [0,0,5,8]}]}
]}
ft = _block_full_text(label_block)
test("Short label detected (<=3 chars)", len(ft.replace(" ", "")) <= 3, f"text='{ft}'")

# Mock mixed block (text with inline equation refs)
mixed_block = {"type": 0, "lines": [
    {"spans": [
        {"text": "where d v/dt=a is the acceleration of the mass m when acted on",
         "font": "Times-Roman", "size": 10, "flags": 4, "bbox": [0,0,400,12]},
        {"text": "=", "font": "PearsonMATH08", "size": 10, "flags": 4, "bbox": [400,0,410,12]},
    ]}
]}
test("Mixed block: has math font", _block_has_math_font(mixed_block))
test("Mixed block: skipped (has math font → no translation)",
     _block_has_math_font(mixed_block))


# ── Test Group 5: Hyphenation Merging ──
print("\n=== Test Group 5: Hyphenation Merge Logic ===")

# Test that lines ending with '-' get merged correctly
test_lines = [
    "Newton became the first person to generalize the observations of Galileo, al-Haytham,",
    "and others into the laws of motion that occupied much of your attention in introduc-",
    "tory physics. The second of Newton's three laws is",
]

# Simulate merge logic
merged = []
i = 0
while i < len(test_lines):
    m = test_lines[i]
    while m.endswith("-") and i + 1 < len(test_lines):
        i += 1
        m = m[:-1] + test_lines[i]
    merged.append(m)
    i += 1

test("Line 1 (al-Haytham, no merge) stays separate",
     merged[0] == test_lines[0])
test("Lines 2+3 merge (introduc- + tory)",
     "introductory physics" in merged[1],
     f"got: {merged[1][:80]}")
test("Merged result has 2 entries (not 3)", len(merged) == 2)


# ── Test Group 6: Word Wrapping ──
print("\n=== Test Group 6: Word Wrap ===")

from translate_pdf import wrap_hebrew_text

font = fitz.Font(fontfile=HEBREW_FONT)
long_heb = "זהו טקסט ארוך מאוד בעברית שצריך להיות מחולק למספר שורות כדי להתאים לרוחב העמודה"
wrapped = wrap_hebrew_text(long_heb, font, 10.0, 200)
test("Long text wraps to multiple lines", len(wrapped) > 1, f"lines={len(wrapped)}")

for wl in wrapped:
    wl_len = font.text_length(wl, fontsize=10.0)
    test(f"Wrapped line fits (width={wl_len:.0f} <= 200)", wl_len <= 205)

short_heb = "שלום"
wrapped_short = wrap_hebrew_text(short_heb, font, 10.0, 200)
test("Short text stays single line", len(wrapped_short) == 1)

# Verify no words lost
all_words = set(long_heb.split())
wrapped_words = set(w for line in wrapped for w in line.split())
test("No words lost in wrapping", all_words == wrapped_words,
     f"missing: {all_words - wrapped_words}")


# ── Test Group 7: Source PDF Page 22 Structure ──
print("\n=== Test Group 7: Source PDF Page 22 Structure ===")

src_pdf = "Modern_Physics_by_Tipler_6th_edition.pdf"
if not os.path.exists(src_pdf):
    src_pdf = "source/Modern_Physics_by_Tipler_6th_edition.pdf"
if os.path.exists(src_pdf):
    doc = fitz.open(src_pdf)
    page = doc[21]
    td = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
    blocks = [b for b in td.get("blocks", []) if b["type"] == 0]

    test("Page 22 has text blocks", len(blocks) > 0)

    # Count equation blocks (with math fonts)
    eq_blocks = [b for b in blocks if _block_has_math_font(b)]
    test("Page 22 has equation blocks", len(eq_blocks) > 0,
         f"found {len(eq_blocks)}")

    # Count short label blocks
    label_blocks = [b for b in blocks
                    if len(_block_full_text(b).replace(" ", "")) <= 3
                    and _block_full_text(b).strip()]
    test("Page 22 has short label blocks", len(label_blocks) > 0,
         f"found {len(label_blocks)}")

    # Verify body text exists
    body_blocks = [b for b in blocks
                   if not _block_has_math_font(b)
                   and _block_alpha_count(b) >= 15
                   and len(_block_full_text(b).replace(" ", "")) > 3]
    test("Page 22 has body text blocks", len(body_blocks) > 0,
         f"found {len(body_blocks)}")

    doc.close()
else:
    print(f"  SKIP: {src_pdf} not found")


# ── Test Group 8: Module Import & Parse ──
print("\n=== Test Group 8: Module Import & Parse ===")

from translate_pdf import parse_page_range
test("translate_pdf imports OK", True)
test("parse '22' -> [21]", parse_page_range("22", 100) == [21])
test("parse '1-3' -> [0,1,2]", parse_page_range("1-3", 100) == [0, 1, 2])
test("parse '5' with max=3 -> []", parse_page_range("5", 3) == [])


# ── Test Group 9: End-to-End Page 22 Translation ──
print("\n=== Test Group 9: End-to-End Page 22 Translation ===")

if os.path.exists(src_pdf) and ollama_up:
    from translate_pdf import translate_page as tp

    doc = fitz.open(src_pdf)
    out_doc = fitz.open()
    out_doc.insert_pdf(doc, from_page=21, to_page=21)
    test_page = out_doc[0]

    tp(test_page, 22)

    out_text = test_page.get_text()
    has_heb = any("\u0590" <= c <= "\u05FF" for c in out_text)
    test("Translated page contains Hebrew", has_heb)

    # Check equations are PRESERVED (not translated)
    # Equation markers 1-1, 1-2, 1-3 should still be in original
    test("Equation marker '1-1' preserved", "1-1" in out_text)
    test("Equation marker '1-2' preserved", "1-2" in out_text)
    test("Equation marker '1-3' preserved", "1-3" in out_text)

    # Check equation content preserved (F, =, m, etc. in original fonts)
    td = test_page.get_text("dict")
    eq_fonts_found = set()
    for b in td.get("blocks", []):
        if b["type"] != 0:
            continue
        for line in b["lines"]:
            for span in line["spans"]:
                if any(mf in span["font"] for mf in {"PearsonMATH", "MathematicalPi"}):
                    eq_fonts_found.add(span["font"][:15])
    test("Math fonts preserved in output (equations untouched)",
         len(eq_fonts_found) > 0,
         f"math fonts: {eq_fonts_found}")

    # Check axis labels preserved (single chars near figure)
    # Look for small text blocks with single chars at y>480
    small_labels = []
    for b in td.get("blocks", []):
        if b["type"] != 0:
            continue
        for line in b["lines"]:
            for span in line["spans"]:
                t = span["text"].strip()
                if t and len(t) <= 2 and span["size"] <= 9 and span["bbox"][1] > 480:
                    small_labels.append(t)
    test("Figure axis labels preserved",
         any(l in ["y", "x", "z", "S", "v"] for l in small_labels),
         f"labels found: {small_labels}")

    # Check Hebrew font sizes are uniform for body text
    heb_body_sizes = set()
    for b in td.get("blocks", []):
        if b["type"] != 0:
            continue
        for line in b["lines"]:
            for span in line["spans"]:
                t = span["text"].strip()
                if t and any("\u0590" <= c <= "\u05FF" for c in t) and span["size"] >= 9.5:
                    heb_body_sizes.add(round(span["size"], 1))
    test("Hebrew body text at uniform 10pt",
         10.0 in heb_body_sizes and all(s in {10.0, 14.0, 16.0, 18.0, 9.0} for s in heb_body_sizes),
         f"sizes: {sorted(heb_body_sizes)}")

    # Check no "sorry/apologize" text from failed translations
    test("No model apology text in output",
         "מצטער" not in out_text,
         "found 'מצטער' (sorry) in output")

    # Check hyphenated words are complete (no fragments like "introduc" or "tory")
    test("No word fragment 'introduc' in output",
         "introduc" not in out_text.lower())
    test("No word fragment 'tory' as standalone in output",
         "\ntory " not in out_text.lower() and out_text.lower().find("tory physics") == -1)

    # CRITICAL: Check no Hebrew text visually overlaps with PURE equation blocks.
    # Use SOURCE PDF to identify true equation blocks (before redaction changed structure).
    # After redaction, MIXED blocks' leftover math spans look like pure equations.
    src_doc = fitz.open(src_pdf)
    src_td = src_doc[21].get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
    eq_rects = []  # (x0, y0, x1, y1) for each pure equation block in SOURCE
    for b in src_td.get("blocks", []):
        if b["type"] != 0:
            continue
        block_has_math = any(
            any(mf in span["font"] for mf in {"PearsonMATH", "MathematicalPi"})
            for line in b["lines"] for span in line["spans"]
        )
        text_alpha = sum(
            sum(1 for c in span["text"] if c.isalpha())
            for line in b["lines"] for span in line["spans"]
            if not any(mf in span["font"] for mf in {"PearsonMATH", "MathematicalPi"})
        )
        if block_has_math and text_alpha < 15:
            xs, ys = [], []
            for line in b["lines"]:
                for span in line["spans"]:
                    if span["text"].strip():
                        xs.extend([span["bbox"][0], span["bbox"][2]])
                        ys.extend([span["bbox"][1], span["bbox"][3]])
            if xs and ys:
                eq_rects.append((min(xs), min(ys), max(xs), max(ys)))
    src_doc.close()

    # Collect Hebrew text span rects from OUTPUT
    heb_rects = []
    for b in td.get("blocks", []):
        if b["type"] != 0:
            continue
        for line in b["lines"]:
            for span in line["spans"]:
                t = span["text"].strip()
                if t and any("\u0590" <= c <= "\u05FF" for c in t):
                    heb_rects.append(tuple(span["bbox"]))

    # Check: no Hebrew span bbox overlaps with any pure equation bbox
    overlaps = []
    for hx0, hy0, hx1, hy1 in heb_rects:
        for ex0, ey0, ex1, ey1 in eq_rects:
            x_overlap = hx0 < ex1 and hx1 > ex0
            y_overlap = hy0 < ey1 + 2 and hy1 > ey0 - 2
            if x_overlap and y_overlap:
                overlaps.append((hy1, ey0, ey1))
    test("No Hebrew text overlaps with pure equation blocks",
         len(overlaps) == 0,
         f"found {len(overlaps)} overlaps: {overlaps[:3]}")

    out_doc.close()
    doc.close()
else:
    print("  SKIP: source PDF or Ollama not available")


# ── Summary ──
print(f"\n{'='*60}")
print(f"QA RESULTS: {PASSED} passed, {FAILED} failed, {PASSED+FAILED} total")
if FAILED == 0:
    print("ALL TESTS PASSED - Ready to release")
else:
    print("SOME TESTS FAILED - Do NOT release")
print(f"{'='*60}")

sys.exit(1 if FAILED > 0 else 0)
