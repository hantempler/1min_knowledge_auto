import os
import re
import json
import requests
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import AudioFileClip, CompositeAudioClip
from moviepy.audio.fx.all import audio_fadeout, audio_loop
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

VISUAL_QUERY_MAP = {
    "atmospheric refraction": "sun halo sky",
    "refraction": "sun halo sky",
    "calendar page": "autumn calendar page",
    "autumn leaves": "autumn leaves closeup",
    "sunrise horizon": "sunrise horizon",
}


def get_visual_query(keyword: str) -> str:
    normalized = (keyword or "").strip().lower()
    return VISUAL_QUERY_MAP.get(normalized, keyword)

def get_pexels_video(keyword: str, duration_needed: float, output_dir: str = None):
    if not config.PEXELS_API_KEY:
        print("PEXELS_API_KEY가 없어 더미 비디오 배경을 사용합니다.")
        return None
        
    keyword = get_visual_query(keyword)
    url = f"https://api.pexels.com/videos/search?query={keyword}&orientation=portrait&size=medium&per_page=1"
    headers = {"Authorization": config.PEXELS_API_KEY}
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
        
        if data.get("videos") and len(data["videos"]) > 0:
            video_files = data["videos"][0]["video_files"]
            # 세로형 중 해상도 적절한 것 선택
            target_file = video_files[0]
            link = target_file["link"]
            
            # 다운로드한 배경 영상은 해당 날짜의 작업 폴더에 보관
            if output_dir is None:
                output_dir = config.DATA_DIR
            os.makedirs(output_dir, exist_ok=True)
            temp_path = os.path.join(output_dir, f"bg_{keyword}.mp4")
            with requests.get(link, stream=True) as r:
                r.raise_for_status()
                with open(temp_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192): 
                        f.write(chunk)
            return temp_path
    except Exception as e:
        print(f"Pexels API 영상 다운로드 오류 ({keyword}): {e}")
    return None


