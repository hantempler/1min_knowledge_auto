# -*- coding: utf-8 -*-
"""
[Step 5-A] 4-Tier 폭포수 비주얼 에셋 소싱 & Gemini Vision 검증 엔진 (asset_sourcer.py)
기준 레퍼런스: onthenext_shorts 02_star_image.py 및 2026-11-17 프로덕션 실증 사양

[4단계 무결점 캐스케이드 & Vision Gate 가드레일]:
1. [Tier 1: Pexels 세로 비디오 클립]:
   - 대본에서 allow_video=True 인 씬 대상 Pexels Video API 세로(1080x1920) 비디오 직수령
   - 1.5초 지점 프레임 캡처 후 Gemini Vision 1차 검증 -> 통과 시 5초 무음 mp4 인코딩
2. [Tier 2: AI 실사 보도사진 카드 (Google Search Grounding)]:
   - require_news_photo=True 인 팩트 사료 씬에 한하여 실시간 AI 공식 보도자료/기사 검색
   - 3.0초 하드 타임아웃 방어 적용 (외부 언론사 서버 지연 시 즉시 Tier 3 전환)
   - 통과 시 9:16 가우시안 블러(반경 35, 밝기 38%) + 중앙 960px 라운딩(r=28) 플로팅 카드 합성
3. [Tier 3: Pexels 실사 스톡 사진]:
   - Pexels Photo API 세로 고화질 스톡 사진 검색 및 1080x1920 스마트 중앙 크롭 (LANCZOS, 상단 30% 포커스)
   - Gemini Vision 심사 통과 시 cut_XX_photo.jpg 저장 및 Photo ID 메타데이터 보존
4. [Tier 4: Gemini Nano Banana 2.1 AI 폴백]:
   - 1~3단계 전원 부재 시에만 최종 비상 안전망 가동 (src/renderer.py 연동)
5. [Deduplication & Audit]:
   - MD5 해시 중복 차단 및 asset_sourcing_report.md / json 전수 자동 기록
"""
import os
import sys
import json
import re
import time
import hashlib
import subprocess
import shutil
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
        self.pexels_api_key = getattr(config, "PEXELS_API_KEY", None)

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

        # AI가 찾아준 공식 출처 웹페이지에서 고화질 사진 파싱 (엄격한 잡음 필터링 & 타임아웃 방어)
        try:
            with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(3.0, connect=2.0), verify=False, headers=HEADERS) as http_client:
                for uri in article_uris[:3]:
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
                            if len(results) >= 4:
                                break
                    except Exception:
                        continue
        except Exception:
            pass

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

    def extract_video_clip(self, query: str, out_mp4: str, timeout: int = 15) -> bool:
        """Tier 1: Pexels Video API 기반 1080x1920 세로 FHD 직수령 & 5초 무음 mp4 인코딩"""
        if not self.pexels_api_key:
            return False
        os.makedirs(os.path.dirname(os.path.abspath(out_mp4)), exist_ok=True)
        headers = {"Authorization": self.pexels_api_key}
        params = {"query": query, "per_page": 5, "orientation": "portrait"}
        raw_clip = out_mp4.replace(".mp4", "_raw.mp4")
        try:
            res = requests.get("https://api.pexels.com/videos/search", headers=headers, params=params, timeout=timeout)
            if res.status_code != 200:
                return False
            videos = res.json().get("videos", [])
            if not videos:
                return False

            v_url = None
            for v in videos:
                for vf in v.get("video_files", []):
                    if vf.get("height", 0) > vf.get("width", 0) and vf.get("link"):
                        v_url = vf["link"]
                        break
                if v_url:
                    break
            if not v_url and videos[0].get("video_files"):
                v_url = videos[0]["video_files"][0].get("link")
            if not v_url:
                return False

            vr = requests.get(v_url, timeout=timeout, stream=True)
            if vr.status_code != 200:
                return False
            with open(raw_clip, "wb") as f:
                for chunk in vr.iter_content(chunk_size=65536):
                    f.write(chunk)

            conv_cmd = [
                "ffmpeg", "-y", "-ss", "0", "-t", "5", "-i", raw_clip,
                "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1",
                "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", out_mp4
            ]
            subprocess.run(conv_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if os.path.exists(raw_clip):
                os.remove(raw_clip)
            return os.path.exists(out_mp4) and os.path.getsize(out_mp4) > 10000
        except Exception:
            if os.path.exists(raw_clip):
                os.remove(raw_clip)
            return False

    def search_pexels_photos(self, query: str, per_page: int = 5, timeout: int = 10) -> list[dict]:
        """Tier 3: Pexels Photo API 세로(portrait) 사진 최대 per_page개 후보 수집"""
        if not self.pexels_api_key:
            return []
        headers = {"Authorization": self.pexels_api_key}
        params = {"query": query, "per_page": per_page, "orientation": "portrait"}
        try:
            res = requests.get("https://api.pexels.com/v1/search", headers=headers, params=params, timeout=timeout)
            if res.status_code == 200:
                return res.json().get("photos", [])
        except Exception:
            pass
        return []

    def download_and_crop_pexels_photo(self, photo: dict, out_jpg: str, timeout: int = 10) -> bool:
        """Pexels 사진 다운로드 후 1080x1920 세로 스마트 중앙 크롭 (LANCZOS)"""
        os.makedirs(os.path.dirname(os.path.abspath(out_jpg)), exist_ok=True)
        p_url = photo.get("src", {}).get("large2x") or photo.get("src", {}).get("portrait") or photo.get("src", {}).get("original")
        if not p_url:
            return False
        try:
            pr = requests.get(p_url, timeout=timeout)
            if pr.status_code != 200 or len(pr.content) < 5000:
                return False

            pil_img = Image.open(BytesIO(pr.content)).convert("RGB")
            w, h = pil_img.size
            target_ratio = 1080 / 1920
            current_ratio = w / h

            if current_ratio > target_ratio:
                new_w = int(h * target_ratio)
                left = (w - new_w) // 2
                pil_img = pil_img.crop((left, 0, left + new_w, h))
            else:
                new_h = int(w / target_ratio)
                top = max(0, int((h - new_h) * 0.3))
                pil_img = pil_img.crop((0, top, w, top + new_h))

            pil_img = pil_img.resize((1080, 1920), Image.Resampling.LANCZOS)
            pil_img.save(out_jpg, "JPEG", quality=95)
            return True
        except Exception:
            return False

    def extract_pexels_photo(self, query: str, out_jpg: str, timeout: int = 10) -> tuple[bool, str]:
        """Tier 3 하위호환 단일 다운로더"""
        photos = self.search_pexels_photos(query, per_page=1, timeout=timeout)
        if photos and self.download_and_crop_pexels_photo(photos[0], out_jpg, timeout=timeout):
            return True, str(photos[0].get("id", ""))
        return False, None

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
        """Tier 4: gemini-nano-banana-2.1 단독 안전 생성 (src/renderer.py 연동)"""
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        try:
            generate_image(prompt, out_path, force_refresh=True)
            return os.path.exists(out_path) and os.path.getsize(out_path) > 10000
        except Exception as e:
            print(f"    [AI Fallback Error] {e}", flush=True)
            return False


def prepare_visual_assets(script_data: dict, topic_info: dict, output_dir: str, force_refresh: bool = False) -> list[dict]:
    """10개 씬 전수에 대해 4-Tier 폭포수(비디오 -> 뉴스보도사진 -> 스톡사진 -> 나노바나나) 에셋 소싱"""
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
    print(f"🎬 [Step 5-A Asset Sourcer] 4-Tier 폭포수 비주얼 에셋 소싱 가동")
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
        out_photo = os.path.join(img_dir, f"cut_{c_no:02d}_photo.jpg")
        out_ai = os.path.join(img_dir, f"cut_{c_no:02d}_ai.jpg")

        print(f"\n▶ [Scene {c_no:02d}/10] {sec.get('step_title', '')} | 자막: {sub}")

        adopted_type = None
        adopted_path = None
        adopted_desc = None
        adopted_source = None

        # ----------------------------------------------------------------------
        # [Tier 1] 대본에서 allow_video=True 로 승인된 씬만 Pexels 비디오 최우선 탐색
        # ----------------------------------------------------------------------
        if sec.get("allow_video", False):
            v_query = sec.get("stock_query_en") or re.sub(r'(?:보도사진|사진|그래픽|인포그래픽|연출)', '', sq).strip()
            print(f"   [Tier 1 비디오 탐색] Pexels 세로 클립 (영문): '{v_query}'")
            if engine.extract_video_clip(v_query, out_video, timeout=15):
                v_pass, v_reason = engine.verify_video_with_vision(out_video, sec, topic_info)
                if v_pass:
                    adopted_type = "video"
                    adopted_path = out_video
                    adopted_desc = f"Pexels 세로 비디오 클립 ({v_reason})"
                    adopted_source = "Tier 1 (Pexels 비디오)"
                    print(f"   ✓ [Tier 1 합격] 🎬 비디오 채택 ➔ {os.path.basename(out_video)} | {v_reason}")
                else:
                    print(f"   ❌ [Tier 1 탈락] 비디오 Vision 불합격 ({v_reason[:40]}...) ➔ Tier 2/3 전환")
                    if os.path.exists(out_video):
                        os.remove(out_video)

        # ----------------------------------------------------------------------
        # [Tier 2] 실제 보도사진 (require_news_photo 가 True이거나 팩트 사료 씬)
        # ----------------------------------------------------------------------
        if not adopted_type and sec.get("require_news_photo", False):
            print(f"   [Tier 2 탐색] AI 공식 보도사진 검색 (Google Grounding): '{sq}'")
            cands = engine.search_image_candidates(sq)
            print(f"   -> 수집된 공식 출처 후보 URL: {len(cands)}개. Vision Gate 순차 심사...")

            for c_idx, c_info in enumerate(cands, 1):
                u = c_info["direct_url"]
                ref = c_info.get("referer", "https://www.google.com/")
                try:
                    cand_file = os.path.join(cand_dir, f"cut_{c_no:02d}_cand_{c_idx}.jpg")
                    r = requests.get(u, headers={"User-Agent": HEADERS["User-Agent"], "Referer": ref}, timeout=4)
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
        # [Tier 3] Pexels Photo API 고화질 실사 스톡 사진 (최대 5개 후보 순차 심사)
        # ----------------------------------------------------------------------
        if not adopted_type:
            stock_q = sec.get("stock_query_en") or re.sub(r'(?:보도사진|사진|그래픽|인포그래픽|연출)', '', sq).strip()
            print(f"   [Tier 3 탐색] Pexels 고화질 스톡 사진 검색 (영문): '{stock_q}'")
            photos = engine.search_pexels_photos(stock_q, per_page=5, timeout=10)
            print(f"   -> 수집된 Pexels 스톡 후보: {len(photos)}개. Vision Gate 순차 심사...")

            for p_idx, photo in enumerate(photos, 1):
                photo_id = str(photo.get("id", ""))
                cand_photo = os.path.join(cand_dir, f"cut_{c_no:02d}_pexels_cand_{p_idx}.jpg")
                if not engine.download_and_crop_pexels_photo(photo, cand_photo, timeout=10):
                    continue

                try:
                    with open(cand_photo, "rb") as sf:
                        s_bytes = sf.read()
                    h = hashlib.md5(s_bytes).hexdigest()
                    if h in used_hashes:
                        continue

                    v_pass, v_reason = engine.verify_image_with_vision(s_bytes, sec, topic_info)
                    if v_pass:
                        shutil.copy2(cand_photo, out_photo)
                        used_hashes.add(h)
                        adopted_type = "card"
                        adopted_path = out_photo
                        adopted_desc = f"Pexels 세로 실사 사진 ({v_reason})"
                        adopted_source = f"Tier 3 (Pexels Photo ID {photo_id})"
                        print(f"   ✓ [Tier 3 합격] 📸 스톡 사진 후보 {p_idx} PASS ➔ {os.path.basename(out_photo)} | {v_reason}")
                        break
                    else:
                        print(f"      스톡 후보 {p_idx} ❌ [Vision 탈락]: {v_reason[:45]}...")
                except Exception:
                    continue

            if not adopted_type:
                print(f"   ❌ [Tier 3 전원 탈락] Pexels 스톡 {len(photos)}개 후보 전원 불합격 ➔ Tier 4 전환")

        # ----------------------------------------------------------------------
        # [Tier 4] gemini-nano-banana-2.1 AI 실사 생성 (전원 부재 시에만 최종 안전망)
        # ----------------------------------------------------------------------
        if not adopted_type:
            print(f"   ⚠ [Tier 1~3 탈락] 실사 부재 ➔ Tier 4 gemini-nano-banana-2.1 안전 생성")
            if engine.generate_ai_fallback(ai_prompt, out_ai):
                h = hashlib.md5(open(out_ai, "rb").read()).hexdigest()
                used_hashes.add(h)
                adopted_type = "ai_art"
                adopted_path = out_ai
                adopted_desc = "9:16 AI 시네마틱 실사 일러스트"
                adopted_source = "Tier 4 (Gemini Nano Banana AI 폴백)"
                print(f"   ✓ [Tier 4 합격] 🎨 AI 일러스트 생성 ➔ {os.path.basename(out_ai)}")
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
    card_cnt = sum(1 for a in final_assets if a["type"] == "card" and "Tier 2" in (a.get("source") or ""))
    photo_cnt = sum(1 for a in final_assets if a["type"] == "card" and "Tier 3" in (a.get("source") or ""))
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
        f"- 🎬 **Tier 1 Pexels 비디오 클립**: **{video_cnt}개 씬 ({video_cnt/len(final_assets)*100:.1f}%)**",
        f"- 🖼️ **Tier 2 뉴스 실사 보도사진 카드**: **{card_cnt}개 씬 ({card_cnt/len(final_assets)*100:.1f}%)**",
        f"- 📸 **Tier 3 Pexels 실사 스톡 사진**: **{photo_cnt}개 씬 ({photo_cnt/len(final_assets)*100:.1f}%)**",
        f"- 🎨 **Tier 4 Gemini Nano Banana AI 폴백**: **{ai_cnt}개 씬 ({ai_cnt/len(final_assets)*100:.1f}%)**",
        "",
        "---",
        "",
        "### 📋 10개 씬 전수 판정 상세표",
        "",
        "| 씬 | 서사 단계 | 채택 유형 | 파일명 | 비주얼 내용 및 판정 근거 | 소싱 출처 |",
        "| :---: | :--- | :---: | :--- | :--- | :--- |"
    ]

    for a in final_assets:
        badge = "🎬 [비디오]" if a["type"] == "video" else ("🖼️ [실사카드]" if "Tier 2" in (a.get("source") or "") else ("📸 [스톡사진]" if "Tier 3" in (a.get("source") or "") else "🎨 [AI폴백]"))
        fn = os.path.basename(a["path"])
        lines.append(f"| {a['cut_no']:02d} | {a['step_title']} | **{badge}** | `{fn}` | {a['desc']} | {a['source']} |")

    with open(report_md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print("\n" + "=" * 80)
    print(f"🎉 [에셋 소싱 완료] 전수 리포트 발행: {report_md_path}")
    print(f"   -> 비디오 {video_cnt}개 / 실사카드 {card_cnt}개 / 스톡사진 {photo_cnt}개 / AI폴백 {ai_cnt}개")
    print("=" * 80)

    return final_assets


if __name__ == "__main__":
    import argparse
    from datetime import datetime
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Step 5-A: 4-Tier 비주얼 에셋 소싱 엔진")
    parser.add_argument("--date", type=str, default=datetime.now().strftime("%Y-%m-%d"), help="실행 날짜 YYYY-MM-DD")
    parser.add_argument("--force", action="store_true", help="기존 에셋 무시하고 강제 재소싱")
    args = parser.parse_args()

    clean_d = args.date.replace("-", "")
    test_script_path = os.path.join(config.DATA_DIR, f"script_{clean_d}.json")
    # topic_selection 파일이 날짜별 폴더 또는 data 폴더에 있는 것 모두 지원
    test_topic_path = os.path.join(config.DATA_DIR, f"topic_selection_{clean_d}.json")
    if not os.path.exists(test_topic_path):
        test_topic_path = os.path.join(config.DATA_DIR, args.date, f"topic_selection_{clean_d}.json")
    if not os.path.exists(test_script_path):
        test_script_path = os.path.join(config.DATA_DIR, args.date, f"script_{clean_d}.json")

    out_dir = os.path.join(config.DATA_DIR, args.date)
    if os.path.exists(test_script_path) and os.path.exists(test_topic_path):
        s_data = json.load(open(test_script_path, encoding="utf-8"))
        t_data = json.load(open(test_topic_path, encoding="utf-8"))
        prepare_visual_assets(s_data, t_data, out_dir, force_refresh=args.force)
    else:
        print(f"에셋 소싱 대상 파일 부재: {test_script_path} 또는 {test_topic_path}")
