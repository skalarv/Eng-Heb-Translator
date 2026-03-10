# Chat Progress

## Session 2026-03-10

- User requested that all chat progress be summarized in this CLAUDE.md file.

### Fix 1: Empty Pages (`translate_pdf.py`)
- **Problem**: Script produced empty/unreadable pages.
- **Root causes**: Used `/api/generate` with `<2he>` prefix (model returned English explanations), font scaled to invisible, no Hebrew validation.
- **Fixes**: Switched to `/api/chat` with system prompt, added Hebrew char validation, added `MIN_FONT_SIZE`, stripped quotes from output, reduced `num_predict` to 512.

### Fix 2: RTL Rendering
- **Problem**: Hebrew text rendered left-to-right (reversed).
- **Fixes**: Added `python-bidi`, applied `get_display()` for logical→visual order, added fallback save path for locked files.

### Fix 3: Font Size & Truncation
- **Problem**: Per-line font scaling (6.7-10pt) and word truncation with `...`.
- **Fixes**: Used full column width for positioning, removed all font scaling and truncation, added UTF-8 stdout.

### Fix 4: Equations, Missing Words, Layout (Major Rewrite)
- **Problem**: (a) Equations garbled — math blocks translated and rendered in David font instead of original math fonts. (b) Missing words — hyphenated line breaks ("introduc-" / "tory") translated as fragments. (c) Figure axis labels (y,S,x,z,v) "translated" to model apology text. (d) Caption misalignment — narrow caption column right-aligned to body text margin.
- **Root causes**: All text blocks treated uniformly; no detection of equations, labels, or block structure; line-by-line translation broke hyphenated words.
- **Fixes applied** (full rewrite of `translate_page`):
  1. **Equation skip**: Added `MATH_FONTS` detection (`PearsonMATH*`, `MathematicalPi*`). Blocks with math fonts and <15 alpha chars in text fonts are skipped entirely — equations stay in original fonts untouched.
  2. **Label skip**: Blocks with ≤3 chars total (axis labels like y, S, x, z, v) are skipped.
  3. **Hyphenation merge**: Lines ending with `-` are merged with the next line before translation (e.g., "introduc-" + "tory" → "introductory").
  4. **Per-block alignment**: Each block uses its own margins (block_x0, block_x1) for right-alignment, so captions align to caption column and body text to body column.
  5. **Word wrapping**: Added `wrap_hebrew_text()` — splits translated text into lines fitting block width. Handles merged multi-line units.
  6. **Per-span redaction**: Redacts individual spans instead of full-line rects to avoid whiting out adjacent content.
  7. **Mixed blocks**: Blocks with math fonts BUT ≥15 alpha chars in text fonts are kept for translation (inline equation references preserved).
  8. **Helper functions**: `_block_has_math_font()`, `_block_alpha_count()`, `_block_full_text()` for clean block classification.
- **QA**: Test suite expanded to **49 tests** across **9 groups**:
  - Groups 1-3: Bidi, fonts, translation (unchanged)
  - Group 4: Equation & label skip logic (7 tests — mock blocks)
  - Group 5: Hyphenation merge logic (3 tests)
  - Group 6: Word wrap correctness (5 tests)
  - Group 7: Source PDF page 22 structure validation (4 tests)
  - Group 8: Module import & parse (4 tests)
  - Group 9: End-to-end page 22 (10 tests — equations preserved, math fonts present, axis labels untouched, uniform font sizes, no apology text, no word fragments)
  - **Result: 49/49 PASSED**
- **Visual comparison** (`visual_compare.py`): Source vs output page 22:
  - Page number "4": preserved at [46,37]
  - Equations: 35 math-font spans preserved in original fonts
  - Images: all 5 preserved
  - Axis labels: all 13 (y,S,x,z,v + primed variants) preserved
  - Hebrew body: 25 lines at 10pt, headers 14-18pt, captions 9pt
  - No model apology text ("מצטער")
  - Y-range coverage: source 37-656, output 37-659 (matches)