def get_pexels_photo(topic: str, output_dir: str = None, photo_index: int = 0, filename: str = "cover_topic.jpg"):
    """오늘의 주제와 관련된 Pexels 사진 중 지정한 순번을 다운로드한다."""
    if not config.PEXELS_API_KEY:
        print("PEXELS_API_KEY가 없어 표지 사진을 사용할 수 없습니다.")
        return None

    url = "https://api.pexels.com/v1/search"
    params = {"query": topic, "orientation": "portrait", "size": "large", "per_page": 2}
    headers = {"Authorization": config.PEXELS_API_KEY}

    try:
        response = requests.get(url, params=params, headers=headers, timeout=15)
        response.raise_for_status()
        photos = response.json().get("photos", [])
        if len(photos) <= photo_index:
            return None

        image_url = photos[photo_index].get("src", {}).get("portrait") or photos[photo_index].get("src", {}).get("large")
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
    lines = text.replace('\n', ' ').split()
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
    today_str = now.strftime("%Y년 %m월 %d일")
    header_str = f"{today_str}({weekdays[now.weekday()]}) | 1분 상식 브리핑"
    topic_str = script_data.get("topic") or topic or script_data.get("cover_title", "오늘의 1분 상식")
    if "?" in topic_str:
        topic_str = script_data.get("cover_title", "오늘의 1분 상식")
    
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
        cover_keyword = (
            script_data.get("cover_keyword")
            or (sections_for_cover[0].get("bg_keyword") if sections_for_cover else "")
            or topic_str
        )
        cover_photo = get_pexels_photo(cover_keyword, daily_dir, photo_index=0, filename="cover_topic.jpg")

        # 주제 선정 배경(왜 이 주제인지)을 인트로 하단에 표시한다.
        news_context = ""
        try:
            with open(os.path.join(daily_dir, "0_topic_selection.json"), "r", encoding="utf-8") as f:
                news_context = json.load(f).get("why_today", "") or ""
        except Exception:
            pass
        if len(news_context) > 80:
            news_context = news_context[:80].rstrip() + "…"
        
        # 바탕화면에 텍스트 오버레이용 배경 하나 만들기
        bg_png = os.path.join(temp_dir, "intro_overlay.png")
        c_img = Image.new('RGBA', (1080, 1920), (255, 255, 255, 0))
        c_draw = ImageDraw.Draw(c_img)
        
        # 텍스트 래핑 헬퍼 함수
        def wrap_text(text, font, max_width=980):
            lines = []
            current_line = ""
            for word in text.split():
                candidate = f"{current_line} {word}".strip()
                if c_draw.textbbox((0,0), candidate, font=font)[2] > max_width:
                    if current_line:
                        lines.append(current_line)
                    current_line = word
                else:
                    current_line = candidate
            if current_line:
                lines.append(current_line)
            return "\n".join(lines)

        # 텍스트들을 한번에 그림
        font90 = ImageFont.truetype(font_path, 90)
        font40 = ImageFont.truetype(font_path, 40)
        font58 = ImageFont.truetype(font_path, 58)
        
        cover_title = wrap_text(cover_title, font90)
        topic_str = wrap_text(topic_str, font58)
        
        c_bbox = c_draw.multiline_textbbox((0, 0), cover_title, font=font90, spacing=20)
        c_draw.multiline_text(((1080 - (c_bbox[2] - c_bbox[0])) / 2, (1920 - (c_bbox[3] - c_bbox[1])) / 2), cover_title, font=font90, fill='#FFD700', align='center', spacing=20, stroke_width=4, stroke_fill='black')
        
        h_bbox = c_draw.textbbox((0, 0), header_str, font=font40)
        c_draw.text(((1080 - (h_bbox[2] - h_bbox[0])) / 2, 150), header_str, font=font40, fill=(255, 255, 255, 220), stroke_width=2, stroke_fill='black')
        
        topic_bbox = c_draw.multiline_textbbox((0, 0), topic_str, font=font58, spacing=10)
        c_draw.multiline_text(((1080 - (topic_bbox[2] - topic_bbox[0])) / 2, 225), topic_str, font=font58, fill='#FFD700', align='center', spacing=10, stroke_width=3, stroke_fill='black')

        if news_context:
            font36 = ImageFont.truetype(font_path, 36)
            news_wrapped = wrap_text(news_context, font36, max_width=940)
            news_lines = news_wrapped.split("\n")[:2]
            news_text = "\n".join(news_lines)
            n_bbox = c_draw.multiline_textbbox((0, 0), news_text, font=font36, spacing=8)
            c_draw.multiline_text(((1080 - (n_bbox[2] - n_bbox[0])) / 2, 1560), news_text, font=font36, fill=(255, 255, 255, 230), align='center', spacing=8, stroke_width=2, stroke_fill='black')
        c_img.save(bg_png)
        
        intro_ts = os.path.join(temp_dir, "chunk_intro.ts")
        if cover_photo and os.path.exists(cover_photo):
            _run_ffmpeg(["ffmpeg", "-y", "-loop", "1", "-i", cover_photo, "-i", bg_png, "-t", "3.0", "-filter_complex", "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=24[bg];[bg][1:v]overlay=0:0", "-c:v", "libx264", "-preset", "ultrafast", intro_ts], temp_dir)
        else:
            _run_ffmpeg(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=#141432:s=1080x1920:d=3.0:r=24", "-i", bg_png, "-filter_complex", "[0:v][1:v]overlay=0:0", "-c:v", "libx264", "-preset", "ultrafast", intro_ts], temp_dir)
        concat_list.append(f"file 'chunk_intro.ts'")
        
        # 2. 본문 컷
        print("  -> 본문 컷 렌더링 중...")
        chunk_idx = 0
        for section_index, sec in enumerate(sections):
            current_sec = 0.0
            text = clean_subtitle_text(sec.get("narration", sec.get("text", "")))
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
                o_draw.multiline_text(((1080 - (topic_bbox[2] - topic_bbox[0])) / 2, 225), topic_str, font=font58, fill='#FFD700', align='center', spacing=10, stroke_width=3, stroke_fill='black')
                
                # Subtitle
                fontsize = 65
                try:
                    font_sub = ImageFont.truetype(font_path, fontsize)
                except IOError:
                    font_sub = ImageFont.load_default()
                sub_bbox = o_draw.multiline_textbbox((0, 0), chunk, font=font_sub, spacing=10)
                sub_w = sub_bbox[2] - sub_bbox[0]
                
                while sub_w > 980 and fontsize > 30:
                    fontsize -= 2
                    try:
                        font_sub = ImageFont.truetype(font_path, fontsize)
                    except IOError:
                        break
                    sub_bbox = o_draw.multiline_textbbox((0, 0), chunk, font=font_sub, spacing=10)
                    sub_w = sub_bbox[2] - sub_bbox[0]
                    
                o_draw.multiline_text(((1080 - (sub_bbox[2] - sub_bbox[0])) / 2, 1350), chunk, font=font_sub, fill='white', align='center', spacing=10, stroke_width=3, stroke_fill='black')
                
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
        summary_keyword = (
            script_data.get("summary_keyword")
            or (sections_for_summary[-1].get("bg_keyword") if sections_for_summary else "")
            or topic_str
        )
        summary_photo = get_pexels_photo(summary_keyword, daily_dir, photo_index=1, filename="summary_topic.jpg")

        cta_png = os.path.join(temp_dir, "cta_overlay.png")
        cta_img = Image.new('RGBA', (1080, 1920), (255, 255, 255, 0))
        cta_draw = ImageDraw.Draw(cta_img)
        cta_draw.text(((1080 - (h_bbox[2] - h_bbox[0])) / 2, 150), header_str, font=font40, fill=(255, 255, 255, 220), stroke_width=2, stroke_fill='black')

        cta_small = ImageFont.truetype(font_path, 60)
        cta_big = ImageFont.truetype(font_path, 120)
        cta_sub = ImageFont.truetype(font_path, 46)
        small_bbox = cta_draw.textbbox((0, 0), "유익했다면", font=cta_small)
        cta_draw.text(((1080 - (small_bbox[2] - small_bbox[0])) / 2, 780), "유익했다면", font=cta_small, fill='white', stroke_width=2, stroke_fill='black')
        big_bbox = cta_draw.textbbox((0, 0), "좋아요 · 구독", font=cta_big)
        cta_draw.text(((1080 - (big_bbox[2] - big_bbox[0])) / 2, 880), "좋아요 · 구독", font=cta_big, fill='#FFD700', stroke_width=4, stroke_fill='black')
        sub_bbox = cta_draw.textbbox((0, 0), "매일 1분 상식 브리핑", font=cta_sub)
        cta_draw.text(((1080 - (sub_bbox[2] - sub_bbox[0])) / 2, 1080), "매일 1분 상식 브리핑", font=cta_sub, fill=(255, 255, 255, 230), stroke_width=2, stroke_fill='black')
        cta_img.save(cta_png)

        outro_ts = os.path.join(temp_dir, "chunk_outro.ts")
        if summary_photo and os.path.exists(summary_photo):
            _run_ffmpeg(["ffmpeg", "-y", "-loop", "1", "-i", summary_photo, "-i", cta_png, "-t", "3.0", "-filter_complex", "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=24[bg];[bg][1:v]overlay=0:0", "-c:v", "libx264", "-preset", "ultrafast", outro_ts], temp_dir)
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