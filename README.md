# Eng-Heb Translator

A PDF English-to-Hebrew translation tool that preserves document layout, equations, figures, and axis labels. Uses a local [Ollama](https://ollama.com/) LLM for translation and [PyMuPDF](https://pymupdf.readthedocs.io/) for PDF manipulation.

## Features

- **RTL Hebrew rendering** — Correct right-to-left text placement using the bidi algorithm
- **Equation preservation** — Detects math fonts (PearsonMATH, MathematicalPi) and leaves equations untouched
- **Figure & label preservation** — Images, axis labels (y, x, S, v, etc.), and page numbers stay intact
- **Paragraph-level translation** — Merges block lines into paragraphs for better translation context
- **Hyphenation handling** — Rejoins hyphenated words split across lines (e.g. "introduc-" + "tory")
- **Smart word wrapping** — Hebrew text wrapped to fit original block width with font scaling fallback
- **Overlap protection** — Hard caps wrapped lines at available slots to prevent text bleeding into adjacent blocks

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.10+ | |
| [Ollama](https://ollama.com/) | Latest | Must be running locally on port 11434 |
| translategemma:12b | — | `ollama pull translategemma:12b` |
| PyMuPDF | 1.23+ | `pip install pymupdf` |
| python-bidi | 0.4+ | `pip install python-bidi` |
| requests | — | `pip install requests` |
| Hebrew fonts | — | `david.ttf` and `davidbd.ttf` in `C:/Windows/Fonts/` (bundled with Windows) |

## Quick Start

```bash
# 1. Install dependencies
pip install pymupdf python-bidi requests

# 2. Pull the translation model
ollama pull translategemma:12b

# 3. Start Ollama (if not already running)
ollama serve

# 4. Translate pages
python translate_pdf.py "MyTextbook.pdf" "1-5"
```

## Usage

### Command Line

```bash
# Translate a range of pages
python translate_pdf.py "input.pdf" "20-23"

# Translate specific pages
python translate_pdf.py "input.pdf" "1,5,10-12"

# Translate a single page
python translate_pdf.py "input.pdf" "22"
```

### Interactive Mode

```bash
python translate_pdf.py
# Enter PDF file name/path: MyTextbook.pdf
# Enter page range (e.g. 1-5 or 3,7,10-12): 20-23
```

### Output

The translated PDF is saved alongside the original with a suffix:
```
input.pdf → input_hebrew_p20-23.pdf
```

If the output file is locked (e.g. open in a viewer), it saves as `*_new.pdf` instead.

## Running Tests

```bash
# Full QA suite (50 tests across 9 groups)
python test_translate_qa.py
```

Tests cover: bidi algorithm, font loading, live translation, equation/label skip logic, hyphenation merging, word wrapping, source PDF structure, module imports, and end-to-end translation with overlap detection.

### Diagnostic Tools

```bash
# Compare source vs translated page structure
python visual_compare.py

# Dump full text dict of source and output
python deep_inspect.py

# Inspect font sizes and positions in output
python inspect_output.py
```

## Project Structure

```
├── translate_pdf.py        # Main translation script
├── test_translate_qa.py    # QA test suite (50 tests)
├── visual_compare.py       # Source vs output structural comparison
├── deep_inspect.py         # Full text dict dump inspector
├── inspect_output.py       # Font/position inspector
├── CLAUDE.md               # Development progress log
├── docs/
│   ├── FUNCTIONAL.md       # Functional specification
│   └── MANUAL.md           # User manual
└── .gitignore
```

## How It Works

1. **Classify blocks** — Each text block is classified as equation (math fonts), label (≤3 chars), or body text
2. **Merge paragraphs** — All lines in a body text block are merged into one paragraph, rejoining hyphenated words
3. **Translate** — Paragraphs are sent to Ollama translategemma:12b via the chat API with a Hebrew-only system prompt
4. **Redact** — Original English text spans are whited out
5. **Render Hebrew** — Translated text is word-wrapped, converted to visual order (bidi), right-aligned, and placed at original line positions

## License

MIT
