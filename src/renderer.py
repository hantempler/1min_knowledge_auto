# -*- coding: utf-8 -*-
"""
[Step 5] 3단 상시 인식 헤더 & 48pt 하이라이트 자막 렌더러
- 상단 3단 일체형 뉴스 앵커 UI (영상 내내 100% 상시 고정):
  * Line 1: [언론사명] 오늘 왜 이 상식? (옐로우 #FFE600, 28pt)
  * Line 2: Q. {기사 핵심 질문} (화이트 볼드 #FFFFFF, 36~38pt, 화면 안전 너비 900px 제한)
  * Line 3: 01~04 단계별 해답 인디케이터 (스카이블루 #38BDF8, 30pt)
- Pillow 기반 48pt 고정, 7px 블랙 스트로크 자막 생성
  * 기본 텍스트: 화이트 (#FFFFFF)
  * <hl> 태그: 옐로우 (#FFE600)
  * 안전 마진 880px 체크 (좌우 최소 100px 여백 보장, 잘림 원천 방지)
- 불필요한 엔딩 페이지 완전 삭제 (나레이션 종료 시점에 맞춰 0.35s 자연스러운 페이드아웃)
- gemini-nano-banana-2.1 기반 텍스트 프리(NO text) 9:16 실사 이미지 생성
- FFmpeg 줌팬 모션 인코딩 + BGM 믹싱
- 씬별 중간 프레임(frame_s0~s3.jpg) 자동 추출
"""
import os
import sys
import json
import time
import re
import shutil
import subprocess
from PIL import Image, ImageDraw, ImageFont
from google import genai
from google.genai import types

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
import config

def get_font_path() -> str:
    candidates = [
        getattr(config, "FONT_PATH", ""),
        os.path.join(config.CONFIG_DIR, "GmarketSansTTFBold.ttf"),
        os.path.join(config.BASE_DIR, "production", "config", "GmarketSansTTFBold.ttf"),
    ]
    for p in candidates:
        if p and os.path.exists(p):
            return p
    return candidates[0]

BGM_TRACKS = {
    # 1. 경쾌/활기 (일상 꿀팁, 빠른 템포 지식)
    "sunspots": "Sunspots - Jeremy Blake.mp3",
    "upbeat": "Sunspots - Jeremy Blake.mp3",
    "fast": "Sunspots - Jeremy Blake.mp3",

    # 2. 긴장/경고/공포/위기 (질병, 생존, 충격 팩트)
    "beyond": "Beyond - Patrick Patrikios.mp3",
    "danger": "Beyond - Patrick Patrikios.mp3",
    "warning": "Beyond - Patrick Patrikios.mp3",
    "dark": "Beyond - Patrick Patrikios.mp3",

    # 3. 신비/우주/미스터리/첨단 (과학 기술, 인체 심층)
    "night_snow": "Night Snow - Asher Fulero.mp3",
    "mystery": "Night Snow - Asher Fulero.mp3",
    "science": "Night Snow - Asher Fulero.mp3",

    # 4. 차분/지적/다큐멘터리/팩트체크 (금융/경제, 제도, 정책)
    "quiet_thought": "A Quiet Thought - Wayne Jones.mp3",
    "documentary": "A Quiet Thought - Wayne Jones.mp3",
    "calm": "A Quiet Thought - Wayne Jones.mp3",

    # 5. 서정/감성/인문/스토리 (심리, 감동, 휴먼)
    "one_step": "One Step Closer - Aakash Gandhi.mp3",
    "emotional": "One Step Closer - Aakash Gandhi.mp3",
    "piano": "One Step Closer - Aakash Gandhi.mp3",

    # 6. 자연/식품/웰빙/어쿠스틱 (자연 친화, 건강 꿀팁)
    "blue_creek": "Blue Creek Trail - Dan Lebowitz.mp3",
    "nature": "Blue Creek Trail - Dan Lebowitz.mp3",
    "acoustic": "Blue Creek Trail - Dan Lebowitz.mp3",
}

