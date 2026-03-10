# User Manual

## Table of Contents

1. [Installation](#1-installation)
2. [Setup](#2-setup)
3. [Translating a PDF](#3-translating-a-pdf)
4. [Understanding the Output](#4-understanding-the-output)
5. [Running Quality Assurance Tests](#5-running-quality-assurance-tests)
6. [Diagnostic Tools](#6-diagnostic-tools)
7. [Troubleshooting](#7-troubleshooting)
8. [Configuration](#8-configuration)
9. [Examples](#9-examples)

---

## 1. Installation

### 1.1 Install Python Dependencies

```bash
pip install pymupdf python-bidi requests
```

### 1.2 Install Ollama

Download and install Ollama from [https://ollama.com/](https://ollama.com/).

### 1.3 Pull the Translation Model

```bash
ollama pull translategemma:12b
```

This downloads the translategemma 12-billion parameter model (~7 GB). The download happens once.

### 1.4 Verify Hebrew Fonts

The translator uses the David font family bundled with Windows. Verify the fonts exist:

```
C:\Windows\Fonts\david.ttf      (regular)
C:\Windows\Fonts\davidbd.ttf    (bold)
```

These are included with standard Windows installations. If missing, install the "David" font from Windows optional features.

---

## 2. Setup

### 2.1 Start Ollama

Before translating, ensure Ollama is running:

```bash
ollama serve
```

Or start it from the system tray if installed as a service.

### 2.2 Verify Ollama is Ready

```bash
curl http://localhost:11434/api/tags
```

You should see a JSON response listing available models, including `translategemma:12b`.

---

## 3. Translating a PDF

### 3.1 Command Line Usage

```bash
python translate_pdf.py <pdf_path> <page_range>
```

**Arguments:**

| Argument | Description | Examples |
|---|---|---|
| `pdf_path` | Path to the source PDF file | `"textbook.pdf"`, `"C:/Books/physics.pdf"` |
| `page_range` | Pages to translate (1-based) | `"22"`, `"1-5"`, `"1,3,10-12"` |

**Page range formats:**

| Format | Meaning | Example |
|---|---|---|
| `N` | Single page | `"22"` → page 22 |
| `N-M` | Range (inclusive) | `"20-25"` → pages 20 through 25 |
| `N,M,P` | Specific pages | `"1,5,10"` → pages 1, 5, and 10 |
| `N-M,P,Q-R` | Mixed | `"1-3,7,10-12"` → pages 1,2,3,7,10,11,12 |

### 3.2 Interactive Mode

Run without arguments for interactive prompts:

```bash
python translate_pdf.py
```

```
Enter PDF file name/path: Modern_Physics_by_Tipler_6th_edition.pdf
Enter page range (e.g. 1-5 or 3,7,10-12): 20-23
```

### 3.3 Translation Progress

The script prints progress as it works:

```
Opened 'textbook.pdf' (786 pages)
Will translate pages: [20, 21, 22, 23]
Processing page 20...
  Translating (1/6): Newton became the first person to generalize the observa...
  Translating (2/6): The second of Newton's three laws is perhaps the most...
  ...
Processing page 21...
  ...
Done! Translated PDF saved to: textbook_hebrew_p20-23.pdf
```

### 3.4 Translation Speed

Each paragraph takes 5–30 seconds depending on length and hardware. A typical page with 5–8 paragraphs takes 1–3 minutes. Translation is sequential — one paragraph at a time.

---

## 4. Understanding the Output

### 4.1 Output File

The translated PDF is saved in the same directory as the source:

```
Source:  textbook.pdf
Output: textbook_hebrew_p20-23.pdf
```

If the output file is already open (e.g. in a PDF viewer), the script saves as `textbook_hebrew_p20-23_new.pdf` instead.

### 4.2 What Gets Translated

| Content Type | Translated? | Details |
|---|---|---|
| Body text | Yes | English paragraphs → Hebrew, right-to-left |
| Section headers | Yes | Preserved at original font size |
| Figure captions | Yes | Wrapped within caption column width |
| Equations | No | Preserved in original math fonts |
| Figure labels | No | Axis labels (y, x, S, v) kept as-is |
| Images | No | All figures and diagrams preserved |
| Page numbers | No | Kept in original position |

### 4.3 Selected Pages Only

The output PDF contains **only** the translated pages, not the full document. Page 22 of a 786-page book produces a 1-page output PDF.

### 4.4 Layout Preservation

- Hebrew text is **right-aligned** to the original block's right margin
- Font sizes match the original (10pt body, 14–18pt headers, 9pt captions)
- If Hebrew translation is longer than the original, font size scales down (minimum 6pt) to fit the same vertical space
- Lines are hard-capped at the original line count to prevent overlap with adjacent blocks

---

## 5. Running Quality Assurance Tests

### 5.1 Full Test Suite

```bash
python test_translate_qa.py
```

### 5.2 Test Groups

The suite runs 50 tests across 9 groups:

**Groups 1–2 (always run):** Bidi algorithm and font loading — verify basic infrastructure.

**Group 3 (requires Ollama):** Live translation tests — sends text to the model, checks Hebrew output. Skipped if Ollama is not running.

**Groups 4–6 (always run):** Equation/label skip logic, hyphenation merging, and word wrapping — uses mock data.

**Group 7 (requires source PDF):** Validates structure of page 22 in the Tipler textbook. Skipped if PDF not present.

**Group 8 (always run):** Module import and page range parsing.

**Group 9 (requires source PDF + Ollama):** Full end-to-end translation of page 22 with comprehensive output validation. Skipped if either dependency is missing.

### 5.3 Reading Test Results

```
=== Test Group 1: Bidi RTL Reordering ===
  PASS: get_display reverses pure Hebrew
  PASS: Visual order reversed character sequence
  ...

============================================================
QA RESULTS: 50 passed, 0 failed, 50 total
ALL TESTS PASSED - Ready to release
============================================================
```

Failed tests show details:
```
  FAIL: Equation marker '1-1' preserved -- not found in output text
```

---

## 6. Diagnostic Tools

### 6.1 Visual Comparison (`visual_compare.py`)

Compares the structure of source page 22 with the translated output:

```bash
python visual_compare.py
```

Checks:
- Page number preservation
- Equation count (math font spans)
- Image preservation
- Axis label preservation (no Hebrew in labels)
- Hebrew body text sample and line count
- Font size consistency
- Model apology text detection
- Y-position coverage comparison

### 6.2 Deep Inspection (`deep_inspect.py`)

Dumps the full text dictionary of both source and output PDFs:

```bash
python deep_inspect.py
```

Shows every span with font name, size, flags, bounding box, and text content. Useful for debugging font detection or layout issues.

### 6.3 Output Inspection (`inspect_output.py`)

Focused inspection of font sizes and rect widths in the output:

```bash
python inspect_output.py
```

---

## 7. Troubleshooting

### "Error: Cannot connect to Ollama"

Ollama is not running. Start it:
```bash
ollama serve
```

### "Error: Model 'translategemma:12b' not found"

The model hasn't been downloaded. Pull it:
```bash
ollama pull translategemma:12b
```

### "[Warning: No Hebrew in response, keeping original]"

The model returned non-Hebrew text (e.g. English explanation or refusal). This happens occasionally with very short or ambiguous input. The original English is kept. This is safe — the page will have a mix of translated and untranslated blocks.

### Empty or blank pages

Check that:
1. Ollama is running and responsive
2. The model is loaded (first translation may take 10–20s to load)
3. The page actually contains extractable text (scanned PDFs won't work)

### Hebrew text appears reversed

This should not happen with the current version. If it does, verify `python-bidi` is installed:
```bash
pip install python-bidi
```

### Output file locked

If the output PDF is open in a viewer, the script saves as `*_new.pdf`. Close the viewer and re-run to overwrite the original output path.

### Font too small on some paragraphs

This means the Hebrew translation was significantly longer than the English original. The script scaled the font down to fit the available vertical space (minimum 6pt). This is expected behavior for long translations.

### "מצטער" (sorry) appears in output

The model refused to translate some text (returned an apology). This is rare with the current system prompt. If it happens, re-run the translation — model responses can vary.

### UnicodeEncodeError on Windows

The script sets `sys.stdout.reconfigure(encoding="utf-8")` at startup. If you still see encoding errors, run Python with:
```bash
set PYTHONIOENCODING=utf-8
python translate_pdf.py ...
```

---

## 8. Configuration

### 8.1 Changing the Translation Model

Edit `translate_pdf.py` line 18:
```python
MODEL = "translategemma:12b"
```

Replace with any Ollama model that supports English-to-Hebrew translation. Note: the system prompt assumes the model responds to chat-format instructions.

### 8.2 Changing Font Paths

Edit lines 20–21:
```python
HEBREW_FONT = "C:/Windows/Fonts/david.ttf"
HEBREW_FONT_BOLD = "C:/Windows/Fonts/davidbd.ttf"
```

Replace with paths to any Hebrew-capable TrueType font.

### 8.3 Adding Math Font Families

If your PDF uses different font names for equations, add them to line 23:
```python
MATH_FONTS = {"PearsonMATH", "MathematicalPi", "YourMathFont"}
```

The detection uses substring matching — `"PearsonMATH"` matches `PearsonMATH08`, `PearsonMATH12`, etc.

### 8.4 Adjusting Label Detection Threshold

The label skip threshold (≤3 characters) is on line 143 of `translate_pdf.py`:
```python
if len(full_text.replace(" ", "")) <= 3:
```

Increase to skip longer labels, decrease to translate shorter ones.

### 8.5 Translation Parameters

In the `translate_text()` function:
- **Temperature** (line 53): `0.1` — increase for more creative translations, decrease for more literal
- **Max tokens** (line 53): `512` — increase for very long paragraphs
- **Timeout** (line 55): `120` seconds — increase for slow hardware

---

## 9. Examples

### Example 1: Translate a Single Page

```bash
python translate_pdf.py "Modern_Physics_by_Tipler_6th_edition.pdf" "22"
```

Output: `Modern_Physics_by_Tipler_6th_edition_hebrew_p22.pdf`

### Example 2: Translate a Chapter (Pages 20–45)

```bash
python translate_pdf.py "Modern_Physics_by_Tipler_6th_edition.pdf" "20-45"
```

Output: `Modern_Physics_by_Tipler_6th_edition_hebrew_p20-45.pdf`

### Example 3: Translate Selected Pages

```bash
python translate_pdf.py "textbook.pdf" "1,5,22,100-105"
```

Output: `textbook_hebrew_p1_5_22_100-105.pdf`

### Example 4: Run Tests Before Release

```bash
python test_translate_qa.py
# If all 50 pass → safe to release
# If any fail → check output, fix, re-run
```

### Example 5: Debug a Bad Page

```bash
# 1. Translate the page
python translate_pdf.py "textbook.pdf" "22"

# 2. Run visual comparison (edit filenames in visual_compare.py if needed)
python visual_compare.py

# 3. Dump all spans for detailed inspection
python deep_inspect.py
```
