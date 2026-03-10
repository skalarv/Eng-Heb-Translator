"""Deep comparison of source page 22 vs translated output."""
import fitz, sys
sys.stdout.reconfigure(encoding="utf-8")

print("=" * 80)
print("SOURCE PAGE 22 — Full text dict dump")
print("=" * 80)
doc = fitz.open("C:/BatchFiles/Books/Modern_Physics_by_Tipler_6th_edition.pdf")
page = doc[21]
td = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
blocks = td.get("blocks", [])

for i, b in enumerate(blocks):
    btype = "TEXT" if b["type"] == 0 else "IMAGE"
    if b["type"] == 1:
        bbox = b.get("bbox", [0,0,0,0])
        print(f"\nBlock {i} [{btype}] bbox=[{bbox[0]:.0f},{bbox[1]:.0f},{bbox[2]:.0f},{bbox[3]:.0f}] "
              f"size={b.get('width',0)}x{b.get('height',0)}")
        continue
    print(f"\nBlock {i} [{btype}]:")
    for j, line in enumerate(b["lines"]):
        spans_text = []
        for span in line["spans"]:
            t = span["text"]
            sz = span["size"]
            fn = span["font"]
            fl = span["flags"]
            bbox = span["bbox"]
            spans_text.append(f"  sz={sz:.1f} fl={fl} fn={fn[:18]:18s} "
                            f"bbox=[{bbox[0]:.0f},{bbox[1]:.0f},{bbox[2]:.0f},{bbox[3]:.0f}] "
                            f"'{t[:90]}'")
        for st in spans_text:
            print(st)

doc.close()

print("\n\n")
print("=" * 80)
print("OUTPUT PAGE 22 — Full text dict dump")
print("=" * 80)
doc = fitz.open("C:/BatchFiles/Books/Modern_Physics_by_Tipler_6th_edition_hebrew_p22.pdf")
page = doc[0]
td = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
blocks = td.get("blocks", [])

for i, b in enumerate(blocks):
    btype = "TEXT" if b["type"] == 0 else "IMAGE"
    if b["type"] == 1:
        bbox = b.get("bbox", [0,0,0,0])
        print(f"\nBlock {i} [{btype}] bbox=[{bbox[0]:.0f},{bbox[1]:.0f},{bbox[2]:.0f},{bbox[3]:.0f}] "
              f"size={b.get('width',0)}x{b.get('height',0)}")
        continue
    print(f"\nBlock {i} [{btype}]:")
    for j, line in enumerate(b["lines"]):
        for span in line["spans"]:
            t = span["text"]
            sz = span["size"]
            fn = span["font"]
            bbox = span["bbox"]
            print(f"  sz={sz:.1f} fn={fn[:18]:18s} "
                  f"bbox=[{bbox[0]:.0f},{bbox[1]:.0f},{bbox[2]:.0f},{bbox[3]:.0f}] "
                  f"'{t[:90]}'")
doc.close()