# 주제 카테고리별 최적 무드 음원 자동 매칭 맵
CATEGORY_BGM_MAP = {
    # 인체·건강 공포, 생존 위기, 질병 경고 -> 긴장감과 묵직한 베이스의 시네마틱 톤
    "의료/건강": "Beyond - Patrick Patrikios.mp3",
    # 팩트체크, 금융/경제 덫, 세금/환급, 제도 분석 -> 지적이고 신뢰감 있는 다큐 스타일
    "금융/경제": "A Quiet Thought - Wayne Jones.mp3",
    # 첨단 기술, 우주/미스터리, 심층 과학 원리 -> 차분하고 몽환적인 신비 톤
    "과학/기술": "Night Snow - Asher Fulero.mp3",
    # 일상 습관 상식 파괴, 생활 꿀팁 -> 경쾌하고 빠른 비트
    "생활/안전": "Sunspots - Jeremy Blake.mp3",
}

def resolve_bgm_track(
    category: str = None,
    bgm_override: str = None,
    date_str: str = None
) -> str:
    """
    BGM 음원 자동 선정 및 오버라이드 해석:
    1. bgm_override가 직접 지정된 경우(파일명 또는 단축 키워드) 최우선 반영
    2. 주제 카테고리(의료/건강, 금융/경제, 과학/기술, 생활/안전)에 최적화된 분위기 매칭
    3. 미지정 또는 매칭 실패 시, 날짜(YYYY-MM-DD) 해시 로테이션으로 6개 음원 골고루 순환
    """
    # 1. 수동 오버라이드 확인
    if bgm_override and bgm_override.lower() not in ("auto", "none", ""):
        low = bgm_override.lower().strip()
        for k, fname in BGM_TRACKS.items():
            if low == k or low in fname.lower():
                return fname
        if bgm_override.endswith(".mp3"):
            return bgm_override

    # 2. 카테고리 기반 분위기 매칭
    if category:
        for cat_key, fname in CATEGORY_BGM_MAP.items():
            if cat_key in category:
                return fname

    # 3. 날짜 기반 6곡 순환 로테이션 (중복 방지)
    unique_tracks = sorted(list(set(BGM_TRACKS.values())))
    if date_str:
        clean = date_str.replace("-", "").strip()
        try:
            idx = int(clean) % len(unique_tracks)
            return unique_tracks[idx]
        except ValueError:
            pass

    return "Sunspots - Jeremy Blake.mp3"

def get_bgm_path(bgm_filename: str = None) -> str:
    """BGM 파일명으로 실제 경로를 탐색하고 유효한 경로 반환 (부재 시 None)"""
    target = bgm_filename or "Sunspots - Jeremy Blake.mp3"
    candidates = [
        os.path.join(getattr(config, "AUDIO_DIR", ""), target),
        os.path.join(config.BASE_DIR, "assets", "audio", target),
        os.path.join(config.BASE_DIR, "production", "assets", "audio", target),
    ]
    for p in candidates:
        if p and os.path.exists(p):
            return p
    # 파일이 없는 경우 assets/audio 폴더 내 첫 번째 mp3로 fallback
    fallback_dir = os.path.join(config.BASE_DIR, "assets", "audio")
    if os.path.exists(fallback_dir):
        files = [f for f in os.listdir(fallback_dir) if f.endswith(".mp3")]
        if files:
            return os.path.join(fallback_dir, files[0])
    return None

def visible_len(text: str) -> int:
    """<hl> 태그를 제외한 실제 화면 노출 글자 수 계산"""
    return len(re.sub(r'<.*?>', '', text))

def parse_hl_text(text: str) -> list:
    """<hl>태그를 상태 기반으로 파싱하여 (문자열, is_highlight) 튜플 리스트 반환.
    태그가 비정상적으로 닫히지 않았거나 남은 경우에도 화면에 태그 문자가 절대 노출되지 않도록 완전 방어."""
    parts = []
    tokens = re.split(r'(</?hl>)', text)
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

