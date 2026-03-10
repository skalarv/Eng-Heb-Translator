"""Visual comparison: source page 22 vs translated output."""
import fitz, sys
sys.stdout.reconfigure(encoding="utf-8")

MATH_FONTS = {"PearsonMATH", "MathematicalPi"}

def describe_block(b, label):
    if b["type"] == 1:
        bbox = b.get("bbox", [0,0,0,0])
        return f"  [{label}] IMAGE at [{bbox[0]:.0f},{bbox[1]:.0f},{bbox[2]:.0f},{bbox[3]:.0f}]"
    lines = []
    for line in b["lines"]:
        for span in line["spans"]:
            t = span["text"].strip()
            if t:
                is_math = any(mf in span["font"] for mf in MATH_FONTS)
                tag = "[MATH]" if is_math else ""
                lines.append(f"    sz={span['size']:.0f} fn={span['font'][:15]:15s} "
                           f"[{span['bbox'][0]:.0f},{span['bbox'][1]:.0f},"
                           f"{span['bbox'][2]:.0f},{span['bbox'][3]:.0f}] "
                           f"{tag} '{t[:70]}'")
    return "\n".join(lines) if lines else "    (empty)"


print("=" * 80)
print("VISUAL COMPARISON: Source page 22 vs Translated output")
print("=" * 80)

# Source
src = fitz.open("Modern_Physics_by_Tipler_6th_edition.pdf")
src_page = src[21]
src_td = src_page.get_text("dict")
src_blocks = src_td.get("blocks", [])

# Output
out = fitz.open("Modern_Physics_by_Tipler_6th_edition_hebrew_p22.pdf")
out_page = out[0]
out_td = out_page.get_text("dict")
out_blocks = out_td.get("blocks", [])

print(f"\nSource: {len(src_blocks)} blocks | Output: {len(out_blocks)} blocks")
print(f"Source page: {src_page.rect.width:.0f}x{src_page.rect.height:.0f} | "
      f"Output page: {out_page.rect.width:.0f}x{out_page.rect.height:.0f}")

# Check structural elements
print("\n--- STRUCTURAL CHECK ---")

# 1. Page number
print("\n[1] Page number:")
for b in out_blocks:
    if b["type"] != 0: continue
    for line in b["lines"]:
        for span in line["spans"]:
            if span["text"].strip() == "4" and span["bbox"][0] < 60:
                print(f"  OK: Page number '4' at [{span['bbox'][0]:.0f},{span['bbox'][1]:.0f}]")

# 2. Equations preserved
print("\n[2] Equations:")
eq_count = 0
for b in out_blocks:
    if b["type"] != 0: continue
    for line in b["lines"]:
        for span in line["spans"]:
            if any(mf in span["font"] for mf in MATH_FONTS):
                eq_count += 1
print(f"  Math-font spans in output: {eq_count}")
if eq_count > 0:
    print("  OK: Equations preserved in original fonts")
else:
    print("  PROBLEM: No math fonts found - equations may be lost")

# 3. Figure/images preserved
print("\n[3] Images:")
src_imgs = [b for b in src_blocks if b["type"] == 1]
out_imgs = [b for b in out_blocks if b["type"] == 1]
print(f"  Source images: {len(src_imgs)} | Output images: {len(out_imgs)}")
if len(out_imgs) >= len(src_imgs):
    print("  OK: Images preserved")

# 4. Axis labels preserved
print("\n[4] Figure axis labels (y,S,x,z,v near figure):")
for b in out_blocks:
    if b["type"] != 0: continue
    for line in b["lines"]:
        for span in line["spans"]:
            t = span["text"].strip()
            y = span["bbox"][1]
            if t and len(t) <= 3 and y > 480 and span["size"] <= 9:
                has_heb = any("\u0590" <= c <= "\u05FF" for c in t)
                status = "PROBLEM (Hebrew!)" if has_heb else "OK (original)"
                print(f"  '{t}' at y={y:.0f} sz={span['size']:.0f} -> {status}")

# 5. Hebrew body text
print("\n[5] Hebrew body text sample:")
heb_lines = []
for b in out_blocks:
    if b["type"] != 0: continue
    for line in b["lines"]:
        for span in line["spans"]:
            t = span["text"].strip()
            if t and any("\u0590" <= c <= "\u05FF" for c in t) and span["size"] == 10:
                heb_lines.append(f"  y={span['bbox'][1]:.0f} '{t[:80]}'")
for hl in heb_lines[:8]:
    print(hl)
print(f"  ... total Hebrew body lines: {len(heb_lines)}")

# 6. Font size consistency
print("\n[6] Hebrew text font sizes:")
sizes = {}
for b in out_blocks:
    if b["type"] != 0: continue
    for line in b["lines"]:
        for span in line["spans"]:
            t = span["text"].strip()
            if t and any("\u0590" <= c <= "\u05FF" for c in t):
                sz = round(span["size"], 1)
                sizes[sz] = sizes.get(sz, 0) + 1
for sz in sorted(sizes):
    print(f"  {sz}pt: {sizes[sz]} spans")

# 7. Check for model apology text
print("\n[7] Model apology check:")
full_text = out_page.get_text()
if "מצטער" in full_text:
    print("  PROBLEM: Found 'מצטער' (sorry) - model refused some translations")
else:
    print("  OK: No apology text found")

# 8. Overall layout comparison
print("\n[8] Y-position coverage:")
src_y_range = [999, 0]
out_y_range = [999, 0]
for b in src_blocks:
    if b["type"] != 0: continue
    for line in b["lines"]:
        for span in line["spans"]:
            if span["text"].strip():
                src_y_range[0] = min(src_y_range[0], span["bbox"][1])
                src_y_range[1] = max(src_y_range[1], span["bbox"][3])
for b in out_blocks:
    if b["type"] != 0: continue
    for line in b["lines"]:
        for span in line["spans"]:
            if span["text"].strip():
                out_y_range[0] = min(out_y_range[0], span["bbox"][1])
                out_y_range[1] = max(out_y_range[1], span["bbox"][3])
print(f"  Source text y-range: {src_y_range[0]:.0f} - {src_y_range[1]:.0f}")
print(f"  Output text y-range: {out_y_range[0]:.0f} - {out_y_range[1]:.0f}")

src.close()
out.close()
print("\nDone.")
