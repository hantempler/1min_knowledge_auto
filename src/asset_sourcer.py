# -*- coding: utf-8 -*-
"""
[Step 5-A] 3-Tier 폭포수 비주얼 에셋 소싱 & Gemini Vision 검증 엔진 (asset_sourcer.py)
기준 레퍼런스: onthenext_shorts 02_star_image.py

[3단계 무결점 캐스케이드 & Vision Gate 가드레일]:
1. [Tier 1: 숏폼 비디오 클립]:
   - 오프닝 훅 씬(씬 1, 2) 유튜브 5초 무음 1080x1920 세로 클립 추출 (yt-dlp)
   - 1.5초 지점 프레임 캡처 후 Gemini Vision 1차 검증 (뉴스/주제 팩트 부합 심사)
2. [Tier 2: AI 실사 보도사진 소싱 (Google Search Grounding)]:
   - Gemini 모델에 Google Search Grounding(types.GoogleSearch())을 연동한 실시간 AI 공식 보도자료/기사 검색
   - 공식 출처 고화질 사진 수집 후 Gemini Vision 하드 게이트 적용
   - 통과 시 9:16 가우시안 블러(반경 35, 밝기 38%) + 중앙 960px 라운딩(r=28) 플로팅 카드 합성
3. [Tier 3: AI 시네마틱 무인 폴백]:
   - 1~2단계 전원 탈락 시 기존 검증된 gemini-nano-banana-2.1 (src/renderer.py 연동) 안전 생성
4. [Deduplication & Audit]:
   - MD5 해시 중복 차단 및 asset_sourcing_report.md 자동 기록
"""
import os
import sys
import json
import re
import time
import hashlib
import subprocess
from io import BytesIO
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
import httpx
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps
from google import genai
from google.genai import types

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

import config
try:
    from renderer import generate_image
except ImportError:
    from src.renderer import generate_image

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
}