def format_subtitle_lines(text: str, max_chars_per_line: int = 18) -> list:
    """쇼츠 표준 자막: 무조건 1~2줄로 자연스러운 의미 단위 분할 (3줄 원천 차단)."""
    text = text.strip().replace("\n", " ")
    v_len = visible_len(text)
    if v_len <= max_chars_per_line:
        return [text]

    words = text.split()
    if len(words) <= 2:
        return [text]

    # 의미와 가로 너비 균형에 맞춘 2줄 최적 분할
    best_split = len(words) // 2
    min_diff = 9999
    for i in range(1, len(words)):
        prefix = " ".join(words[:i])
        open_tags = prefix.count("<hl>")
        close_tags = prefix.count("</hl>")
        is_inside_tag = (open_tags > close_tags)

        l1 = prefix
        l2 = " ".join(words[i:])
        v1 = visible_len(l1)
        v2 = visible_len(l2)

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

def generate_image(prompt_text: str, dest_path: str, max_retries: int = 5, force_refresh: bool = False) -> str:
    """gemini-nano-banana-2.1로 텍스트 프리 9:16 실사 이미지 생성 (프롬프트 일치 검증)"""
    meta_path = dest_path + ".meta"
    if not force_refresh and os.path.exists(dest_path) and os.path.getsize(dest_path) > 10000:
        if os.path.exists(meta_path):
            try:
                with open(meta_path, "r", encoding="utf-8") as mf:
                    saved_prompt = mf.read().strip()
                if saved_prompt == prompt_text.strip():
                    print(f"    [Step 5 Image] 동일 프롬프트 기존 이미지 재사용: {dest_path}", flush=True)
                    return dest_path
            except Exception:
                pass

    os.makedirs(os.path.dirname(os.path.abspath(dest_path)), exist_ok=True)
    client_global = genai.Client(vertexai=True, project=config.GCP_PROJECT_ID, location="global")
    full_prompt = (
        f"{prompt_text}. "
        "Cinematic documentary lighting, vertical 9:16 portrait composition, 8k resolution, photorealistic, sharp focus. "
        "CRITICAL REQUIREMENT: Absolutely NO text, NO words, NO letters, NO alphabet, NO typography, NO hangul, NO korean writing, NO captions, NO watermark."
    )
    for attempt in range(max_retries):
        try:
            print(f"    🎨 [Step 5 Image] 이미지 생성 요청 ({attempt+1}/{max_retries})...", flush=True)
            resp = client_global.models.generate_content(
                model=getattr(config, "MODEL_IMAGE", "gemini-nano-banana-2.1"),
                contents=full_prompt,
                config=types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"], candidate_count=1)
            )
            if resp.candidates:
                for part in resp.candidates[0].content.parts:
                    if hasattr(part, "inline_data") and part.inline_data:
                        with open(dest_path, "wb") as f:
                            f.write(part.inline_data.data)
                        with open(meta_path, "w", encoding="utf-8") as mf:
                            mf.write(prompt_text.strip())
                        print(f"    ✨ [Step 5 Image 성공] {dest_path} ({os.path.getsize(dest_path)} bytes)", flush=True)
                        time.sleep(3)
                        return dest_path
            time.sleep(5)
        except Exception as e:
            err_str = str(e)
            print(f"    ⚠️ [Step 5 Image 에러] {err_str[:90]}...", flush=True)
            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                wait_sec = min(35 + attempt * 15, 90)
                time.sleep(wait_sec)
            else:
                time.sleep(4)

    raise RuntimeError(f"이미지 생성 실패 ({max_retries}회 재시도 초과)")

def format_header_lines(text: str, max_single_len: int = 18) -> list:
    """헤더 제목을 자연스러운 한국어 의미 단위(수식절 + 피수식어/핵심주어)로 2줄 분할"""
    text = re.sub(r'^[Qq]\.?\s*', '', text).strip()
    if len(text) <= max_single_len:
        return [text]
    words = text.split()
    if len(words) <= 2:
        return [text]

    best_split = len(words) // 2
    min_score = 999
    for i in range(1, len(words)):
        l1 = " ".join(words[:i])
        l2 = " ".join(words[i:])
        score = abs(len(l1) - len(l2))
        # 2번째 줄이 어색한 조사로 시작하는 분할 방지
        if words[i].startswith(("을", "를", "이", "가", "에", "의", "도", "는", "은", "로")):
            score += 50
        # 수식절 완성 후 개행 우대 (~적인, ~하는, ~되는 등)
        if words[i-1].endswith(("적인", "하는", "되는", "있는", "없는", "보다", "에서", "에게")):
            score -= 15
        if score < min_score:
            min_score = score
            best_split = i

    return [" ".join(words[:best_split]), " ".join(words[best_split:])]

