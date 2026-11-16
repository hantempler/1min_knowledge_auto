import os
import sys
import json
import re
import cv2
from PIL import Image, ImageDraw, ImageFont

ROOT_DIR = r"g:\내 드라이브\2_프로젝트\PRJ_1min_knowledge"
DATA_DIR = os.path.join(ROOT_DIR, "data")
DATE_STR = "2026-11-16"
OUT_DIR = os.path.join(DATA_DIR, "layout_test", "10_scenes_verified")
os.makedirs(OUT_DIR, exist_ok=True)

FONT_PATH = os.path.join(ROOT_DIR, "config", "GmarketSansTTFBold.ttf")
if not os.path.exists(FONT_PATH):
    FONT_PATH = "C:/Windows/Fonts/malgunbd.ttf"

# 1. 대본 및 소싱 리포트 로드
script_path = os.path.join(DATA_DIR, f"script_{DATE_STR.replace('-', '')}.json")
report_path = os.path.join(DATA_DIR, DATE_STR, "temp", "asset_sourcing_report.json")

with open(script_path, "r", encoding="utf-8") as f:
    script_data = json.load(f)

with open(report_path, "r", encoding="utf-8") as f:
    assets_data = json.load(f)

sections = script_data.get("sections", [])
article_q = script_data.get("article_question", "비만치료제 오젬픽이 정말 실명을 유발할까?")

# 폰트 로드
font_brand = ImageFont.truetype(FONT_PATH, 36)
font_q = ImageFont.truetype(FONT_PATH, 54)        # 헤더: 54pt 확대, 1행/2행 동일 크기
font_callout = ImageFont.truetype(FONT_PATH, 62)  # 중앙 레드 콜아웃
font_sub = ImageFont.truetype(FONT_PATH, 48)      # 하단 자막

# <hl> 파싱 함수
def parse_hl_text(text: str) -> list:
    tokens = re.split(r'(</?hl>)', text)
    parts = []
    is_hl = False
    for tok in tokens:
        if not tok:
            continue
        if tok == "<hl>":
            is_hl = True
        elif tok == "</hl>":
            is_hl = False
        else:
            clean_tok = tok.replace("<hl>", "").replace("</hl>", "")
            if clean_tok:
                parts.append((clean_tok, is_hl))
    return parts

# 자막 2줄 분할 함수
def format_subtitle_lines(text: str, max_chars_per_line: int = 18) -> list:
    text = text.strip().replace("\n", " ")
    v_len = len(re.sub(r'<.*?>', '', text))
    if v_len <= max_chars_per_line:
        return [text]
    words = text.split()
    if len(words) <= 2:
        return [text]
    best_split = len(words) // 2
    min_diff = 9999
    for i in range(1, len(words)):
        prefix = " ".join(words[:i])
        open_tags = prefix.count("<hl>")
        close_tags = prefix.count("</hl>")
        is_inside_tag = (open_tags > close_tags)
        l1 = prefix
        l2 = " ".join(words[i:])
        v1 = len(re.sub(r'<.*?>', '', l1))
        v2 = len(re.sub(r'<.*?>', '', l2))
        awkward = 500 if is_inside_tag else 0
        diff = abs(v1 - v2) + awkward
        if diff < min_diff:
            min_diff = diff
            best_split = i
    l1 = " ".join(words[:best_split])
    l2 = " ".join(words[best_split:])
    if l1.count("<hl>") > l1.count("</hl>"):
        l1 = l1 + "</hl>"
        l2 = "<hl>" + l2
    return [l1, l2]

# 질문 헤더 2줄 (사용자 지시: 전체 노란색)
q_line1 = "비만치료제 오젬픽이"
q_line2 = "정말 실명을 유발할까?"

print("=" * 80)
print(f"🎬 [레이아웃] 출처 표기 전면 제외 + 좌측 라벨 + 확대 옐로우 헤더 10개 씬 렌더링")
print("=" * 80)

generated_files = []

