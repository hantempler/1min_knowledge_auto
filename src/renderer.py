import os
import re
import json
import requests
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import AudioFileClip, CompositeAudioClip
from moviepy.audio.fx.all import audio_fadeout, audio_loop
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
import text_render

VISUAL_QUERY_MAP = {
    "atmospheric refraction": "sun halo sky",
    "refraction": "sun halo sky",
    "calendar page": "autumn calendar page",
    "autumn leaves": "autumn leaves closeup",
    "sunrise horizon": "sunrise horizon",
}

# 사람이 등장하는 표지 사진은 채널 톤에 어울리지 않고 얼굴 노출 위험도 있으므로 걸러낸다.
PERSON_ALT_KEYWORDS = (
    "woman", "women", "man ", "men ", "girl", "boy", "lady", "gentleman",
    "portrait of a", "close-up of a person", "selfie", "model ", "couple",
    "human", "people ", "person ", "child", "baby",
)

# 표지 사진용 안전 키워드 (카테고리별 폴백).
# 반드시 '사물·건물·문서·자연'처럼 사람이 아닌 것이 화면에 비치는 키워드를 쓴다.
# 본문 bg_keyword는 '움직이는 배경'용이라 표지로 쓰면 사람 군중이 잡히기 쉽다.
COVER_KEYWORD_FALLBACK = {
    "과학": "laboratory glassware science",
    "기술": "circuit board macro technology",
    "역사": "antique archive old document",
    "경제": "stock market chart financial newspaper",
    "사회": "city skyline buildings architecture",
    "문화": "traditional cultural heritage artifact",
    "생활": "household objects flat lay",
    "우주": "earth planet space orbit",
    "의료": "stethoscope medical equipment hospital",
    "환경": "forest trees nature landscape",
}

# 표지 인트로 상단에 2줄로 배치할 10개 카테고리 매트릭스
CATEGORIES_MATRIX = [
    ["과학", "기술", "역사", "경제", "사회"],
    ["문화", "생활", "우주", "의료", "환경"]
]



def get_visual_query(keyword: str) -> str:
    normalized = (keyword or "").strip().lower()
    return VISUAL_QUERY_MAP.get(normalized, keyword)


def _is_person_photo(alt: str) -> bool:
    lowered = (alt or "").lower()
    return any(keyword in lowered for keyword in PERSON_ALT_KEYWORDS)


def get_pexels_video(keyword: str, duration_needed: float, output_dir: str = None):
    if not config.PEXELS_API_KEY:
        print("PEXELS_API_KEY가 없어 더미 비디오 배경을 사용합니다.")
        return None
        
    keyword = get_visual_query(keyword)
    url = f"https://api.pexels.com/videos/search?query={keyword}&orientation=portrait&size=medium&per_page=1"
    headers = {"Authorization": config.PEXELS_API_KEY}
    
    try:
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()
        data = response.json()
        
        if data.get("videos") and len(data["videos"]) > 0:
            video_files = data["videos"][0].get("video_files") or []
            # 아무거나 첫 번째를 고르면 저해상도가 섞인다. 세로 화면에 맞는
            # 충분히 큰 해상도 중 파일이 작은 것을 고른다(다운로드 비용 절감).
            portrait_files = [
                f for f in video_files
                if f.get("height") and f.get("width")
                and f.get("width") <= f.get("height")
                and f.get("height") >= 720
                and f.get("link")
            ]
            candidates = portrait_files or [
                f for f in video_files if f.get("link")
            ]
            if not candidates:
                return None
            target_file = min(candidates, key=lambda f: f.get("height", 99999))
            link = target_file["link"]
            
            # 다운로드한 배경 영상은 해당 날짜의 작업 폴더에 보관
            if output_dir is None:
                output_dir = config.DATA_DIR
            os.makedirs(output_dir, exist_ok=True)
            safe_name = re.sub(r'[\\/:*?"<>|]', "_", keyword).strip() or "clip"
            temp_path = os.path.join(output_dir, f"bg_{safe_name}.mp4")
            with requests.get(link, stream=True, timeout=120) as r:
                r.raise_for_status()
                with open(temp_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192): 
                        f.write(chunk)
            return temp_path
    except Exception as e:
        print(f"Pexels API 영상 다운로드 오류 ({keyword}): {e}")
    return None