def create_callout_overlay(callout_items: list, font_path: str, out_png_path: str):
    """이미지 중앙 상단(y=660~740)에 팝업 등장할 54~62pt 볼드 키워드 오버레이 생성.
    하이라이트 단어가 여러 개일 때는 1줄로 구겨 넣지 않고 2줄로 개행 분리하여 입체 배치."""
    img = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    if not callout_items:
        img.save(out_png_path)
        return

    if isinstance(callout_items, str):
        callout_items = [callout_items]
    cleaned = [c.strip() for c in callout_items if c.strip()]
    if not cleaned:
        img.save(out_png_path)
        return

    draw = ImageDraw.Draw(img)

    if len(cleaned) == 1:
        text = cleaned[0]
        fsize = 62
        font_c = ImageFont.truetype(font_path, fsize)
        tw = draw.textlength(text, font=font_c)
        while tw > 900 and fsize > 42:
            fsize -= 2
            font_c = ImageFont.truetype(font_path, fsize)
            tw = draw.textlength(text, font=font_c)
        cx = (1080 - tw) / 2
        cy = 700
        # 선명한 붉은색 계통(#FF2A2A) + 8px 딥 블랙 외곽선으로 강렬한 0초 시각적 강조
        draw.text((cx, cy), text, font=font_c, fill=(255, 42, 42, 255), stroke_width=8, stroke_fill=(0, 0, 0, 240))
    else:
        # 2개 이상일 때는 2줄 입체 분리 (1행 순백색, 2행 강렬한 레드)
        t1, t2 = cleaned[0], " ".join(cleaned[1:])
        fsize1 = 52
        font_c1 = ImageFont.truetype(font_path, fsize1)
        tw1 = draw.textlength(t1, font=font_c1)
        while tw1 > 900 and fsize1 > 38:
            fsize1 -= 2
            font_c1 = ImageFont.truetype(font_path, fsize1)
            tw1 = draw.textlength(t1, font=font_c1)

        fsize2 = 58
        font_c2 = ImageFont.truetype(font_path, fsize2)
        tw2 = draw.textlength(t2, font=font_c2)
        while tw2 > 900 and fsize2 > 42:
            fsize2 -= 2
            font_c2 = ImageFont.truetype(font_path, fsize2)
            tw2 = draw.textlength(t2, font=font_c2)

        draw.text(((1080 - tw1) / 2, 660), t1, font=font_c1, fill=(255, 255, 255, 255), stroke_width=7, stroke_fill=(0, 0, 0, 240))
        draw.text(((1080 - tw2) / 2, 735), t2, font=font_c2, fill=(255, 42, 42, 255), stroke_width=8, stroke_fill=(0, 0, 0, 240))

    img.save(out_png_path)