for idx in range(len(sections)):
    c_no = idx + 1
    sec = sections[idx]
    asset = assets_data[idx]
    
    sub_text = sec.get("subtitle", "")
    kw = sec.get("core_keyword", "")
    
    # 베이스 이미지 확보 (1080x1920)
    asset_path = asset.get("path")
    if not os.path.isabs(asset_path):
        asset_path = os.path.join(ROOT_DIR, asset_path)
        
    canvas = None
    if asset["type"] == "video" or asset_path.endswith(".mp4"):
        cap = cv2.VideoCapture(asset_path)
        fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(fps * 1.5))
        ret, frame = cap.read()
        cap.release()
        if ret:
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            canvas = Image.fromarray(frame_rgb).resize((1080, 1920), Image.Resampling.LANCZOS)
        else:
            canvas = Image.new("RGB", (1080, 1920), (20, 20, 20))
    else:
        if os.path.exists(asset_path):
            im = Image.open(asset_path).convert("RGB")
            if im.size != (1080, 1920):
                im = im.resize((1080, 1920), Image.Resampling.LANCZOS)
            canvas = im
        else:
            canvas = Image.new("RGB", (1080, 1920), (20, 20, 20))

    # 오버레이 레이어 생성 (RGBA)
    ov = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    draw = ImageDraw.Draw(ov)

    # 1. 상단 은은한 딤 비네팅 (y: 0~380)
    for y in range(380):
        alpha = int(175 * (1 - y / 380) ** 1.4)
        draw.line([(0, y), (1080, y)], fill=(0, 0, 0, alpha))

    # 2. 하단 자막 영역 딤 비네팅 (y: 1220~1660)
    for y in range(1220, 1660):
        rel = 1 - abs(y - 1440) / 220.0
        alpha = int(155 * max(0, rel))
        draw.line([(0, y), (1080, y)], fill=(0, 0, 0, alpha))

    # -------------------------------------------------------------
    # [라벨] 참조 코드 규격: 좌측 상단 골드 불릿(●) + Gmarket Sans TTF Bold 36pt
    # -------------------------------------------------------------
    brand_y = 95
    gold_color = (255, 204, 0)
    draw.ellipse([60, brand_y - 9, 78, brand_y + 9], fill=gold_color)
    draw.text((92, brand_y), "1분상식", fill=(245, 245, 250), font=font_brand, anchor="lm")

    # -------------------------------------------------------------
    # [상단 헤더] 전체 노란색(#FFE600), 동일 54pt 확대, 6px 블랙 스트로크
    # -------------------------------------------------------------
    lw1 = draw.textlength(q_line1, font=font_q)
    draw.text(((1080 - lw1) / 2, 150), q_line1, font=font_q, fill=(255, 230, 0), stroke_width=6, stroke_fill=(0, 0, 0, 240))
    
    lw2 = draw.textlength(q_line2, font=font_q)
    draw.text(((1080 - lw2) / 2, 215), q_line2, font=font_q, fill=(255, 230, 0), stroke_width=6, stroke_fill=(0, 0, 0, 240))

    # -------------------------------------------------------------
    # [출처 표기] 사용자 지시: 출처 완전 제외 (표시 안 함)
    # -------------------------------------------------------------

    # -------------------------------------------------------------
    # [중앙 콜아웃] 62pt 레드(#FF2A2A) + 8px 블랙 스트로크 (y=690)
    # -------------------------------------------------------------
    if kw:
        cw = draw.textlength(kw, font=font_callout)
        cx = (1080 - cw) / 2
        cy = 690
        draw.text((cx, cy), kw, font=font_callout, fill=(255, 42, 42), stroke_width=8, stroke_fill=(0, 0, 0, 240))

    # -------------------------------------------------------------
    # [하단 자막] 48pt 고정 2줄, <hl> 노란색(#FFE600) + 화이트(#FFFFFF), 6px 스트로크
    # -------------------------------------------------------------
    lines = format_subtitle_lines(sub_text, max_chars_per_line=18)
    if len(lines) == 1:
        y_positions = [1375]
    else:
        y_positions = [1340, 1410]

    for l_idx, line in enumerate(lines[:2]):
        segs = parse_hl_text(line)
        line_w = sum(draw.textlength(text, font=font_sub) for text, is_hl in segs)
        start_x = (1080 - line_w) / 2
        cur_x = start_x
        y_pos = y_positions[l_idx]

        for text, is_hl in segs:
            col = "#FFE600" if is_hl else "#FFFFFF"
            draw.text((cur_x, y_pos), text, font=font_sub, fill=col, stroke_width=6, stroke_fill=(0, 0, 0, 255))
            cur_x += draw.textlength(text, font=font_sub)

    # 최종 합성 및 저장
    final_img = Image.alpha_composite(canvas.convert("RGBA"), ov).convert("RGB")
    out_file = os.path.join(OUT_DIR, f"scene_{c_no:02d}_verified.jpg")
    final_img.save(out_file, quality=95)
    generated_files.append(out_file)
    print(f"  ✓ [Scene {c_no:02d}/10 완성] -> {os.path.basename(out_file)} (콜아웃: '{kw}', 출처: 제외)")

print("\n" + "=" * 80)
print(f"🎉 10개 씬 전수 렌더링 완료! (출처 제외, 깔끔한 화면 구성)")
print("=" * 80)
