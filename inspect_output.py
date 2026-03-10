import fitz, sys
sys.stdout.reconfigure(encoding="utf-8")

# Inspect current output
doc = fitz.open("C:/BatchFiles/Books/Modern_Physics_by_Tipler_6th_edition_hebrew_p20_new.pdf")
page = doc[0]
td = page.get_text("dict")

print("=== Output PDF: All text spans ===")
for b in td.get("blocks", []):
    if b["type"] != 0:
        continue
    for line in b["lines"]:
        for span in line["spans"]:
            t = span["text"].strip()
            if not t:
                continue
            bbox = span["bbox"]
            w = bbox[2] - bbox[0]
            print(f"  fsize={span['size']:5.1f} rect_w={w:6.1f} font={span['font'][:20]:20s} | {t[:80]}")
doc.close()

print("\n\n=== Source PDF page 20: All text spans ===")
doc = fitz.open("C:/BatchFiles/Books/Modern_Physics_by_Tipler_6th_edition.pdf")
page = doc[19]
td = page.get_text("dict")
for b in td.get("blocks", []):
    if b["type"] != 0:
        continue
    for line in b["lines"]:
        for span in line["spans"]:
            t = span["text"].strip()
            if not t:
                continue
            bbox = span["bbox"]
            w = bbox[2] - bbox[0]
            print(f"  fsize={span['size']:5.1f} rect_w={w:6.1f} font={span['font'][:20]:20s} | {t[:80]}")
doc.close()