def create_subtitle_overlay(
    header_sub: str, header_main: str, sub_text: str,
    font_path: str, out_png_path: str,
    article_question: str = ""
):
    """풀스크린 몰입형: 36pt 1분상식 브랜딩 + 의미 단위 2줄 헤더 + 황금존 48pt 고정 자막 오버레이 생성"""
    img = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 1. 상단 은은한 투명 딤 비네팅 (y: 0~460)
    for y in range(460):
        alpha = int(170 * (1 - y / 460) ** 1.5)
        draw.line([(0, y), (1080, y)], fill=(0, 0, 0, alpha))

    # 2. 하단 자막 영역 황금존 딤 비네팅 (y: 1220~1660)
    for y in range(1220, 1660):
        rel = 1 - abs(y - 1440) / 220.0
        alpha = int(145 * max(0, rel))
        draw.line([(0, y), (1080, y)], fill=(0, 0, 0, alpha))

    # 3. 상단 브랜드 라벨: 좌측 상단 골드 불릿(●) + Gmarket Sans TTF Bold 36pt (상단 Safe Zone 적용)
    brand_y = 145
    gold_color = (255, 204, 0)
    font_brand = ImageFont.truetype(font_path, 36)
    draw.ellipse([60, brand_y - 9, 78, brand_y + 9], fill=gold_color)
    draw.text((92, brand_y), "1분상식", fill=(245, 245, 250), font=font_brand, anchor="lm")

    # 4. 상단 헤더: 1행/2행 전체 노란색(#FFE600), 54pt 동일 확대 볼드, 6px 블랙 스트로크 (상단 Safe Zone 적용)
    q_raw = article_question.strip() if article_question else "오늘 꼭 알아야 할 핵심 상식"
    q_lines = format_header_lines(q_raw)
    font_q = ImageFont.truetype(font_path, 54)

    if len(q_lines) == 2:
        lw1 = draw.textlength(q_lines[0], font=font_q)
        draw.text(((1080 - lw1) / 2, 250), q_lines[0], font=font_q, fill=(255, 230, 0), stroke_width=6, stroke_fill=(0, 0, 0, 240))

        lw2 = draw.textlength(q_lines[1], font=font_q)
        draw.text(((1080 - lw2) / 2, 315), q_lines[1], font=font_q, fill=(255, 230, 0), stroke_width=6, stroke_fill=(0, 0, 0, 240))
    else:
        lw = draw.textlength(q_lines[0], font=font_q)
        draw.text(((1080 - lw) / 2, 275), q_lines[0], font=font_q, fill=(255, 230, 0), stroke_width=6, stroke_fill=(0, 0, 0, 240))

    # 5. 하단 본문 자막 (황금 리딩 존 y=1340~1410, 무조건 1~2줄, 48pt 고정, hl=노란색 #FFE600)
    if sub_text:
        lines = format_subtitle_lines(sub_text, max_chars_per_line=18)
        fsize_sub = 48
        font_p = ImageFont.truetype(font_path, fsize_sub)

        # 무조건 1~2줄 고정 배치
        if len(lines) == 1:
            y_positions = [1375]
        else:
            y_positions = [1340, 1410]

        for l_idx, line in enumerate(lines[:2]):
            segs = parse_hl_text(line)
            line_w = sum(draw.textlength(text, font=font_p) for text, is_hl in segs)
            start_x = (1080 - line_w) / 2
            cur_x = start_x
            y_pos = y_positions[l_idx]

            for text, is_hl in segs:
                color = "#FFE600" if is_hl else "#FFFFFF"
                draw.text((cur_x, y_pos), text, font=font_p, fill=color, stroke_width=6, stroke_fill="black")
                cur_x += draw.textlength(text, font=font_p)

    img.save(out_png_path)

