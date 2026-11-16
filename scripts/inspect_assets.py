import os, json
from PIL import Image

report_path = "data/2026-11-16/temp/asset_sourcing_report.json"
with open(report_path, "r", encoding="utf-8") as f:
    assets = json.load(f)

for item in assets:
    p = item["path"]
    if os.path.exists(p):
        if p.endswith(".mp4"):
            print(f"Cut {item['cut_no']:02d}: Video {p}")
        else:
            im = Image.open(p)
            print(f"Cut {item['cut_no']:02d}: Image size {im.size}, type {item['type']}, path {p}")
    else:
        print(f"Cut {item['cut_no']:02d}: NOT FOUND {p}")