### Fix 5: Text-Equation Overlap (Paragraph-Level Translation)
- **Problem**: Hebrew body text lines overlapped with equation blocks below. Per-line translations that wrapped to 2+ lines extended into equation territory. Figure caption text also oversized.
- **Root cause**: Each line translated independently → wrapped Hebrew lines overflowed into adjacent equation blocks. No cap on vertical space usage.
- **Fixes applied**:
  1. **Paragraph-level translation**: All lines within a block now merged into one paragraph (with hyphenation handling), translated as a single unit. Reduces 28 individual line translations to 6 paragraph translations — much better context and quality.
  2. **Line slot capping**: Wrapped Hebrew lines hard-capped at `n_available` (original line count). Prevents ANY overflow into adjacent blocks.
  3. **Font scaling for overflow**: If wrapped lines exceed available slots, font scaled down by 0.92x iteratively (min 6pt) until text fits. Only triggers when paragraph translation is significantly longer than original.
  4. **Caption containment**: Caption blocks use their own narrow margins (~106pt) for word wrapping, keeping text within the caption column.
- **QA**: Test suite expanded to **50 tests**:
  - Added critical overlap test: checks no Hebrew text y-position falls within any equation block's y-range
  - **Result: 50/50 PASSED, 0 overlaps detected**
- **Output**: `Modern_Physics_by_Tipler_6th_edition_hebrew_p22_new.pdf`
  - 0 overlaps between Hebrew text and equations
  - Equations preserved (35 math-font spans in original fonts)
  - Axis labels preserved (13 labels)
  - All 5 images preserved
  - Caption at 9.2pt within caption column (y=570-647)

### Feature: Parallel Page Translation
- Added `--workers N` (`-w N`) CLI flag for multi-threaded page translation
- Each worker opens its own independent PDF document — fully thread-safe, no shared state
- Ollama queues concurrent requests from all workers
- Results merged in page order after all workers complete
- Falls back to original untranslated page if a worker fails
- Thread-safe `_tprint()` with `threading.Lock` for clean interleaved console output
- Uses `concurrent.futures.ThreadPoolExecutor` + `as_completed`
- `--workers 1` (default) uses original sequential path with zero overhead
- Recommended: `-w 2` to `-w 3` (Ollama serializes inference, so diminishing returns beyond 3)
- **QA: 50/50 PASSED** (no changes to test suite needed — parallel is transparent)

### Documentation Created
- `README.md` — project overview, features, prerequisites, quick start, usage, project structure
- `docs/FUNCTIONAL.md` — full functional spec: architecture, 4-phase pipeline, block classification, data flow, all functions with signatures, constants, error handling, test coverage, known limitations
- `docs/MANUAL.md` — user manual: installation, setup, CLI usage, output explanation, QA guide, diagnostic tools, 9 troubleshooting scenarios, 5 configuration options, worked examples

### GitHub Repository
- **Repo**: https://github.com/skalarv/Eng-Heb-Translator
- **Branch**: `master`
- **Commits**: initial code → documentation → parallel translation

### Project Files
- `translate_pdf.py` — main translation script (paragraph-level, overlap-safe, parallel-capable)
- `test_translate_qa.py` — 50-test QA suite (incl. overlap detection)
- `visual_compare.py` — source vs output structural comparison
- `deep_inspect.py`, `inspect_output.py` — debugging/inspection tools
- `README.md` — project README
- `docs/FUNCTIONAL.md` — functional specification
- `docs/MANUAL.md` — user manual
- `.gitignore` — excludes PDFs, images, __pycache__

### Quick Reference
```bash
# Sequential (single page)
python translate_pdf.py "textbook.pdf" "22"

# Parallel (multiple pages)
python translate_pdf.py "textbook.pdf" "20-25" --workers 3

# Run QA
python test_translate_qa.py

# Dependencies
pip install pymupdf python-bidi requests
ollama pull translategemma:12b
```