def render_news_short(
    script_data: dict, durations: list, onetake_audio_path: str,
    output_dir: str, target_date_str: str,
    category: str = None, bgm_filename: str = None,
    force_refresh: bool = False,
    visual_assets: list = None,
    topic_info: dict = None
) -> str:
    """Step 5 전체 렌더링 파이프라인 (풀스크린 몰입형 + 키워드 애니메이션 팝업 + 비디오/실사 하이브리드 지원)"""
    temp_dir = os.path.join(output_dir, "temp")
    os.makedirs(temp_dir, exist_ok=True)
    font_path = get_font_path()

    sections = script_data["sections"]
    article_question = script_data.get("article_question", "")
    output_mp4 = os.path.join(output_dir, f"{target_date_str}.mp4")
    final_shorts_mp4 = os.path.join(output_dir, "final_shorts.mp4")

    # 4-Tier 폭포수 비주얼 에셋 확보
    if not visual_assets:
        report_json = os.path.join(temp_dir, "asset_sourcing_report.json")
        if os.path.exists(report_json):
            try:
                with open(report_json, "r", encoding="utf-8") as rf:
                    cached_assets = json.load(rf)
                if len(cached_assets) == len(sections):
                    visual_assets = cached_assets
                    print(f"  🎬 [Step 5 Renderer] 기존 소싱된 에셋 재사용: {len(visual_assets)}개", flush=True)
            except Exception:
                pass

    if not visual_assets:
        try:
            from asset_sourcer import prepare_visual_assets
        except ImportError:
            try:
                from src.asset_sourcer import prepare_visual_assets
            except ImportError:
                prepare_visual_assets = None

        if prepare_visual_assets and topic_info:
            print("\n  🎬 [Step 5 Renderer] 4-Tier 폭포수 비주얼 에셋 소싱 가동...", flush=True)
            visual_assets = prepare_visual_assets(script_data, topic_info, output_dir, force_refresh=force_refresh)

    # 폴백: visual_assets가 없으면 기존 방식(100% AI 이미지) 안전 대기
    if not visual_assets:
        print("\n  🎬 [Step 5 Renderer] 9:16 실사 AI 이미지 확보 중...", flush=True)
        visual_assets = []
        for idx, sec in enumerate(sections):
            img_p = os.path.join(temp_dir, f"image_{idx}.jpg")
            generate_image(sec["image_prompt"], img_p, force_refresh=force_refresh)
            visual_assets.append({"type": "ai_art", "path": img_p})

    print("  🎞️ [Step 5 Renderer] 풀스크린 몰입형 헤더, 자막 및 키워드 애니메이션 인코딩 중...", flush=True)
    ts_chunks = []

    for idx in range(len(sections)):
        sec = sections[idx]
        dur = float(durations[idx])
        asset = visual_assets[idx] if idx < len(visual_assets) else {"type": "ai_art", "path": os.path.join(temp_dir, f"image_{idx}.jpg")}
        asset_type = asset.get("type", "ai_art")
        asset_path = asset.get("path")
        ts_out = os.path.join(temp_dir, f"chunk_{idx}.ts")
        ov_path = os.path.join(temp_dir, f"overlay_s{idx}.png")
        callout_path = os.path.join(temp_dir, f"callout_s{idx}.png")

        sub_source = sec.get("subtitle", sec.get("narration", ""))
        create_subtitle_overlay(
            sec.get("header_sub", ""), sec.get("header_main", ""),
            sub_source, font_path, ov_path,
            article_question=article_question
        )

        # 씬별 하이라이트 키워드 추출 (core_keyword 우선, <hl> 원본 100% 직결)
        core_kw = sec.get("core_keyword", "").strip()
        hl_matches = re.findall(r'<hl>(.*?)</hl>', sub_source)
        if core_kw:
            callout_items = [core_kw]
        elif hl_matches:
            callout_items = [m.strip() for m in hl_matches if m.strip()]
        else:
            callout_items = []
        c_text = " ".join(callout_items)
        create_callout_overlay(callout_items, font_path, callout_path)

        total_frames = int(dur * 24)
        if idx % 2 == 0:
            z_expr = f"1.0+0.14*(on/{total_frames})"
        else:
            z_expr = f"1.14-0.14*(on/{total_frames})"

        # 4대 다이내믹 모션 애니메이션 (등장 후 씬 종료 시까지 100% 영구 유지)
        st_call = 0.70
        motion_type = idx % 3

        if asset_type == "video" and os.path.exists(asset_path):
            # Tier 1 비디오 클립 청크 인코딩 (원본 모션 유지 + 헤더/자막 오버레이 합성)
            if c_text and dur >= 2.0:
                if motion_type == 1:
                    callout_overlay_expr = f"[bg][2:v]overlay=x='min(0, max(0, 0.90-t)*(-1200))':y=0:enable='gte(t,{st_call})'[bg_call]"
                elif motion_type == 2:
                    callout_overlay_expr = f"[bg][2:v]overlay=x=0:y='min(0, max(0, 0.95-t)*1000)':enable='gte(t,{st_call})'[bg_call]"
                else:
                    callout_overlay_expr = f"[bg][2:v]overlay=0:0:enable='gte(t,{st_call})'[bg_call]"

                filter_str = (
                    f"[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
                    f"fps=24,format=yuv420p[bg];"
                    f"{callout_overlay_expr};"
                    f"[bg_call][1:v]overlay=0:0[v]"
                )
                cmd = [
                    "ffmpeg", "-y", "-i", asset_path, "-i", ov_path, "-i", callout_path,
                    "-t", str(dur),
                    "-filter_complex", filter_str,
                    "-map", "[v]",
                    "-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p", "-preset", "ultrafast",
                    "-an", ts_out
                ]
            else:
                filter_str = (
                    f"[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
                    f"fps=24,format=yuv420p[bg];"
                    f"[bg][1:v]overlay=0:0[v]"
                )
                cmd = [
                    "ffmpeg", "-y", "-i", asset_path, "-i", ov_path,
                    "-t", str(dur),
                    "-filter_complex", filter_str,
                    "-map", "[v]",
                    "-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p", "-preset", "ultrafast",
                    "-an", ts_out
                ]
        else:
            # Tier 0, 2, 3 스틸 이미지/카드 ZoomPan 인코딩
            img_in = asset_path
            if c_text and dur >= 2.0:
                if motion_type == 1:
                    callout_overlay_expr = f"[bg][2:v]overlay=x='min(0, max(0, 0.90-t)*(-1200))':y=0:enable='gte(t,{st_call})'[bg_call]"
                elif motion_type == 2:
                    callout_overlay_expr = f"[bg][2:v]overlay=x=0:y='min(0, max(0, 0.95-t)*1000)':enable='gte(t,{st_call})'[bg_call]"
                else:
                    callout_overlay_expr = f"[bg][2:v]overlay=0:0:enable='gte(t,{st_call})'[bg_call]"

                filter_str = (
                    f"[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
                    f"zoompan=z='{z_expr}':d={total_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920,"
                    f"fps=24,format=yuv420p[bg];"
                    f"{callout_overlay_expr};"
                    f"[bg_call][1:v]overlay=0:0[v]"
                )
                cmd = [
                    "ffmpeg", "-y", "-loop", "1", "-i", img_in, "-i", ov_path, "-i", callout_path,
                    "-t", str(dur),
                    "-filter_complex", filter_str,
                    "-map", "[v]",
                    "-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p", "-preset", "ultrafast",
                    "-an", ts_out
                ]
            else:
                filter_str = (
                    f"[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
                    f"zoompan=z='{z_expr}':d={total_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920,"
                    f"fps=24,format=yuv420p[bg];"
                    f"[bg][1:v]overlay=0:0[v]"
                )
                cmd = [
                    "ffmpeg", "-y", "-loop", "1", "-i", img_in, "-i", ov_path,
                    "-t", str(dur),
                    "-filter_complex", filter_str,
                    "-map", "[v]",
                    "-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p", "-preset", "ultrafast",
                    "-an", ts_out
                ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        ts_chunks.append(ts_out)

    # 비디오 청크 Concat (엔딩 페이지 완전 삭제로 순수 4개 씬만 결합)
    concat_txt_path = os.path.join(temp_dir, "concat.txt")
    with open(concat_txt_path, "w", encoding="utf-8") as f:
        for chunk in ts_chunks:
            clean_chunk = chunk.replace("\\", "/")
            f.write(f"file '{clean_chunk}'\n")

    raw_video_ts = os.path.join(temp_dir, "raw_video.ts")
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_txt_path, "-c", "copy", raw_video_ts],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

    # BGM + 보이스 믹싱 및 MP4 렌더링 (나레이션 종료 시점에 맞춘 0.35s 페이드아웃)
    total_dur = round(sum([float(d) for d in durations]), 2)
    fade_start = round(total_dur - 0.35, 2)
    
    # BGM 음원 동적 결정 (카테고리 매칭 / CLI 오버라이드 / 날짜 로테이션)
    chosen_bgm = resolve_bgm_track(category=category, bgm_override=bgm_filename, date_str=target_date_str)
    bgm_path = get_bgm_path(chosen_bgm)
    
    if bgm_path and os.path.exists(bgm_path):
        print(f"  🎵 [Step 5 Renderer] BGM 트랙 적용: {os.path.basename(bgm_path)} (주제: {category or '일반'}, 날짜: {target_date_str})", flush=True)
        filter_complex = (
            f"[0:v]fade=t=out:st={fade_start}:d=0.35[v];"
            f"[2:a]aloop=loop=-1:size=2e+09,volume=0.08,atrim=0:{total_dur},"
            f"afade=t=out:st={fade_start}:d=0.35[bgm];"
            f"[1:a]adelay=80|80[vox];"
            f"[vox][bgm]amix=inputs=2:duration=first:dropout_transition=2[a]"
        )
        cmd_final = [
            "ffmpeg", "-y",
            "-i", raw_video_ts,
            "-i", onetake_audio_path,
            "-i", bgm_path,
            "-filter_complex", filter_complex,
            "-map", "[v]",
            "-map", "[a]",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            output_mp4
        ]
    else:
        print(f"  ℹ️ [Step 5 Renderer] BGM 음원 부재/제외 -> 나레이션 보이스 단독 렌더링 진행", flush=True)
        filter_complex = (
            f"[0:v]fade=t=out:st={fade_start}:d=0.35[v];"
            f"[1:a]adelay=80|80,afade=t=out:st={fade_start}:d=0.35[a]"
        )
        cmd_final = [
            "ffmpeg", "-y",
            "-i", raw_video_ts,
            "-i", onetake_audio_path,
            "-filter_complex", filter_complex,
            "-map", "[v]",
            "-map", "[a]",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            output_mp4
        ]
    subprocess.run(cmd_final, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

    # final_shorts.mp4 복사
    try:
        shutil.copy2(output_mp4, final_shorts_mp4)
    except Exception as e:
        print(f"  ⚠️ final_shorts.mp4 복사 경고: {e}")

    # 검증용 프레임 스냅샷 추출 (씬 01~04 중간점)
    cum_t = 0.0
    for idx, d in enumerate(durations):
        snap_t = round(cum_t + float(d) / 2, 2)
        subprocess.run(["ffmpeg", "-y", "-ss", str(snap_t), "-i", output_mp4, "-vframes", "1", "-q:v", "2",
                        os.path.join(output_dir, f"frame_s{idx}.jpg")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cum_t += float(d)

    size_mb = round(os.path.getsize(output_mp4) / (1024 * 1024), 2)
    print(f"  ✨ [Step 5 완료] 최종 영상 렌더링 성공 (엔딩 삭제 완결): {output_mp4} ({size_mb} MB, 길이: {round(total_dur, 1)}초)", flush=True)
    return output_mp4

if __name__ == "__main__":
    import argparse
    from datetime import datetime
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Step 5-B: 비디오 최종 렌더러")
    parser.add_argument("--date", type=str, default=datetime.now().strftime("%Y-%m-%d"), help="대상 일자 (YYYY-MM-DD)")
    parser.add_argument("--bgm", type=str, default=None, help="BGM 파일명 오버라이드")
    parser.add_argument("--force", action="store_true", help="기존 캐시 무시 강제 렌더링")
    args = parser.parse_args()

    clean_d = args.date.replace("-", "")
    script_file = os.path.join(config.DATA_DIR, f"script_{clean_d}.json")
    topic_file = os.path.join(config.DATA_DIR, f"topic_selection_{clean_d}.json")
    t_info = json.load(open(topic_file, "r", encoding="utf-8")) if os.path.exists(topic_file) else {}

    if os.path.exists(script_file):
        with open(script_file, "r", encoding="utf-8") as f:
            s_data = json.load(f)
        out_d = os.path.join(config.DATA_DIR, args.date)
        ts_file = os.path.join(out_d, "temp", "timestamps.json")
        if os.path.exists(ts_file):
            with open(ts_file, "r", encoding="utf-8") as f:
                ts_data = json.load(f)
            wav_p = os.path.join(out_d, "temp", "audio_onetake.wav")
            render_news_short(
                s_data, ts_data["durations"], wav_p, out_d, args.date,
                category=t_info.get("category"), bgm_filename=args.bgm, force_refresh=args.force,
                topic_info=t_info
            )
        else:
            print(f"타임스탬프 파일 부재: {ts_file}")
    else:
        print(f"대본 파일 부재: {script_file}")
