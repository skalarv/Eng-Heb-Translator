# Functional Specification

## 1. Overview

The Eng-Heb Translator converts English PDF pages to Hebrew while preserving the original document layout, equations, figures, and labels. It targets academic/scientific textbooks that contain a mix of body text, mathematical equations, and annotated figures.

## 2. System Architecture

```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐
│  Source PDF  │────>│ translate_pdf│────>│  Output PDF  │
│  (English)   │     │   .py        │     │  (Hebrew)    │
└─────────────┘     └──────┬───────┘     └──────────────┘
                           │
                    ┌──────┴───────┐
                    │  Ollama API  │
                    │ translategemma│
                    │   :12b       │
                    └──────────────┘
```

### Components

| Component | Role |
|---|---|
| `translate_pdf.py` | Main pipeline — block classification, paragraph merging, translation, redaction, Hebrew rendering |
| Ollama (local) | LLM inference server running translategemma:12b |
| PyMuPDF (fitz) | PDF reading (text dict extraction), redaction, and text insertion |
| python-bidi | Converts logical Hebrew character order to visual order for PDF rendering |
| David font | Hebrew-capable TrueType font (regular + bold) for rendered output |

## 3. Functional Requirements

### 3.1 Translation Pipeline

The pipeline processes each selected page through 4 phases:

#### Phase 1: Block Classification

Each text block in the PDF is classified into one of four categories:

| Category | Detection Criteria | Action |
|---|---|---|
| **Equation** | Contains math font spans (`PearsonMATH*`, `MathematicalPi*`) AND fewer than 15 alphabetic characters in non-math spans | **Skip** — preserved exactly as-is |
| **Short label** | Total text content ≤ 3 characters (after removing spaces) | **Skip** — axis labels like y, x, S, v preserved |
| **Mixed text+equation** | Contains math font spans BUT ≥ 15 alphabetic characters in non-math spans | **Translate** — inline equation references kept, surrounding text translated |
| **Body text** | No math fonts, has alphabetic content, > 3 characters | **Translate** |

Non-text blocks (images, type != 0) are never modified.

#### Phase 2: Paragraph Merging & Translation

For each translatable block:

1. All lines are merged into a single paragraph string
2. Hyphenated line breaks are detected and rejoined:
   - Line ending with `-` where the next line continues the word → hyphen removed, words joined
   - Lines ending with `-` as part of a compound word (e.g., "al-Haytham,") → kept as-is (handled by checking if next line starts lowercase continuation)
3. The merged paragraph is sent to Ollama for translation
4. Duplicate paragraphs are translated only once (cached per page)

**Translation API call:**
- Endpoint: `POST http://localhost:11434/api/chat`
- Model: `translategemma:12b`
- System prompt: Forces Hebrew-only output, no explanations
- Temperature: 0.1 (near-deterministic)
- Max tokens: 512
- Timeout: 120 seconds

**Validation:** Response must contain at least one Hebrew character (`\u0590`–`\u05FF`). If not, the original English text is kept.

#### Phase 3: Redaction

For each translatable block, every original text span is covered with a white rectangle using PyMuPDF's redaction API. Redactions are applied with `images=fitz.PDF_REDACT_IMAGE_NONE` to preserve images.

#### Phase 4: Hebrew Text Rendering

For each translated paragraph:

1. **Word wrapping:** Text is split into lines fitting the original block width using `wrap_hebrew_text()`
2. **Overflow protection (3-layer):**
   - If wrapped lines exceed available line slots → scale font down by 0.92× iteratively (minimum 6pt)
   - Hard cap: wrapped lines truncated to `n_available` (original line count)
3. **Bidi conversion:** Each wrapped line is converted from logical to visual order via `get_display()`
4. **Right-alignment:** Each line is positioned at `block_x1 - text_width`
5. **Y-positioning:** Each line is placed at the original line's y-position (baseline adjusted by 15% of line height)
6. **Color preservation:** Original text color is converted from integer to RGB tuple and applied
7. **Font selection:** Bold spans use `davidbd.ttf`, regular spans use `david.ttf`

### 3.2 Page Range Parsing

The `parse_page_range()` function accepts:
- Single page: `"22"` → page 22 (0-indexed: 21)
- Range: `"1-5"` → pages 1 through 5
- Comma-separated: `"1,5,10-12"` → pages 1, 5, 10, 11, 12
- Out-of-range pages are silently excluded

### 3.3 Output File Generation

- Output filename: `{original_name}_hebrew_p{range}.pdf`
- Contains only the selected pages (not the full document)
- Saved with `garbage=4, deflate=True` for compression
- If the output path is locked, falls back to `*_new.pdf`

## 4. Data Flow

```
Source PDF page
    │
    ▼
get_text("dict") ──> blocks[] ──> lines[] ──> spans[]
    │                                            │
    │                              font, size, flags, bbox, text, color
    │
    ▼
Block Classification
    │
    ├── Equation block ──> SKIP (preserve)
    ├── Label block ────> SKIP (preserve)
    └── Body text ──────> TRANSLATE
                              │
                              ▼
                     Merge lines → paragraph
                     (rejoin hyphenation)
                              │
                              ▼
                     Ollama API ──> Hebrew text
                              │
                              ▼
                     Redact original spans (white fill)
                              │
                              ▼
                     Word-wrap Hebrew to block width
                              │
                              ▼
                     Bidi visual reorder
                              │
                              ▼
                     Right-align + place at original y positions
                              │
                              ▼
                     TextWriter.append() + write_text()
```