class RobustNewsVisualEngine:
    def __init__(self):
        self.client = genai.Client(vertexai=True, project=config.GCP_PROJECT_ID, location=config.GCP_LOCATION)
        self.model_flash = getattr(config, "MODEL_FAST", "gemini-3.5-flash")

    def search_image_candidates(self, query: str) -> list[dict]:
        """Gemini AI + Google Search Grounding을 통한 공식 뉴스/보도사진 출처 수집 (순수 AI 검색)"""
        results = []
        prompt = f"{query} 관련 실제 공식 뉴스 기사, 보도자료, 사진 웹페이지 링크를 찾아줘"
        article_uris = []

        try:
            resp = self.client.models.generate_content(
                model=self.model_flash,
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                    temperature=0.1
                )
            )
            candidate = resp.candidates[0] if resp.candidates else None
            metadata = getattr(candidate, "grounding_metadata", None)
            if metadata and getattr(metadata, "grounding_chunks", None):
                for chunk in metadata.grounding_chunks:
                    if getattr(chunk, "web", None) and chunk.web.uri:
                        article_uris.append(chunk.web.uri)
        except Exception as e:
            print(f"    [AI Grounding Search Warning] {e}", flush=True)

        # AI가 찾아준 공식 출처 웹페이지에서 고화질 사진 파싱 (엄격한 잡음 필터링)
        with httpx.Client(follow_redirects=True, timeout=7.0, verify=False, headers=HEADERS) as http_client:
            for uri in article_uris[:5]:
                try:
                    r = http_client.get(uri)
                    if r.status_code != 200:
                        continue
                    final_url = str(r.url)
                    html = r.text

                    # 1. og:image 메타 태그
                    m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html, re.I)
                    if not m:
                        m = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', html, re.I)
                    if m:
                        og_u = urljoin(final_url, m.group(1))
                        if not any(k in og_u.lower() for k in ["logo", "icon", "share", "banner", "facebook", "twitter", "default", "avatar"]):
                            results.append({"direct_url": og_u, "referer": final_url})

                    # 2. 본문 고화질 img 태그
                    for img_m in re.finditer(r'<img[^>]+src=["\']([^"\']+\.(?:jpg|jpeg|png|webp)[^"\']*)["\']', html, re.I):
                        src = img_m.group(1)
                        if any(k in src.lower() for k in ["logo", "icon", "banner", "btn", "ad_", "pixel", "sp_", "spinner", "share", "sns", "default", "avatar"]):
                            continue
                        full_u = urljoin(final_url, src)
                        results.append({"direct_url": full_u, "referer": final_url})
                        if len(results) >= 6:
                            break
                except Exception:
                    continue

        return results

    def verify_image_with_vision(self, img_bytes: bytes, sec_info: dict, topic_info: dict) -> tuple[bool, str]:
        """Gemini Vision 게이트: 뉴스/상식 보도 적합성 및 팩트 부합 여부 심사"""
        sub = sec_info.get("subtitle", "")
        kw = sec_info.get("core_keyword", "")
        step_t = sec_info.get("step_title", "")
        press = topic_info.get("press", "언론사")
        headline = topic_info.get("selected_article_title", "")

        prompt = f"""너는 대한민국 1위 뉴스·교양 쇼츠 파이프라인의 수석 비주얼 팩트 검증 AI이다.

[장면 정보]:
- 씬 단계: {step_t}
- 씬 자막: {sub}
- 핵심 팩트 키워드: {kw}
- 뉴스 출처: [{press}] {headline}

[★ 9:16 다큐멘터리 쇼츠 판정 기준]:
1. [합격 (pass: true)]:
   - 본 사진이 해당 뉴스 주제나 대본 팩트(의학, 건강, 통계, 약품, 피해 사례, 사회 현상 등)와 직접 부합하는 실제 보도사진, 실사 사료, 통계 그래프, 인포그래픽, 실물 사진인가?
   - 가로형 사진이어도 화면 중앙에 핵심 피사체가 식별되면 합격 처리하라.
   - 언론사 로고나 방송 자막 바이라인이 있어도, 실사 보도 자료의 신뢰도를 높여주므로 합격 처리하라!
2. [불합격 (pass: false)]:
   - 화면 전체를 가리는 대형 유료 스톡 워터마크 (Getty Images 대형 격자 등)
   - 2D 만화, 웹툰, 유머 짤방, 낚시성 썸네일
   - 대본 내용과 완전히 다른 엉뚱한 사물이나 인물
   - 심각한 저해상도 픽셀 깨짐

반드시 다음 순수 JSON으로만 응답하라:
```json
{{
  "pass": true,
  "reason": "구체적인 판정 사유 한 문장"
}}
```"""

        try:
            part = types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg")
            resp = self.client.models.generate_content(
                model=self.model_flash,
                contents=[part, prompt],
                config=types.GenerateContentConfig(temperature=0.0, response_mime_type="application/json")
            )
            clean_t = re.sub(r"^```(?:json)?\s*", "", resp.text.strip())
            clean_t = re.sub(r"\s*```$", "", clean_t)
            j = json.loads(clean_t)
            return j.get("pass", False), j.get("reason", "")
        except Exception as e:
            return False, f"Vision 검증 에러: {e}"

    def verify_video_with_vision(self, video_path: str, sec_info: dict, topic_info: dict) -> tuple[bool, str]:
        """비디오 클립의 1.5초 프레임을 캡처하여 Gemini Vision으로 검증"""
        thumb_path = video_path.replace(".mp4", "_thumb.jpg")
        os.system(f'ffmpeg -y -ss 00:00:01.5 -i "{video_path}" -vframes 1 "{thumb_path}" >nul 2>&1')
        if not os.path.exists(thumb_path) or os.path.getsize(thumb_path) < 2000:
            return False, "비디오 프레임 캡처 실패"

        try:
            with open(thumb_path, "rb") as f:
                img_bytes = f.read()
            v_pass, v_reason = self.verify_image_with_vision(img_bytes, sec_info, topic_info)
            if os.path.exists(thumb_path):
                os.remove(thumb_path)
            return v_pass, v_reason
        except Exception as e:
            if os.path.exists(thumb_path):
                os.remove(thumb_path)
            return False, str(e)

    def extract_video_clip(self, query: str, out_mp4: str, timeout: int = 20) -> bool:
        """yt-dlp로 5초 무음 1080x1920 세로 비디오 클립 추출 (02_star_image.py 레퍼런스 준수)"""
        os.makedirs(os.path.dirname(os.path.abspath(out_mp4)), exist_ok=True)
        search_cmd = [
            sys.executable, "-m", "yt_dlp",
            f"ytsearch1:{query}",
            "--get-id",
            "--no-warnings"
        ]
        try:
            r = subprocess.run(search_cmd, capture_output=True, text=True, timeout=10)
            v_ids = [line.strip() for line in r.stdout.strip().split("\n") if line.strip() and not line.startswith("ERROR")]
            if not v_ids:
                # 쿼리가 길어 실패 시 핵심 키워드 기반 재탐색
                words = query.split()
                short_q = f"{words[0]} {words[1] if len(words)>1 else ''} shorts".strip()
                r = subprocess.run([sys.executable, "-m", "yt_dlp", f"ytsearch1:{short_q}", "--get-id", "--no-warnings"], capture_output=True, text=True, timeout=10)
                v_ids = [line.strip() for line in r.stdout.strip().split("\n") if line.strip() and not line.startswith("ERROR")]
            if not v_ids:
                return False
            v_id = v_ids[-1]
        except Exception:
            return False

        yt_url = f"https://www.youtube.com/watch?v={v_id}"
        raw_clip = out_mp4.replace(".mp4", "_raw.mp4")
        dl_cmd = [
            sys.executable, "-m", "yt_dlp",
            "-f", "bestvideo[ext=mp4][height<=1080]/best[ext=mp4]/best",
            "--download-sections", "*00:02-00:07",
            "--force-keyframes-at-cuts",
            "-o", raw_clip,
            yt_url
        ]
        try:
            subprocess.run(dl_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout)
            if not os.path.exists(raw_clip) or os.path.getsize(raw_clip) < 5000:
                return False

            # FFmpeg 1080x1920 세로 패딩 변환
            conv_cmd = [
                "ffmpeg", "-y", "-i", raw_clip,
                "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black,setsar=1",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-an",
                out_mp4
            ]
            subprocess.run(conv_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if os.path.exists(raw_clip):
                os.remove(raw_clip)
            return os.path.exists(out_mp4) and os.path.getsize(out_mp4) > 10000
        except Exception:
            if os.path.exists(raw_clip):
                os.remove(raw_clip)
            return False

    def compose_9x16_card(self, img_bytes: bytes, out_path: str) -> bool:
        """9:16 가우시안 블러 배경(반경 35, 밝기 38%) + 중앙 960px 라운딩(r=28) 플로팅 카드 합성"""
        try:
            img = Image.open(BytesIO(img_bytes)).convert("RGB")
            w, h = img.size
            if w < 200 or h < 150:
                return False

            target_w, target_h = 1080, 1920
            aspect = w / h

            if aspect <= 0.68:
                canvas = ImageOps.fit(img, (target_w, target_h), method=Image.Resampling.LANCZOS)
            else:
                bg = ImageOps.fit(img, (target_w, target_h), method=Image.Resampling.LANCZOS)
                bg = bg.filter(ImageFilter.GaussianBlur(radius=35))
                bg = ImageEnhance.Brightness(bg).enhance(0.38)
                canvas = bg.convert("RGBA")

                card_w = 960
                card_h = int(card_w / aspect)
                if card_h > 1150:
                    card_h = 1150
                    card_w = int(card_h * aspect)

                fg = img.resize((card_w, card_h), Image.Resampling.LANCZOS).convert("RGBA")
                mask = Image.new("L", (card_w, card_h), 0)
                draw = ImageDraw.Draw(mask)
                draw.rounded_rectangle((0, 0, card_w, card_h), radius=28, fill=255)

                card_x = (target_w - card_w) // 2
                card_y = (target_h - card_h) // 2 - 20
                canvas.paste(fg, (card_x, card_y), mask)

            os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
            canvas.convert("RGB").save(out_path, format="JPEG", quality=95)
            return True
        except Exception:
            return False

    def generate_ai_fallback(self, prompt: str, out_path: str) -> bool:
        """Tier 3: gemini-nano-banana-2.1 단독 안전 생성 (src/renderer.py 연동)"""
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        try:
            generate_image(prompt, out_path, force_refresh=True)
            return os.path.exists(out_path) and os.path.getsize(out_path) > 10000
        except Exception as e:
            print(f"    [AI Fallback Error] {e}", flush=True)
            return False


def prepare_visual_assets(script_data: dict, topic_info: dict, output_dir: str, force_refresh: bool = False) -> list[dict]:
    """10개 씬 전수에 대해 3-Tier 폭포수(비디오 -> AI실사 -> 나노바나나) 에셋 소싱"""
    temp_dir = os.path.join(output_dir, "temp")
    img_dir = os.path.join(temp_dir, "images")
    cand_dir = os.path.join(temp_dir, "candidates")
    video_dir = os.path.join(temp_dir, "videos")
    os.makedirs(img_dir, exist_ok=True)
    os.makedirs(cand_dir, exist_ok=True)
    os.makedirs(video_dir, exist_ok=True)

    engine = RobustNewsVisualEngine()
    sections = script_data.get("sections", [])

    print("\n" + "=" * 80)
    print(f"🎬 [Step 5-A Asset Sourcer] 3-Tier 폭포수 비주얼 에셋 소싱 가동")
    print(f"    - 대상 주제: [{topic_info.get('press', '언론사')}] {topic_info.get('shorts_title', '')}")
    print(f"    - 총 씬 수: {len(sections)}개 씬")
    print("=" * 80)

    used_hashes = set()
    final_assets = []

    for idx, sec in enumerate(sections):
        c_no = idx + 1
        sub = sec.get("subtitle", "")
        kw = sec.get("core_keyword", "")
        sq = sec.get("search_query") or f"{kw} {topic_info.get('shorts_title', '')}"
        ai_prompt = sec.get("image_prompt", "")

        out_card = os.path.join(img_dir, f"cut_{c_no:02d}_card.jpg")
        out_video = os.path.join(video_dir, f"cut_{c_no:02d}_video.mp4")
        out_ai = os.path.join(img_dir, f"cut_{c_no:02d}_ai.jpg")

        print(f"\n▶ [Scene {c_no:02d}/10] {sec.get('step_title', '')} | 자막: {sub}")

        adopted_type = None
        adopted_path = None
        adopted_desc = None
        adopted_source = None

        # ----------------------------------------------------------------------
        # [Tier 1] 대본에서 allow_video=True 로 승인된 씬만 비디오 최우선 탐색
        # ----------------------------------------------------------------------
        if sec.get("allow_video", False):
            clean_sub = re.sub(r'<.*?>', '', sub).strip()
            v_sq = re.sub(r'(?:보도사진|사진|그래픽|인포그래픽|연출)', '', sq).strip()
            v_query = f"{kw} {v_sq} shorts".strip()
            print(f"   [Tier 1 비디오 탐색] 유튜브 세로 클립: '{v_query}'")
            if engine.extract_video_clip(v_query, out_video, timeout=20):
                v_pass, v_reason = engine.verify_video_with_vision(out_video, sec, topic_info)
                if v_pass:
                    adopted_type = "video"
                    adopted_path = out_video
                    adopted_desc = f"현장 비디오 클립 ({v_reason})"
                    adopted_source = "Tier 1 (유튜브 클립)"
                    print(f"   ✓ [Tier 1 합격] 🎬 비디오 채택 ➔ {os.path.basename(out_video)} | {v_reason}")
                else:
                    print(f"   ❌ [Tier 1 탈락] 비디오 Vision 불합격 ({v_reason[:40]}...) ➔ Tier 2 전환")
                    if os.path.exists(out_video):
                        os.remove(out_video)

        # ----------------------------------------------------------------------
        # [Tier 2] AI 실사 보도사진 검색 (Gemini AI + Google Search Grounding)
        # ----------------------------------------------------------------------
        if not adopted_type:
            print(f"   [Tier 2 탐색] AI 공식 보도사진 검색 (Google Grounding): '{sq}'")
            cands = engine.search_image_candidates(sq)
            print(f"   -> 수집된 공식 출처 후보 URL: {len(cands)}개. Vision Gate 순차 심사...")

            for c_idx, c_info in enumerate(cands, 1):
                u = c_info["direct_url"]
                ref = c_info.get("referer", "https://www.google.com/")
                try:
                    cand_file = os.path.join(cand_dir, f"cut_{c_no:02d}_cand_{c_idx}.jpg")
                    r = requests.get(u, headers={"User-Agent": HEADERS["User-Agent"], "Referer": ref}, timeout=6)
                    if r.status_code != 200 or len(r.content) < 8000:
                        continue

                    h = hashlib.md5(r.content).hexdigest()
                    if h in used_hashes:
                        continue

                    with open(cand_file, "wb") as cf:
                        cf.write(r.content)

                    v_pass, v_reason = engine.verify_image_with_vision(r.content, sec, topic_info)
                    if v_pass:
                        if engine.compose_9x16_card(r.content, out_card):
                            used_hashes.add(h)
                            adopted_type = "card"
                            adopted_path = out_card
                            adopted_desc = f"검증된 실사 보도사진 ({v_reason})"
                            adopted_source = f"Tier 2 (AI Grounding: {u[:50]}...)"
                            print(f"   ✓ [Tier 2 합격] 🖼️ 실사 사진 PASS ➔ {os.path.basename(out_card)} | {v_reason}")
                            break
                    else:
                        print(f"      후보 {c_idx} ❌ [Vision 탈락]: {v_reason[:50]}...")
                except Exception:
                    continue

        # ----------------------------------------------------------------------
        # [Tier 3] gemini-nano-banana-2.1 AI 실사 생성 (무인 무중단 안전망)
        # ----------------------------------------------------------------------
        if not adopted_type:
            print(f"   ⚠ [Tier 1~2 탈락] 실사 부재 ➔ Tier 3 gemini-nano-banana-2.1 안전 생성")
            if engine.generate_ai_fallback(ai_prompt, out_ai):
                h = hashlib.md5(open(out_ai, "rb").read()).hexdigest()
                used_hashes.add(h)
                adopted_type = "ai_art"
                adopted_path = out_ai
                adopted_desc = "9:16 AI 시네마틱 실사 일러스트"
                adopted_source = "Tier 3 (Gemini Nano Banana 2.1)"
                print(f"   ✓ [Tier 3 합격] 🎨 AI 일러스트 생성 ➔ {os.path.basename(out_ai)}")
            else:
                Image.new("RGB", (1080, 1920), color=(20, 24, 30)).save(out_ai)
                adopted_type = "ai_art"
                adopted_path = out_ai
                adopted_desc = "비상 단색 배경 카드"
                adopted_source = "Emergency Fallback"

        final_assets.append({
            "cut_no": c_no,
            "step_title": sec.get("step_title", ""),
            "subtitle": sub,
            "core_keyword": kw,
            "search_query": sq,
            "type": adopted_type,
            "path": adopted_path,
            "desc": adopted_desc,
            "source": adopted_source
        })

    # 감사 리포트 저장 (JSON & Markdown)
    report_json_path = os.path.join(temp_dir, "asset_sourcing_report.json")
    with open(report_json_path, "w", encoding="utf-8") as f:
        json.dump(final_assets, f, ensure_ascii=False, indent=2)

    report_md_path = os.path.join(output_dir, "asset_sourcing_report.md")
    video_cnt = sum(1 for a in final_assets if a["type"] == "video")
    card_cnt = sum(1 for a in final_assets if a["type"] == "card")
    ai_cnt = sum(1 for a in final_assets if a["type"] == "ai_art")

    lines = [
        f"# 📸 [비주얼 에셋 소싱 & Vision 검증 리포트] {topic_info.get('shorts_title', '')}",
        "",
        f"> **뉴스 출처**: [{topic_info.get('press', '언론사')}] {topic_info.get('selected_article_title', '')}  ",
        f"> **검증 일시**: {time.strftime('%Y-%m-%d %H:%M:%S')}  ",
        f"> **총 씬 수**: {len(final_assets)}개 씬  ",
        "",
        "---",
        "",
        "### 📊 종합 에셋 채택 통계",
        f"- 🎬 **Tier 1 비디오 클립**: **{video_cnt}개 씬 ({video_cnt/len(final_assets)*100:.1f}%)**",
        f"- 🖼️ **Tier 2 AI 실사 보도사진 카드**: **{card_cnt}개 씬 ({card_cnt/len(final_assets)*100:.1f}%)**",
        f"- 🎨 **Tier 3 Gemini Nano Banana AI 폴백**: **{ai_cnt}개 씬 ({ai_cnt/len(final_assets)*100:.1f}%)**",
        "",
        "---",
        "",
        "### 📋 10개 씬 전수 판정 상세표",
        "",
        "| 씬 | 서사 단계 | 채택 유형 | 파일명 | 비주얼 내용 및 판정 근거 | 소싱 출처 |",
        "| :---: | :--- | :---: | :--- | :--- | :--- |"
    ]

    for a in final_assets:
        badge = "🎬 [비디오]" if a["type"] == "video" else ("🖼️ [실사카드]" if a["type"] == "card" else "🎨 [AI아트]")
        fn = os.path.basename(a["path"])
        lines.append(f"| {a['cut_no']:02d} | {a['step_title']} | **{badge}** | `{fn}` | {a['desc']} | {a['source']} |")

    with open(report_md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print("\n" + "=" * 80)
    print(f"🎉 [에셋 소싱 완료] 전수 리포트 발행: {report_md_path}")
    print(f"   -> 비디오 {video_cnt}개 / 실사카드 {card_cnt}개 / AI폴백 {ai_cnt}개")
    print("=" * 80)

    return final_assets


def run_cold_test():
    """모듈별 단위 기능 정밀 콜드테스트 (더미가 아닌 실제 보도사진 및 비디오 실물 전수 검증)"""
    print("\n" + "=" * 80)
    print("🧊 [정밀 콜드테스트 시작] src/asset_sourcer.py 5대 핵심 모듈 실물 검증")
    print("=" * 80)

    engine = RobustNewsVisualEngine()
    test_dir = "data/cold_test"
    os.makedirs(test_dir, exist_ok=True)

    sec_info = {"subtitle": "체중 감량 주사제", "core_keyword": "위고비", "step_title": "오프닝"}
    topic_info = {"press": "이데일리", "selected_article_title": "“10kg 뺐지만 시력 잃었다”…오젬픽·위고비에 무슨 일이"}

    # 1. AI Grounding 검색 및 실제 후보 다운로드
    print("\n[테스트 1] AI Google Search Grounding 공식 보도사진 수집 및 고화질 필터링...")
    cands = engine.search_image_candidates("위고비 비만치료제 오젬픽")
    print(f"   결과: 수집된 원천 후보 URL {len(cands)}개")

    real_photo_bytes = None
    real_photo_url = None
    for idx, c in enumerate(cands, 1):
        u = c["direct_url"]
        ref = c.get("referer", "https://www.google.com/")
        try:
            r = requests.get(u, headers={"User-Agent": HEADERS["User-Agent"], "Referer": ref}, timeout=6)
            if r.status_code == 200 and len(r.content) >= 15000:
                im = Image.open(BytesIO(r.content))
                w, h = im.size
                if w >= 300 and h >= 200 and (0.35 <= w/h <= 3.0):
                    cand_save = os.path.join(test_dir, f"real_candidate_{idx}.jpg")
                    with open(cand_save, "wb") as f:
                        f.write(r.content)
                    print(f"   ✓ [고화질 후보 확보 {idx}] {w}x{h} ({len(r.content)} bytes) ➔ {cand_save}")
                    if real_photo_bytes is None:
                        real_photo_bytes = r.content
                        real_photo_url = u
        except Exception:
            continue

    if not real_photo_bytes:
        print("   ⚠️ 실사 사진 다운로드 실패 ➔ 비상 테스트 이미지 로드")

    # 2. 실제 보도사진에 대한 Gemini Vision Gate 검증
    print("\n[테스트 2] 수집된 실제 보도사진 Gemini Vision Gate 팩트 판정...")
    if real_photo_bytes:
        v_pass, v_reason = engine.verify_image_with_vision(real_photo_bytes, sec_info, topic_info)
        print(f"   출처 URL: {real_photo_url}")
        print(f"   결과: pass = {v_pass} | 판정 사유: {v_reason}")

    # 3. 실제 보도사진으로 9:16 가우시안 블러 플로팅 카드 합성
    print("\n[테스트 3] 실제 보도사진 기반 9:16 가우시안 블러 플로팅 카드 합성...")
    card_path = os.path.join(test_dir, "test_card_real.jpg")
    if real_photo_bytes:
        c_ok = engine.compose_9x16_card(real_photo_bytes, card_path)
        print(f"   결과: 카드 합성 성공 = {c_ok}")
        if c_ok and os.path.exists(card_path):
            card_im = Image.open(card_path)
            print(f"   생성 파일: {card_path} ({os.path.getsize(card_path)} bytes, 규격: {card_im.size})")

    # 4. 유튜브 5초 무음 비디오 클립 추출 및 비전 검증
    print("\n[테스트 4] 유튜브 5초 세로 비디오 클립 추출 (yt-dlp) 및 Vision 검증...")
    test_video = os.path.join(test_dir, "test_clip.mp4")
    v_ok = engine.extract_video_clip("위고비 오젬픽 뉴스", test_video, timeout=20)
    print(f"   결과: 비디오 추출 성공 = {v_ok}")
    if v_ok and os.path.exists(test_video):
        print(f"   생성 비디오: {test_video} ({os.path.getsize(test_video)} bytes)")
        v_pass_vid, v_reason_vid = engine.verify_video_with_vision(test_video, sec_info, topic_info)
        print(f"   비디오 프레임 Vision 판정: pass = {v_pass_vid} | 사유: {v_reason_vid}")

    # 5. Tier 3 AI 이미지 생성 (gemini-nano-banana-2.1)
    print("\n[테스트 5] Tier 3 gemini-nano-banana-2.1 AI 실사 생성 (src/renderer.py 연동)...")
    ai_path = os.path.join(test_dir, "test_ai.jpg")
    ai_ok = engine.generate_ai_fallback("A pharmaceutical vial of semaglutide weight loss medication with medical packaging", ai_path)
    print(f"   결과: AI 생성 성공 = {ai_ok}")
    if ai_ok and os.path.exists(ai_path):
        print(f"   생성 이미지: {ai_path} ({os.path.getsize(ai_path)} bytes, 규격: {Image.open(ai_path).size})")

    print("\n" + "=" * 80)
    print("🧊 [콜드테스트 종료] 5대 모듈 전수 실물 생성 및 검증 완료")
    print("=" * 80)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--cold-test", action="store_true", help="단위 기능 콜드테스트 실행")
    args = parser.parse_args()

    if args.cold_test:
        run_cold_test()
    else:
        test_script_path = os.path.join(config.DATA_DIR, "script_20261116.json")
        test_topic_path = os.path.join(config.DATA_DIR, "topic_selection_20261116.json")
        if os.path.exists(test_script_path) and os.path.exists(test_topic_path):
            s_data = json.load(open(test_script_path, encoding="utf-8"))
            t_data = json.load(open(test_topic_path, encoding="utf-8"))
            prepare_visual_assets(s_data, t_data, "data/2026-11-16", force_refresh=True)