def get_pexels_photo(topic: str, output_dir: str = None, photo_index: int = 0, filename: str = "cover_topic.jpg"):
    """주제와 관련된 Pexels 사진 중 지정한 순번을 다운로드한다.

    사람이 등장하는 사진(얼굴/전신 노출)은 건너뛰고, 표지로 쓸 만한
    사물·장면 위주의 사진을 먼저 고른다.
    """
    if not config.PEXELS_API_KEY:
        print("PEXELS_API_KEY가 없어 표지 사진을 사용할 수 없습니다.")
        return None

    url = "https://api.pexels.com/v1/search"
    params = {"query": topic, "orientation": "portrait", "size": "large", "per_page": 8}
    headers = {"Authorization": config.PEXELS_API_KEY}

    try:
        response = requests.get(url, params=params, headers=headers, timeout=20)
        response.raise_for_status()
        photos = response.json().get("photos", [])
        if not photos:
            return None

        # 사람이 있는 사진은 표지로 부적합하므로 뒤로 미룬다.
        object_photos = [p for p in photos if not _is_person_photo(p.get("alt", ""))]
        ordered = object_photos + [p for p in photos if _is_person_photo(p.get("alt", ""))]
        if photo_index >= len(ordered):
            return None

        image_url = (
            ordered[photo_index].get("src", {}).get("portrait")
            or ordered[photo_index].get("src", {}).get("large")
        )
        if not image_url:
            return None

        if output_dir is None:
            output_dir = config.DATA_DIR
        os.makedirs(output_dir, exist_ok=True)
        photo_path = os.path.join(output_dir, filename)
        with requests.get(image_url, stream=True, timeout=30) as image_response:
            image_response.raise_for_status()
            with open(photo_path, "wb") as file:
                for chunk in image_response.iter_content(chunk_size=8192):
                    file.write(chunk)
        return photo_path
    except (requests.RequestException, ValueError) as error:
        print(f"Pexels 표지 사진 다운로드 오류 ({topic}): {error}")
        return None

def chunk_text(text, max_length=13):
    """자막을 2줄 단위의 청크로 나눈다.

    공백 없는 긴 토큰(URL, 영어 단어 등)이 들어오면 한 줄을 통째로 넘어
    화면 밖으로 나가는 문제가 있어, 토큰 자체가 너무 길면 글자 단위로
    먼저 쪼갠 뒤 배치한다.
    """
    lines = text.replace('\n', ' ').split()
    # 너무 긴 단어는 미리 쪼갠다.
    expanded = []
    for word in lines:
        if len(word) > max_length:
            for i in range(0, len(word), max_length):
                expanded.append(word[i:i + max_length])
        else:
            expanded.append(word)
    lines = expanded

    chunks = []
    current_line = []
    current_chunk_lines = []
    
    for word in lines:
        if sum(len(w) for w in current_line) + len(current_line) + len(word) > max_length:
            if current_line:
                current_chunk_lines.append(" ".join(current_line))
            current_line = [word]
            if len(current_chunk_lines) == 2:
                chunks.append("\n".join(current_chunk_lines))
                current_chunk_lines = []
        else:
            current_line.append(word)
            
    if current_line:
        current_chunk_lines.append(" ".join(current_line))
    if current_chunk_lines:
        chunks.append("\n".join(current_chunk_lines))
        
    return chunks


def clean_subtitle_text(text: str) -> str:
    text = re.sub(r"\([^()]*\)", "", text or "")
    text = re.sub(r"[‘’'`\"]", "", text)
    return re.sub(r"\s+", " ", text).strip()

def _run_ffmpeg(cmd: list, temp_dir: str) -> None:
    """ffmpeg 실행 결과를 temp_dir/ffmpeg.log에 남기고, 실패 시 예외를 발생시킨다."""
    import subprocess
    log_path = os.path.join(temp_dir, "ffmpeg.log")
    with open(log_path, "ab") as log_file:
        log_file.write(("$ " + " ".join(str(c) for c in cmd) + "\n").encode("utf-8", "replace"))
        log_file.flush()
        result = subprocess.run(cmd, stdout=log_file, stderr=subprocess.STDOUT)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg 실패 (exit={result.returncode}). 로그: {log_path}")


def _apply_readability_gradient(img: Image.Image) -> Image.Image:
    """텍스트 영역의 가독성을 위해 상단/하단에 어두운 그라데이션을 입힌다.

    밝은 하늘·흰 배경 위에 금색 글씨가 올라가면 거의 보이지 않기 때문에,
    표지 사진의 명암과 무관하게 텍스트가 읽히도록 보정한다.
    """
    width, height = img.size
    gradient = Image.new("L", (1, height), 0)
    pixels = gradient.load()
    for y in range(height):
        ratio = y / max(1, height - 1)
        if ratio < 0.28:
            # 상단: 헤더·배지 영역
            pixels[0, y] = int(150 * (1 - ratio / 0.28))
        elif ratio > 0.72:
            # 하단: '왜 지금' 설명 영역
            pixels[0, y] = int(170 * ((ratio - 0.72) / 0.28))
        else:
            pixels[0, y] = 0
    gradient = gradient.resize((width, height))
    shade = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    shade.putalpha(gradient)
    return Image.alpha_composite(img.convert("RGBA"), shade)