## 5. Key Constants

| Constant | Value | Purpose |
|---|---|---|
| `OLLAMA_URL` | `http://localhost:11434/api/chat` | Ollama chat endpoint |
| `MODEL` | `translategemma:12b` | Translation model |
| `HEBREW_FONT` | `C:/Windows/Fonts/david.ttf` | Regular Hebrew font |
| `HEBREW_FONT_BOLD` | `C:/Windows/Fonts/davidbd.ttf` | Bold Hebrew font |
| `MATH_FONTS` | `{"PearsonMATH", "MathematicalPi"}` | Font families indicating equations |
| `MIN_FONT_SIZE` | `6.0` | Minimum font size for overflow scaling |
| Temperature | `0.1` | Near-deterministic translation |
| `num_predict` | `512` | Max tokens per translation |
| Timeout | `120s` | Per-translation API timeout |

## 6. Error Handling

| Scenario | Behavior |
|---|---|
| Ollama not running | Exit with error message and instructions |
| Model not pulled | Exit with `ollama pull` command suggestion |
| Translation returns no Hebrew | Keep original English text, print warning |
| Translation API timeout (120s) | Keep original English text, print error |
| Font file missing | Fall back to `david.ttf` (regular) |
| Output file locked | Save as `*_new.pdf` |
| TextWriter rendering error | Print error, skip that line |
| PDF file not found | Try current script directory, then exit |
| Empty/no-alpha text | Skip without translation |

## 7. Functions Reference

### `translate_text(text: str) -> str`
Translates English text to Hebrew via Ollama. Returns original text on failure.

**Input:** English string (stripped)
**Output:** Hebrew string, or original if translation fails
**Side effects:** HTTP POST to Ollama

### `_block_has_math_font(block: dict) -> bool`
Checks if any span in the block uses a math/equation font.

**Input:** PyMuPDF text block dict
**Output:** True if PearsonMATH or MathematicalPi font found

### `_block_alpha_count(block: dict) -> int`
Counts alphabetic characters in non-math-font spans.

**Input:** PyMuPDF text block dict
**Output:** Integer count of alpha characters in text-font spans

### `_block_full_text(block: dict) -> str`
Concatenates all non-empty span text in a block.

**Input:** PyMuPDF text block dict
**Output:** Space-joined string of all span texts

### `wrap_hebrew_text(text: str, font: fitz.Font, fontsize: float, max_width: float) -> list[str]`
Word-wraps Hebrew text (logical order) into lines fitting max_width.

**Input:** Hebrew text, font object, font size, maximum pixel width
**Output:** List of line strings (logical order)

### `translate_page(page: fitz.Page, page_num: int) -> None`
Main page translation function. Classifies blocks, translates body text, redacts originals, renders Hebrew.

**Input:** PyMuPDF page object, 1-based page number
**Output:** None (modifies page in-place)
**Side effects:** Modifies the page, calls Ollama API

### `parse_page_range(range_str: str, max_pages: int) -> list[int]`
Parses page range string into sorted list of 0-based page indices.

**Input:** Range string (e.g. "1-5", "3,7,10-12"), maximum page count
**Output:** Sorted list of valid 0-based indices

### `main() -> None`
CLI entry point. Handles argument parsing, Ollama health check, PDF open/save.

## 8. Test Coverage

The QA suite (`test_translate_qa.py`) contains 50 tests in 9 groups:

| Group | Tests | Scope |
|---|---|---|
| 1. Bidi RTL Reordering | 5 | `get_display()` on pure Hebrew, mixed text, numbers, empty |
| 2. Font Loading | 6 | Font file existence, object creation, Hebrew measurement, TextWriter rendering |
| 3. Translation (live) | 6 | Hebrew output, conciseness, number passthrough, empty passthrough, physics text, no English leaks |
| 4. Equation & Label Skip | 7 | Math font detection, alpha counting, short label detection, mixed block handling |
| 5. Hyphenation Merge | 3 | Compound word preservation, cross-line merge, entry count |
| 6. Word Wrap | 5+ | Multi-line wrap, width fitting, single-line passthrough, no word loss |
| 7. Source PDF Structure | 4 | Block count, equation blocks, label blocks, body text blocks |
| 8. Module Import & Parse | 4 | Import success, page range parsing edge cases |
| 9. End-to-End Page 22 | 12 | Hebrew presence, equation markers, math fonts, axis labels, font uniformity, no apology text, no fragments, no overlap |

## 9. Known Limitations

- **Windows-only font paths** — `david.ttf` path is hardcoded to `C:/Windows/Fonts/`. Cross-platform use requires font path configuration.
- **Single model** — Hardcoded to `translategemma:12b`. Other models may work but are untested.
- **Math font detection** — Limited to `PearsonMATH` and `MathematicalPi` families. Other textbooks may use different math fonts.
- **No inline equation preservation** — In mixed blocks (text + math), the entire block is translated. Inline math symbols in text-font spans may be affected.
- **Sequential translation** — Pages and paragraphs are translated one at a time. No parallel API calls.
- **Selected pages only** — Output contains only translated pages, not the full document.
