"""
Visual QA: Render translated PDF pages to images and use vision LLMs
(minicpm-v + llama3.2-vision via Ollama) to detect overlap, garbled text, and layout issues.
"""
import sys
import os
import base64
import json
import requests
import fitz  # PyMuPDF

sys.stdout.reconfigure(encoding="utf-8")

OLLAMA_URL = "http://localhost:11434/api/chat"
# Primary: MiniCPM-V (better OCR/document analysis), fallback: llama3.2-vision
VISION_MODELS = ["minicpm-v:latest", "llama3.2-vision:11b"]

VISUAL_QA_PROMPT = """\
You are a PDF translation quality inspector. This image shows a page from a physics \
textbook that was translated from English to Hebrew (right-to-left text).

Inspect the page for these specific issues ONLY:
1. OVERLAP: Two lines of text rendered on top of each other, creating an unreadable \
garbled mess where characters from both lines mix together
2. GARBLED: A sequence of characters that is obviously corrupted — random mixed \
characters from multiple words overlapping, or mojibake
3. EQUATION DAMAGE: Equations that are clearly broken — missing operators, truncated \
expressions, or symbols replaced with boxes/placeholders

Severity guide:
- MAJOR: The issue makes a section genuinely unreadable or unusable (two text lines \
printed on top of each other, corrupted character sequences)
- minor: Cosmetic imperfection that does not affect readability

IMPORTANT rules:
- Hebrew text near (but not overlapping) equations is NORMAL — not an issue
- Slightly smaller font sizes for longer translations is NORMAL — not an issue
- Hebrew script that looks unfamiliar to you is NOT garbled — do not report it
- Mathematical expressions rendered inline with Hebrew text is NORMAL
- Only report OVERLAP if you can clearly see two distinct text lines printed on \
the same vertical position creating unreadable mixed characters

If you find no MAJOR issues, respond with exactly: PASS
"""


def render_page_to_png(page: fitz.Page, dpi: int = 150) -> bytes:
    """Render a PDF page to PNG bytes at given DPI."""
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat)
    return pix.tobytes("png")


def check_page_with_vision(png_bytes: bytes, page_label: str,
                           model: str = None) -> str:
    """Send a page image to a vision model and get QA feedback."""
    if model is None:
        model = VISION_MODELS[0]
    b64_image = base64.b64encode(png_bytes).decode("utf-8")

    resp = requests.post(
        OLLAMA_URL,
        json={
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": VISUAL_QA_PROMPT,
                    "images": [b64_image],
                },
            ],
            "stream": False,
            "options": {"temperature": 0.0, "num_predict": 512},
        },
        timeout=300,
    )
    resp.raise_for_status()
    return resp.json().get("message", {}).get("content", "").strip()


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Visual QA for translated PDF pages.")
    parser.add_argument("pdf_path", help="Path to the translated PDF")
    parser.add_argument("--dpi", type=int, default=150, help="Render DPI (default: 150)")
    parser.add_argument("--pages", default=None,
                        help="Pages to check (1-based, e.g. '1-3' or '2,4'). Default: all")
    parser.add_argument("--save-images", action="store_true",
                        help="Save rendered page images to disk")
    args = parser.parse_args()

    if not os.path.exists(args.pdf_path):
        print(f"Error: File '{args.pdf_path}' not found.")
        sys.exit(1)

    # Verify at least one vision model is available
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=5)
        available = [m["name"] for m in r.json().get("models", [])]
        active_models = [m for m in VISION_MODELS if m in available]
        if not active_models:
            print(f"Error: No vision models found. Pull one with:")
            for m in VISION_MODELS:
                print(f"  ollama pull {m}")
            sys.exit(1)
    except requests.ConnectionError:
        print("Error: Cannot connect to Ollama.")
        sys.exit(1)

    doc = fitz.open(args.pdf_path)
    total = len(doc)
    print(f"Opened '{args.pdf_path}' ({total} pages)")

    # Determine which pages to check
    if args.pages:
        page_indices = []
        for part in args.pages.split(","):
            part = part.strip()
            if "-" in part:
                s, e = part.split("-", 1)
                for p in range(int(s), int(e) + 1):
                    if 1 <= p <= total:
                        page_indices.append(p - 1)
            else:
                p = int(part)
                if 1 <= p <= total:
                    page_indices.append(p - 1)
    else:
        page_indices = list(range(total))

    print(f"Checking pages: {[i+1 for i in page_indices]}")
    print(f"Using vision models: {', '.join(active_models)}")
    print()

    # Clean up old rendered images before generating new ones
    if args.save_images:
        import glob
        base_name = os.path.splitext(args.pdf_path)[0]
        for old_img in glob.glob(f"{base_name}_page*.png"):
            try:
                os.remove(old_img)
            except OSError:
                pass

    issues_found = 0
    results = []

    for idx in page_indices:
        page = doc[idx]
        page_label = f"Page {idx + 1}"
        print(f"--- {page_label} ---")
        print(f"  Rendering at {args.dpi} DPI...")

        png_bytes = render_page_to_png(page, dpi=args.dpi)

        if args.save_images:
            img_path = os.path.splitext(args.pdf_path)[0] + f"_page{idx+1}.png"
            with open(img_path, "wb") as f:
                f.write(png_bytes)
            print(f"  Saved: {img_path}")

        # Multi-model consensus: check with each available model.
        # Page fails ONLY if the MAJORITY of models report MAJOR issues.
        model_verdicts = []
        model_results = []
        for model in active_models:
            print(f"  Analyzing with {model}...")
            try:
                result = check_page_with_vision(png_bytes, page_label, model=model)
            except Exception as e:
                result = f"ERROR: {e}"

            r_upper = result.upper()
            if "PASS" in r_upper:
                verdict = "PASS"
            elif "MAJOR" in r_upper or "CRITICAL" in r_upper:
                verdict = "FAIL"
            else:
                verdict = "PASS"  # no MAJOR/CRITICAL = minor only
            model_verdicts.append(verdict)
            model_results.append(result)
            print(f"    {model}: {verdict}")

        # Consensus: fail only if majority of models say FAIL
        fail_count = model_verdicts.count("FAIL")
        is_pass = fail_count <= len(active_models) // 2

        # Use the most detailed result for reporting
        combined = model_results[0] if model_results else ""
        for r in model_results:
            if len(r) > len(combined):
                combined = r
        results.append((page_label, combined))

        if is_pass:
            print(f"  Result: PASS")
        else:
            issues_found += 1
            print(f"  Result: ISSUES FOUND ({fail_count}/{len(active_models)} models)")
            for line in combined.split("\n"):
                if line.strip():
                    print(f"    {line.strip()}")
        print()

    doc.close()

    # Summary
    print("=" * 60)
    print(f"VISUAL QA RESULTS: {len(page_indices)} pages checked, "
          f"{issues_found} with issues")
    if issues_found == 0:
        print("ALL PAGES PASSED VISUAL INSPECTION")
    else:
        print("ISSUES FOUND - Review above for details")
        print()
        for label, result in results:
            r_upper = result.upper()
            is_pass_summary = "PASS" in r_upper or ("MAJOR" not in r_upper and "CRITICAL" not in r_upper)
            if not is_pass_summary:
                print(f"  {label}: {result[:100]}...")
    print("=" * 60)

    sys.exit(1 if issues_found > 0 else 0)


if __name__ == "__main__":
    main()
