"""
Visual comparison: render source and translated pages side by side,
check that layout, equations, images, and labels are preserved.
"""
import sys
import os
import fitz

sys.stdout.reconfigure(encoding="utf-8")

MATH_FONTS = {"PearsonMATH", "MathematicalPi"}


def compare_pages(src_page, out_page, page_num):
    """Compare source and output page structure. Returns list of issues."""
    issues = []
    src_td = src_page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
    out_td = out_page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
    src_blocks = src_td.get("blocks", [])
    out_blocks = out_td.get("blocks", [])

    # 1. Page dimensions must match
    if abs(src_page.rect.width - out_page.rect.width) > 1 or \
       abs(src_page.rect.height - out_page.rect.height) > 1:
        issues.append(f"Page size mismatch: src={src_page.rect.width:.0f}x{src_page.rect.height:.0f} "
                      f"out={out_page.rect.width:.0f}x{out_page.rect.height:.0f}")

    # 2. Images preserved
    src_imgs = [b for b in src_blocks if b["type"] == 1]
    out_imgs = [b for b in out_blocks if b["type"] == 1]
    if len(out_imgs) < len(src_imgs):
        issues.append(f"Images lost: src={len(src_imgs)} out={len(out_imgs)}")

    # 3. Equation fonts preserved (math-font spans should exist in output)
    src_math = 0
    out_math = 0
    for b in src_blocks:
        if b["type"] != 0:
            continue
        for line in b["lines"]:
            for span in line["spans"]:
                if any(mf in span["font"] for mf in MATH_FONTS) and span["text"].strip():
                    src_math += 1
    for b in out_blocks:
        if b["type"] != 0:
            continue
        for line in b["lines"]:
            for span in line["spans"]:
                if any(mf in span["font"] for mf in MATH_FONTS) and span["text"].strip():
                    out_math += 1
    if src_math > 0 and out_math == 0:
        issues.append(f"All equation fonts lost: src={src_math} math spans, out=0")
    elif src_math > 0 and out_math < src_math * 0.5:
        issues.append(f"Many equation fonts lost: src={src_math} out={out_math}")

    # 4. Axis labels preserved (short labels <=3 chars near figures)
    src_labels = set()
    out_labels = set()
    for b in src_blocks:
        if b["type"] != 0:
            continue
        for line in b["lines"]:
            for span in line["spans"]:
                t = span["text"].strip()
                if t and len(t) <= 3 and not any("\u0590" <= c <= "\u05FF" for c in t):
                    src_labels.add(t)
    for b in out_blocks:
        if b["type"] != 0:
            continue
        for line in b["lines"]:
            for span in line["spans"]:
                t = span["text"].strip()
                if t and len(t) <= 3 and not any("\u0590" <= c <= "\u05FF" for c in t):
                    out_labels.add(t)
    lost_labels = src_labels - out_labels
    if lost_labels:
        issues.append(f"Labels lost: {lost_labels}")

    # 5. Output has Hebrew text
    out_text = out_page.get_text()
    has_hebrew = any("\u0590" <= c <= "\u05FF" for c in out_text)
    if not has_hebrew:
        issues.append("No Hebrew text found in output")

    # 6. Check for S9 (should be S')
    if "S9" in out_text:
        issues.append("Found 'S9' instead of \"S'\" — prime fix not applied")

    # 7. Check for model apology
    if "\u05de\u05e6\u05d8\u05e2\u05e8" in out_text:  # מצטער
        issues.append("Found model apology text")

    # 8. Y-range coverage (text should span similar vertical range)
    def y_range(blocks):
        ymin, ymax = 999, 0
        for b in blocks:
            if b["type"] != 0:
                continue
            for line in b["lines"]:
                for span in line["spans"]:
                    if span["text"].strip():
                        ymin = min(ymin, span["bbox"][1])
                        ymax = max(ymax, span["bbox"][3])
        return ymin, ymax

    src_yr = y_range(src_blocks)
    out_yr = y_range(out_blocks)
    if abs(src_yr[0] - out_yr[0]) > 20:
        issues.append(f"Y-start shifted: src={src_yr[0]:.0f} out={out_yr[0]:.0f}")
    if abs(src_yr[1] - out_yr[1]) > 30:
        issues.append(f"Y-end shifted: src={src_yr[1]:.0f} out={out_yr[1]:.0f}")

    # 9. Visual overlap detection: check if any two Hebrew text blocks overlap
    heb_rects = []
    for b in out_blocks:
        if b["type"] != 0:
            continue
        for line in b["lines"]:
            for span in line["spans"]:
                t = span["text"].strip()
                if t and any("\u0590" <= c <= "\u05FF" for c in t):
                    heb_rects.append(span["bbox"])
    overlap_count = 0
    for i in range(len(heb_rects)):
        for j in range(i + 1, len(heb_rects)):
            r1, r2 = heb_rects[i], heb_rects[j]
            # Check vertical overlap (>3pt) AND horizontal overlap
            v_overlap = min(r1[3], r2[3]) - max(r1[1], r2[1])
            h_overlap = min(r1[2], r2[2]) - max(r1[0], r2[0])
            if v_overlap > 3 and h_overlap > 5:
                overlap_count += 1
    if overlap_count > 0:
        issues.append(f"Hebrew text overlap detected: {overlap_count} overlapping pairs")

    # 10. Render both pages and save comparison image
    return issues


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Compare source and translated PDF pages.")
    parser.add_argument("source_pdf", help="Path to source PDF")
    parser.add_argument("output_pdf", help="Path to translated output PDF")
    parser.add_argument("--pages", default=None,
                        help="Source page range that was translated (e.g. '20-25')")
    parser.add_argument("--save-images", action="store_true",
                        help="Save side-by-side comparison images")
    args = parser.parse_args()

    src_doc = fitz.open(args.source_pdf)
    out_doc = fitz.open(args.output_pdf)

    # Determine page mapping
    total_out = len(out_doc)
    if args.pages:
        from translate_pdf import parse_page_range
        src_indices = parse_page_range(args.pages, len(src_doc))
    else:
        src_indices = list(range(total_out))

    if len(src_indices) != total_out:
        print(f"Warning: {len(src_indices)} source pages vs {total_out} output pages")
        src_indices = src_indices[:total_out]

    print(f"Comparing {total_out} pages...")
    print()

    total_issues = 0
    for out_idx in range(total_out):
        src_idx = src_indices[out_idx]
        src_page = src_doc[src_idx]
        out_page = out_doc[out_idx]
        page_label = f"Page {src_idx + 1}"
        print(f"--- {page_label} (output page {out_idx + 1}) ---")

        issues = compare_pages(src_page, out_page, src_idx + 1)

        if args.save_images:
            # Render side-by-side
            dpi = 100
            mat = fitz.Matrix(dpi / 72, dpi / 72)
            src_pix = src_page.get_pixmap(matrix=mat)
            out_pix = out_page.get_pixmap(matrix=mat)

            # Create combined image
            w = src_pix.width + out_pix.width + 4
            h = max(src_pix.height, out_pix.height)
            combined = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, w, h), 1)
            combined.set_rect(fitz.IRect(0, 0, w, h), (255, 255, 255))
            combined.set_rect(fitz.IRect(src_pix.width, 0, src_pix.width + 4, h), (200, 0, 0))
            # Copy source on left
            combined.copy(src_pix, fitz.IRect(0, 0, src_pix.width, src_pix.height))
            # Copy output on right
            combined.copy(out_pix, fitz.IRect(src_pix.width + 4, 0,
                                               src_pix.width + 4 + out_pix.width, out_pix.height))

            img_path = os.path.splitext(args.output_pdf)[0] + f"_compare_p{src_idx+1}.png"
            combined.save(img_path)
            print(f"  Saved comparison: {img_path}")

        if issues:
            total_issues += len(issues)
            for issue in issues:
                print(f"  ISSUE: {issue}")
        else:
            print(f"  OK: Layout matches source")
        print()

    src_doc.close()
    out_doc.close()

    # Summary
    print("=" * 60)
    if total_issues == 0:
        print(f"COMPARISON RESULTS: {total_out} pages checked, ALL MATCH SOURCE")
    else:
        print(f"COMPARISON RESULTS: {total_out} pages checked, {total_issues} issues found")
    print("=" * 60)
    sys.exit(1 if total_issues > 0 else 0)


if __name__ == "__main__":
    main()