def render_video(audio_path: str, script_data: dict, daily_dir: str = None, topic: str = None, bgm_path: str = None, section_durations: list | None = None):
    if daily_dir is None:
        daily_dir = config.DATA_DIR
    
    font_path = os.path.join(config.CONFIG_DIR, "GmarketSansTTFBold.ttf")
    temp_dir = os.path.join(daily_dir, "temp_subs")
    os.makedirs(temp_dir, exist_ok=True)
    
    import datetime
    import subprocess
    now = datetime.datetime.now()
    weekdays = ['월요일', '화요일', '수요일', '목요일', '금요일', '토요일', '일요일']
    target_dt = now
    try:
        ref_date_str = None
        topic_file = os.path.join(daily_dir, "0_topic_selection.json")
        if os.path.exists(topic_file):
            with open(topic_file, "r", encoding="utf-8") as f:
                ref_date_str = json.load(f).get("reference_date")
        if not ref_date_str:
            folder_name = os.path.basename(os.path.normpath(daily_dir))
            if re.match(r"^\d{4}-\d{2}-\d{2}$", folder_name):
                ref_date_str = folder_name
        if ref_date_str:
            target_dt = datetime.datetime.strptime(ref_date_str[:10], "%Y-%m-%d")
    except Exception:
        target_dt = now

    today_str = target_dt.strftime("%Y년 %m월 %d일")
    header_str = f"{today_str}({weekdays[target_dt.weekday()]}) | 1분 상식 브리핑"
    topic_str = script_data.get("topic") or topic or script_data.get("cover_title", "오늘의 1분 상식")
    if "?" in topic_str:
        topic_str = script_data.get("cover_title", "오늘의 1분 상식")
    # topic_str도 화면에 그려지므로 여기서 폰트가 그릴 수 없는 문자를 제거한다.
    topic_str = text_render.sanitize(topic_str, font_path)
    
    try:
        audio_clip = AudioFileClip(audio_path)
        total_duration = audio_clip.duration
        
        sections = script_data.get("script_sections", [])
        narration_lengths = [
            len(sec.get("narration", sec.get("text", "")))
            for sec in sections
        ]
        total_narration_chars = sum(narration_lengths)

        # 구간별 실측 길이가 있으면 그대로 쓰고, 없으면 기존 글자수 비례로 대체한다.
        use_measured = (
            section_durations is not None
            and len(section_durations) == len(sections)
            and all(d > 0 for d in section_durations)
        )
        if use_measured:
            print(f"  -> 구간 실측 길이 사용: {section_durations}")
        else:
            print("  -> 실측 길이가 없어 글자수 비례로 대체합니다.")
        
        # 0. 오디오 믹싱 (MoviePy Audio만 사용)
        from moviepy.editor import AudioClip, concatenate_audioclips
        def make_silence(t): return [0, 0]
        silence_intro = AudioClip(make_frame=make_silence, duration=3.0)
        silence_outro = AudioClip(make_frame=make_silence, duration=3.0)
        
        final_audio = concatenate_audioclips([silence_intro, audio_clip, silence_outro])
        if bgm_path and os.path.exists(bgm_path):
            bgm_clip = AudioFileClip(bgm_path)
            bgm_clip = audio_loop(bgm_clip, duration=final_audio.duration)
            bgm_clip = bgm_clip.volumex(0.18)
            bgm_clip = audio_fadeout(bgm_clip, min(2.0, final_audio.duration))
            final_audio = CompositeAudioClip([final_audio, bgm_clip])
            
        raw_audio_path = os.path.join(temp_dir, "raw_audio.wav")
        final_audio.write_audiofile(raw_audio_path, fps=44100, logger=None)
        
        concat_list = []
        
        # 1. 인트로 (표지) 컷 추가 (3초)
        print("  -> 인트로 컷 렌더링 중...")
        cover_title = script_data.get("cover_title", "오늘의 1분 상식")
        sections_for_cover = script_data.get("script_sections", [])

        # 주제 선정 배경(왜 이 주제인지)을 읽어 Intro 하단에 배치한다.
        news_context = ""
        category = script_data.get("category", "")
        try:
            with open(os.path.join(daily_dir, "0_topic_selection.json"), "r", encoding="utf-8") as f:
                topic_data = json.load(f)
            if not news_context:
                news_context = (topic_data.get("why_today") or "").strip()
            if not category:
                category = (topic_data.get("category") or "").strip()
        except Exception:
            pass

        # 표지 키워드 결정 순서:
        #   1) 대본의 cover_keyword (가장 정확)
        #   2) 카테고리별 안전 키워드 (사람·군중이 섞이지 않는 사물/장면)
        #   3) 본문 첫 컷의 bg_keyword (마지막 resorts)
        cover_keyword = (script_data.get("cover_keyword") or "").strip()
        if not cover_keyword:
            cover_keyword = COVER_KEYWORD_FALLBACK.get(category, "")
        if not cover_keyword and sections_for_cover:
            cover_keyword = sections_for_cover[0].get("bg_keyword", "")
        if not cover_keyword:
            cover_keyword = topic_str
        cover_photo = get_pexels_photo(cover_keyword, daily_dir, photo_index=0, filename="cover_topic.jpg")

        # 첫 문장까지만 쓰되, 문장이 너무 길면 단어 경계에서 자른다.
        if news_context:
            first_end = re.search(r"[.?!]", news_context)
            if first_end and first_end.end() <= 90:
                news_context = news_context[:first_end.end()]
            else:
                cut = news_context[:70].rsplit(" ", 1)[0]
                news_context = (cut or news_context[:70]).rstrip() + "…"

        # 폰트가 그릴 수 없는 문자(이모지 등)를 제거해 네모(□) 깨짐을 막는다.
        cover_title = text_render.sanitize(cover_title, font_path)
        news_context = text_render.sanitize(news_context, font_path)
        category = text_render.sanitize(category, font_path)
        header_str = text_render.sanitize(header_str, font_path)

        # 배경화면에 텍스트 오버레이용 배경 하나 만들기
        bg_png = os.path.join(temp_dir, "intro_overlay.png")
        c_img = Image.new('RGBA', (1080, 1920), (255, 255, 255, 0))
        c_draw = ImageDraw.Draw(c_img)

        # 텍스트들을 한번에 그림
        font90 = ImageFont.truetype(font_path, 90)
        font40 = ImageFont.truetype(font_path, 40)
        font58 = ImageFont.truetype(font_path, 58)
        font_badge = ImageFont.truetype(font_path, 30)
        font_why_title = ImageFont.truetype(font_path, 42)
        font_why_desc = ImageFont.truetype(font_path, 40)

        # 1. 상단 헤더 (날짜 및 브리핑)
        h_bbox = c_draw.textbbox((0, 0), header_str, font=font40)
        c_draw.text(((1080 - (h_bbox[2] - h_bbox[0])) / 2, 110), header_str, font=font40, fill=(255, 255, 255, 225), stroke_width=2, stroke_fill='black')

        # 2. 10개 카테고리 2줄 알약 (오늘 카테고리만 노란색 강조, 나머지는 은은한 다크 톤)
        pill_w = 150
        pill_h = 48
        pill_gap_x = 14
        pill_gap_y = 12
        row_total_w = 5 * pill_w + 4 * pill_gap_x
        start_x = (1080 - row_total_w) / 2
        start_y = 175

        for row_idx, row in enumerate(CATEGORIES_MATRIX):
            curr_y = start_y + row_idx * (pill_h + pill_gap_y)
            for col_idx, cat_name in enumerate(row):
                curr_x = start_x + col_idx * (pill_w + pill_gap_x)
                box = [curr_x, curr_y, curr_x + pill_w, curr_y + pill_h]
                if cat_name == category:
                    c_draw.rounded_rectangle(box, radius=pill_h // 2, fill=(255, 215, 0, 245))
                    t_bbox = c_draw.textbbox((0, 0), cat_name, font=font_badge)
                    tx = curr_x + (pill_w - (t_bbox[2] - t_bbox[0])) / 2
                    ty = curr_y + (pill_h - (t_bbox[3] - t_bbox[1])) / 2 - 2
                    c_draw.text((tx, ty), cat_name, font=font_badge, fill=(24, 24, 32))
                else:
                    c_draw.rounded_rectangle(box, radius=pill_h // 2, fill=(0, 0, 0, 120), outline=(255, 255, 255, 60), width=1)
                    t_bbox = c_draw.textbbox((0, 0), cat_name, font=font_badge)
                    tx = curr_x + (pill_w - (t_bbox[2] - t_bbox[0])) / 2
                    ty = curr_y + (pill_h - (t_bbox[3] - t_bbox[1])) / 2 - 2
                    c_draw.text((tx, ty), cat_name, font=font_badge, fill=(255, 255, 255, 175))

        # 3. 화면 중앙 대형 메인 타이틀 (1줄 또는 2줄 유동적 처리)
        main_title = cover_title or topic_str or "오늘의 1분 상식"
        main_title = text_render.wrap_text(c_draw, main_title, font90, 920)
        c_bbox = c_draw.multiline_textbbox((0, 0), main_title, font=font90, spacing=20)
        main_w = c_bbox[2] - c_bbox[0]
        main_h = c_bbox[3] - c_bbox[1]

        # 1줄일 때 Y=670, 2줄일 때 Y=580으로 상향 배치하여 배경 피사체 가림 방지 및 황금비율 유지
        lines_count = len(main_title.split("\n"))
        main_y = 670 if lines_count == 1 else 580
        main_x = (1080 - main_w) / 2
        c_draw.multiline_text(
            (main_x, main_y),
            main_title, font=font90, fill='#FFD700', align='center', spacing=20,
            stroke_width=5, stroke_fill='black',
        )
        main_bottom = main_y + main_h

        # 4. "왜 지금 이 상식?" + 설명 블록: 메인 타이틀 하단에 유동적으로 배치
        # 메인 타이틀 끝나는 지점(main_bottom)에서 여유로운 간격(gap=60px)을 두고 시작
        if news_context:
            gap_after_title = 60
            why_label_y = main_bottom + gap_after_title

            label = "오늘 알아야 할 이유"
            l_bbox = c_draw.textbbox((0, 0), label, font=font_why_title)
            c_draw.text(((1080 - (l_bbox[2] - l_bbox[0])) / 2, why_label_y), label, font=font_why_title, fill='#38BDF8', stroke_width=2, stroke_fill='black')

            desc_gap = 56
            news_text = text_render.fit_to_lines(c_draw, news_context, font_why_desc, max_width=920, max_lines=3)
            n_bbox = c_draw.multiline_textbbox((0, 0), news_text, font=font_why_desc, spacing=12)
            c_draw.multiline_text(
                ((1080 - (n_bbox[2] - n_bbox[0])) / 2, why_label_y + desc_gap),
                news_text, font=font_why_desc, fill=(255, 255, 255, 245),
                align='center', spacing=12, stroke_width=2.5, stroke_fill='black'
            )
        c_img.save(bg_png)

        intro_ts = os.path.join(temp_dir, "chunk_intro.ts")
        if cover_photo and os.path.exists(cover_photo):
            # 표지 사진에 가독성 그라데이션을 먼저 입힌 뒤 텍스트를 얹는다.
            graded_photo = os.path.join(temp_dir, "cover_graded.jpg")
            try:
                with Image.open(cover_photo) as raw_cover:
                    graded = _apply_readability_gradient(raw_cover)
                    graded.convert("RGB").save(graded_photo, quality=92)
            except Exception as e:
                print(f"표지 그라데이션 처리 실패(원본 그대로 사용): {e}")
                graded_photo = cover_photo
            _run_ffmpeg(["ffmpeg", "-y", "-loop", "1", "-i", graded_photo, "-i", bg_png, "-t", "3.0", "-filter_complex", "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=24[bg];[bg][1:v]overlay=0:0", "-c:v", "libx264", "-preset", "ultrafast", intro_ts], temp_dir)
        else:
            _run_ffmpeg(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=#141432:s=1080x1920:d=3.0:r=24", "-i", bg_png, "-filter_complex", "[0:v][1:v]overlay=0:0", "-c:v", "libx264", "-preset", "ultrafast", intro_ts], temp_dir)
        concat_list.append(f"file 'chunk_intro.ts'")
        
        # 2. 본문 컷
        print("  -> 본문 컷 렌더링 중...")
        # 본문 상단에 계속 노출되는 짧은 주제 표기(런닝 헤더)
        running_title = text_render.wrap_text(c_draw, topic_str, font58, 900)
        running_bbox = c_draw.multiline_textbbox((0, 0), running_title, font=font58, spacing=10)
        chunk_idx = 0
        for section_index, sec in enumerate(sections):
            current_sec = 0.0
            text = clean_subtitle_text(sec.get("narration", sec.get("text", "")))
            text = text_render.sanitize(text, font_path)
            keyword = sec["bg_keyword"]
            narration_length = narration_lengths[section_index]
            if use_measured:
                sec_duration = section_durations[section_index]
            else:
                sec_duration = (narration_length / total_narration_chars) * total_duration if total_narration_chars > 0 else 5.0
            bg_path = get_pexels_video(keyword, sec_duration, daily_dir)
            
            chunks = chunk_text(text, max_length=15)
            chunk_total_chars = sum(len(c.replace('\n', ' ').replace(' ', '')) for c in chunks)
            if chunk_total_chars == 0: chunk_total_chars = 1
            
            for chunk in chunks:
                chunk_chars = len(chunk.replace('\n', ' ').replace(' ', ''))
                if chunk_chars == 0: continue
                chunk_duration = sec_duration * (chunk_chars / chunk_total_chars)
                
                # PNG 오버레이 렌더링
                overlay_png = os.path.join(temp_dir, f"overlay_{chunk_idx}.png")
                o_img = Image.new('RGBA', (1080, 1920), (255, 255, 255, 0))
                o_draw = ImageDraw.Draw(o_img)
                
                # Header
                o_draw.text(((1080 - (h_bbox[2] - h_bbox[0])) / 2, 150), header_str, font=font40, fill=(255, 255, 255, 220), stroke_width=2, stroke_fill='black')
                # Topic
                o_draw.multiline_text(((1080 - (running_bbox[2] - running_bbox[0])) / 2, 225), running_title, font=font58, fill='#FFD700', align='center', spacing=10, stroke_width=3, stroke_fill='black')
                
                # Subtitle
                fontsize = 65
                try:
                    font_sub = ImageFont.truetype(font_path, fontsize)
                except IOError:
                    font_sub = ImageFont.load_default()
                # 자막이 화면 밖으로 넘치지 않도록 줄바꿈을 보장한다.
                # (한 단어가 너무 길면 글자 단위로 쪼갠다)
                def _fit(chunk_value, font_obj):
                    wrapped = text_render.wrap_text(o_draw, chunk_value, font_obj, 980)
                    bbox = o_draw.multiline_textbbox((0, 0), wrapped, font=font_obj, spacing=10)
                    return wrapped, bbox, bbox[2] - bbox[0]

                sub_text, sub_bbox, sub_w = _fit(chunk, font_sub)
                while sub_w > 980 and fontsize > 30:
                    fontsize -= 2
                    try:
                        font_sub = ImageFont.truetype(font_path, fontsize)
                    except IOError:
                        break
                    sub_text, sub_bbox, sub_w = _fit(chunk, font_sub)
                
                o_draw.multiline_text(((1080 - (sub_bbox[2] - sub_bbox[0])) / 2, 1350), sub_text, font=font_sub, fill='white', align='center', spacing=10, stroke_width=3, stroke_fill='black')
                
                o_img.save(overlay_png)
                
                ts_path = os.path.join(temp_dir, f"chunk_body_{chunk_idx}.ts")
                if bg_path and os.path.exists(bg_path):
                    _run_ffmpeg(["ffmpeg", "-y", "-stream_loop", "-1", "-ss", str(current_sec), "-i", bg_path, "-i", overlay_png, "-t", str(chunk_duration), "-filter_complex", "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=24[bg];[bg][1:v]overlay=0:0", "-c:v", "libx264", "-preset", "ultrafast", ts_path], temp_dir)
                else:
                    _run_ffmpeg(["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=#323232:s=1080x1920:d={chunk_duration}:r=24", "-i", overlay_png, "-filter_complex", "[0:v][1:v]overlay=0:0", "-c:v", "libx264", "-preset", "ultrafast", ts_path], temp_dir)
                
                concat_list.append(f"file 'chunk_body_{chunk_idx}.ts'")
                chunk_idx += 1
                current_sec += chunk_duration
                
        # 3. 아웃트로 (구독 유도) 컷 추가 (3초)
        print("  -> 아웃트로 컷 렌더링 중...")
        sections_for_summary = script_data.get("script_sections", [])
        summary_keyword = (script_data.get("summary_keyword") or "").strip()
        if not summary_keyword:
            summary_keyword = COVER_KEYWORD_FALLBACK.get(category, "")
        if not summary_keyword and sections_for_summary:
            summary_keyword = sections_for_summary[-1].get("bg_keyword", "")
        if not summary_keyword:
            summary_keyword = topic_str
        summary_photo = get_pexels_photo(summary_keyword, daily_dir, photo_index=0, filename="summary_topic.jpg")

        cta_png = os.path.join(temp_dir, "cta_overlay.png")
        cta_img = Image.new('RGBA', (1080, 1920), (255, 255, 255, 0))
        cta_draw = ImageDraw.Draw(cta_img)

        # 1. 상단 날짜 헤더 (인트로와 동일)
        cta_draw.text(((1080 - (h_bbox[2] - h_bbox[0])) / 2, 110), header_str, font=font40, fill=(255, 255, 255, 225), stroke_width=2, stroke_fill='black')

        # 2. 10개 카테고리 2줄 알약 (인트로와 동일한 수미상관 브랜드 통일성)
        for row_idx, row in enumerate(CATEGORIES_MATRIX):
            curr_y = start_y + row_idx * (pill_h + pill_gap_y)
            for col_idx, cat_name in enumerate(row):
                curr_x = start_x + col_idx * (pill_w + pill_gap_x)
                box = [curr_x, curr_y, curr_x + pill_w, curr_y + pill_h]
                if cat_name == category:
                    cta_draw.rounded_rectangle(box, radius=pill_h // 2, fill=(255, 215, 0, 245))
                    t_bbox = cta_draw.textbbox((0, 0), cat_name, font=font_badge)
                    tx = curr_x + (pill_w - (t_bbox[2] - t_bbox[0])) / 2
                    ty = curr_y + (pill_h - (t_bbox[3] - t_bbox[1])) / 2 - 2
                    cta_draw.text((tx, ty), cat_name, font=font_badge, fill=(24, 24, 32))
                else:
                    cta_draw.rounded_rectangle(box, radius=pill_h // 2, fill=(0, 0, 0, 120), outline=(255, 255, 255, 60), width=1)
                    t_bbox = cta_draw.textbbox((0, 0), cat_name, font=font_badge)
                    tx = curr_x + (pill_w - (t_bbox[2] - t_bbox[0])) / 2
                    ty = curr_y + (pill_h - (t_bbox[3] - t_bbox[1])) / 2 - 2
                    cta_draw.text((tx, ty), cat_name, font=font_badge, fill=(255, 255, 255, 175))

        # 3. 화면 중앙: [오늘의 핵심 정리] 다크 글래스 카드
        # 요약 텍스트 결정 (대본의 summary_takeaway 우선, 없으면 마지막 결론 문장 또는 knowledge_angle)
        summary_takeaway = (script_data.get("summary_takeaway") or "").strip()
        if not summary_takeaway:
            if sections_for_summary:
                summary_takeaway = sections_for_summary[-1].get("narration", "")
            if not summary_takeaway:
                try:
                    with open(os.path.join(daily_dir, "0_topic_selection.json"), "r", encoding="utf-8") as f:
                        summary_takeaway = json.load(f).get("knowledge_angle", "")
                except Exception:
                    summary_takeaway = topic_str
        summary_takeaway = text_render.sanitize(summary_takeaway, font_path)

        card_w = 960
        card_h = 450
        card_x = (1080 - card_w) / 2
        card_y = 430
        cta_draw.rounded_rectangle(
            [card_x, card_y, card_x + card_w, card_y + card_h],
            radius=28, fill=(10, 15, 28, 175), outline=(255, 255, 255, 55), width=2
        )

        font_summary_tag = ImageFont.truetype(font_path, 34)
        font_summary_title = ImageFont.truetype(font_path, 60)
        font_summary_body = ImageFont.truetype(font_path, 36)

        # 3-1. 태그 라벨 (시안 블루 #38BDF8)
        tag_text = "오늘의 핵심 정리"
        t_bbox = cta_draw.textbbox((0, 0), tag_text, font=font_summary_tag)
        cta_draw.text(((1080 - (t_bbox[2] - t_bbox[0])) / 2, card_y + 40), tag_text, font=font_summary_tag, fill='#38BDF8', stroke_width=2, stroke_fill='black')

        # 3-2. 주제 타이틀 (골드 #FFD700)
        card_title = script_data.get("cover_title") or topic_str or "오늘의 1분 상식"
        card_title = text_render.sanitize(card_title, font_path)
        title_font_size = 60
        font_summary_title = ImageFont.truetype(font_path, title_font_size)
        while title_font_size > 36:
            tb = cta_draw.textbbox((0, 0), card_title, font=font_summary_title)
            if (tb[2] - tb[0]) <= 840:
                break
            title_font_size -= 4
            font_summary_title = ImageFont.truetype(font_path, title_font_size)

        title_bbox = cta_draw.textbbox((0, 0), card_title, font=font_summary_title)
        cta_draw.text(((1080 - (title_bbox[2] - title_bbox[0])) / 2, card_y + 100), card_title, font=font_summary_title, fill='#FFD700', stroke_width=3, stroke_fill='black')

        # 구분선
        cta_draw.line([(card_x + 80, card_y + 185), (card_x + card_w - 80, card_y + 185)], fill=(255, 255, 255, 60), width=1)

        # 3-3. 핵심 요약 2~3줄 본문 (화이트)
        body_wrapped = text_render.wrap_text(cta_draw, summary_takeaway, font_summary_body, 840)
        # 최대 3줄로 맞춤
        body_lines = body_wrapped.split("\n")
        if len(body_lines) > 3:
            body_wrapped = text_render.fit_to_lines(cta_draw, summary_takeaway, font_summary_body, max_width=840, max_lines=3)
        b_bbox = cta_draw.multiline_textbbox((0, 0), body_wrapped, font=font_summary_body, spacing=14)
        cta_draw.multiline_text(
            ((1080 - (b_bbox[2] - b_bbox[0])) / 2, card_y + 220),
            body_wrapped, font=font_summary_body, fill=(255, 255, 255, 240),
            align='center', spacing=14, stroke_width=2, stroke_fill='black'
        )

        # 4. 화면 하단: [유익했다면, 좋아요 · 구독] CTA (Y=1360~1580)
        cta_y = 1360
        font_cta_small = ImageFont.truetype(font_path, 46)
        font_cta_big = ImageFont.truetype(font_path, 88)
        font_cta_sub = ImageFont.truetype(font_path, 34)

        cta_line1 = text_render.sanitize("유익했다면", font_path)
        cta_line2 = text_render.sanitize("좋아요 · 구독", font_path)
        cta_line3 = text_render.sanitize("매일 1분 상식 브리핑", font_path)

        small_bbox = cta_draw.textbbox((0, 0), cta_line1, font=font_cta_small)
        cta_draw.text(((1080 - (small_bbox[2] - small_bbox[0])) / 2, cta_y), cta_line1, font=font_cta_small, fill='white', stroke_width=2, stroke_fill='black')

        big_bbox = cta_draw.textbbox((0, 0), cta_line2, font=font_cta_big)
        cta_draw.text(((1080 - (big_bbox[2] - big_bbox[0])) / 2, cta_y + 60), cta_line2, font=font_cta_big, fill='#FFD700', stroke_width=4, stroke_fill='black')

        sub_bbox = cta_draw.textbbox((0, 0), cta_line3, font=font_cta_sub)
        cta_draw.text(((1080 - (sub_bbox[2] - sub_bbox[0])) / 2, cta_y + 175), cta_line3, font=font_cta_sub, fill=(255, 255, 255, 220), stroke_width=2, stroke_fill='black')

        cta_img.save(cta_png)

        outro_ts = os.path.join(temp_dir, "chunk_outro.ts")
        if summary_photo and os.path.exists(summary_photo):
            graded_summary = os.path.join(temp_dir, "summary_graded.jpg")
            try:
                with Image.open(summary_photo) as raw_summary:
                    graded = _apply_readability_gradient(raw_summary)
                    graded.convert("RGB").save(graded_summary, quality=92)
            except Exception as e:
                print(f"아웃트로 그라데이션 처리 실패(원본 그대로 사용): {e}")
                graded_summary = summary_photo
            _run_ffmpeg(["ffmpeg", "-y", "-loop", "1", "-i", graded_summary, "-i", cta_png, "-t", "3.0", "-filter_complex", "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=24[bg];[bg][1:v]overlay=0:0", "-c:v", "libx264", "-preset", "ultrafast", outro_ts], temp_dir)
        else:
            _run_ffmpeg(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=#0a0a1e:s=1080x1920:d=3.0:r=24", "-i", cta_png, "-filter_complex", "[0:v][1:v]overlay=0:0", "-c:v", "libx264", "-preset", "ultrafast", outro_ts], temp_dir)
        concat_list.append(f"file 'chunk_outro.ts'")
            
        print("  -> 비디오 합치기(Concat) 및 오디오 병합 중...")
        concat_txt_path = os.path.join(temp_dir, "concat.txt")
        with open(concat_txt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(concat_list))
            
        raw_video_ts = os.path.join(temp_dir, "raw_video.ts")
        _run_ffmpeg(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_txt_path, "-c", "copy", raw_video_ts], temp_dir)
        
        output_path = os.path.join(daily_dir, "final_shorts.mp4")
        _run_ffmpeg(["ffmpeg", "-y", "-i", raw_video_ts, "-i", raw_audio_path, "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", output_path], temp_dir)
        
        print(f"영상 렌더링 완료: {output_path}")
        return output_path
    except Exception as e:
        print(f"영상 렌더링 오류: {e}")
        return None