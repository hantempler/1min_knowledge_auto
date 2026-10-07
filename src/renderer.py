import os
import re
import requests
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps
from moviepy.editor import AudioFileClip, CompositeAudioClip, CompositeVideoClip, VideoFileClip, ImageClip, concatenate_videoclips, ColorClip
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

def create_pil_subtitle_clip(text, font_path, fontsize, temp_dir):
    try:
        font = ImageFont.truetype(font_path, fontsize)
    except IOError:
        font = ImageFont.load_default()
        
    canvas_w, canvas_h = 1080, 200
    img = Image.new('RGBA', (canvas_w, canvas_h), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)
    
    try:
        bbox = draw.multiline_textbbox((0, 0), text, font=font, spacing=10)
        text_w = bbox[2] - bbox[0]
        
        while text_w > 980 and fontsize > 30:
            fontsize -= 2
            try:
                font = ImageFont.truetype(font_path, fontsize)
            except IOError:
                break
            bbox = draw.multiline_textbbox((0, 0), text, font=font, spacing=10)
            text_w = bbox[2] - bbox[0]
            
        text_h = bbox[3] - bbox[1]
    except AttributeError:
        # 구버전 PIL 하위 호환
        text_w, text_h = draw.textsize(text, font=font)
    
    x = (canvas_w - text_w) / 2
    y = (canvas_h - text_h) / 2
    draw.multiline_text((x, y), text, font=font, fill='white', align='center', spacing=10, stroke_width=3, stroke_fill='black')
    
    temp_path = os.path.join(temp_dir, f"temp_{abs(hash(text))}.png")
    img.save(temp_path)
    
    # moviepy ImageClip으로 변환 시 np.array로 로드
    return temp_path

def create_pil_text_clip(text, font_path, fontsize, temp_dir, text_type="title"):
    try:
        font = ImageFont.truetype(font_path, fontsize)
    except IOError:
        font = ImageFont.load_default()
        
    canvas_w, canvas_h = 1080, 1920
    img = Image.new('RGBA', (canvas_w, canvas_h), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)
    
    if text_type == "header":
        bbox = draw.textbbox((0, 0), text, font=font)
        x = (canvas_w - (bbox[2] - bbox[0])) / 2
        y = 150
        draw.text((x, y), text, font=font, fill=(255, 255, 255, 220), stroke_width=2, stroke_fill='black')

    elif text_type == "topic":
        max_width = 900
        topic_lines = []
        current_line = ""
        for word in text.split(" "):
            candidate = f"{current_line} {word}".strip()
            candidate_width = draw.textbbox((0, 0), candidate, font=font)[2]
            if current_line and candidate_width > max_width:
                topic_lines.append(current_line)
                current_line = word
            else:
                current_line = candidate
        if current_line:
            topic_lines.append(current_line)

        topic_text = "\n".join(topic_lines)
        bbox = draw.multiline_textbbox((0, 0), topic_text, font=font, spacing=10)
        x = (canvas_w - (bbox[2] - bbox[0])) / 2
        draw.multiline_text((x, 225), topic_text, font=font, fill='#FFD700', align='center', spacing=10, stroke_width=3, stroke_fill='black')
        
    elif text_type == "cover":
        # 중앙에 크게
        bbox = draw.multiline_textbbox((0, 0), text, font=font, spacing=20)
        x = (canvas_w - (bbox[2] - bbox[0])) / 2
        y = (canvas_h - (bbox[3] - bbox[1])) / 2
        draw.multiline_text((x, y), text, font=font, fill='#FFD700', align='center', spacing=20, stroke_width=4, stroke_fill='black')
        
    elif text_type == "summary":
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        # "오늘의 상식\n[{cover_title}]\n요약1\n요약2\n요약3"
        title_1 = lines[0] if len(lines) > 0 else "오늘의 상식"
        title_2 = lines[1] if len(lines) > 1 else "[오늘의 1분 상식]"
        summary_lines = lines[2:5] if len(lines) > 4 else lines[2:]

        title1_font = ImageFont.truetype(font_path, 50)
        title1_bbox = draw.textbbox((0, 0), title_1, font=title1_font)
        title1_x = (canvas_w - (title1_bbox[2] - title1_bbox[0])) / 2
        draw.text((title1_x, 390), title_1, font=title1_font, fill='white', stroke_width=2, stroke_fill='black')

        title2_font = ImageFont.truetype(font_path, 65)
        
        # 줄바꿈 헬퍼
        max_width = 980
        t2_lines = []
        current_line = ""
        for word in title_2.split():
            candidate = f"{current_line} {word}".strip()
            if draw.textbbox((0,0), candidate, font=title2_font)[2] > max_width:
                if current_line:
                    t2_lines.append(current_line)
                current_line = word
            else:
                current_line = candidate
        if current_line:
            t2_lines.append(current_line)
        title_2_wrapped = "\n".join(t2_lines)

        title2_bbox = draw.multiline_textbbox((0, 0), title_2_wrapped, font=title2_font, spacing=10)
        title2_x = (canvas_w - (title2_bbox[2] - title2_bbox[0])) / 2
        draw.multiline_text((title2_x, 465), title_2_wrapped, font=title2_font, fill='#FFD700', align='center', spacing=10, stroke_width=3, stroke_fill='black')

        row_x = 70
        row_width = canvas_w - (row_x * 2)
        row_height = 190
        row_gap = 28
        first_row_y = 620
        number_font = ImageFont.truetype(font_path, 44)
        body_font = ImageFont.truetype(font_path, 43)

        import re
        for index, summary_line in enumerate(summary_lines, start=1):
            summary_line = re.sub(r'^\d+\.\s*', '', summary_line).strip()
            if ':' in summary_line:
                summary_label, summary_line = summary_line.split(':', 1)
                summary_label = summary_label.strip()
                summary_line = summary_line.strip()
            else:
                summary_label = ''
            wrapped_lines = []
            current_line = ""
            max_text_width = row_width - 170
            for word in summary_line.split():
                candidate = f"{current_line} {word}".strip()
                candidate_width = draw.textbbox((0, 0), candidate, font=body_font)[2]
                if current_line and candidate_width > max_text_width:
                    wrapped_lines.append(current_line)
                    current_line = word
                else:
                    current_line = candidate
            if current_line:
                wrapped_lines.append(current_line)

            row_y = first_row_y + (index - 1) * (row_height + row_gap)
            draw.rounded_rectangle(
                (row_x, row_y, row_x + row_width, row_y + row_height),
                radius=18,
                fill=(28, 31, 52, 235),
                outline=(255, 215, 0, 180),
                width=2,
            )
            number_bbox = (row_x + 24, row_y + 55, row_x + 94, row_y + 125)
            draw.ellipse(number_bbox, fill='#FFD700')
            number_text = str(index)
            number_text_bbox = draw.textbbox((0, 0), number_text, font=number_font)
            number_x = (number_bbox[0] + number_bbox[2] - (number_text_bbox[2] - number_text_bbox[0])) / 2
            number_y = (number_bbox[1] + number_bbox[3] - (number_text_bbox[3] - number_text_bbox[1])) / 2 - 6
            draw.text((number_x, number_y), number_text, font=number_font, fill='#111323')

            body_text = "\n".join(wrapped_lines[:2])
            text_x = row_x + 125
            if summary_label:
                label_font = ImageFont.truetype(font_path, 36)
                draw.text((text_x, row_y + 34), summary_label, font=label_font, fill='#FFD700', stroke_width=1, stroke_fill='black')
                body_y = row_y + 86
            else:
                body_bbox = draw.multiline_textbbox((0, 0), body_text, font=body_font, spacing=10)
                body_y = row_y + (row_height - (body_bbox[3] - body_bbox[1])) / 2 - 4
            draw.multiline_text((text_x, body_y), body_text, font=body_font, fill='white', spacing=10, stroke_width=1, stroke_fill='black')
        
    temp_path = os.path.join(temp_dir, f"temp_{abs(hash(text))}.png")
    img.save(temp_path)
    return temp_path

def render_video(audio_path: str, script_data: dict, daily_dir: str = None, topic: str = None, bgm_path: str = None):
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
        
        summary_lines = script_data.get("summary_3_lines", [])
        
        # 0. 오디오 믹싱 (MoviePy Audio만 사용)
        from moviepy.editor import AudioClip, concatenate_audioclips
        def make_silence(t): return [0, 0]
        silence_intro = AudioClip(make_frame=make_silence, duration=3.0)
        silence_outro = AudioClip(make_frame=make_silence, duration=4.0 if summary_lines else 0)
        
        final_audio = concatenate_audioclips([silence_intro, audio_clip, silence_outro])
        if bgm_path and os.path.exists(bgm_path):
            bgm_clip = AudioFileClip(bgm_path)
            bgm_clip = audio_loop(bgm_clip, duration=final_audio.duration)
            bgm_clip = bgm_clip.volumex(0.08)
            bgm_clip = audio_fadeout(bgm_clip, min(2.0, final_audio.duration))
            final_audio = CompositeAudioClip([final_audio, bgm_clip])
            
        raw_audio_path = os.path.join(temp_dir, "raw_audio.wav")
        final_audio.write_audiofile(raw_audio_path, fps=44100, logger=None)
        
        concat_list = []
        
        # 1. 인트로 (표지) 컷 추가 (3초)
        print("  -> 인트로 컷 렌더링 중...")
        cover_title = script_data.get("cover_title", "오늘의 1분 상식")
        cover_photo = get_pexels_photo(topic_str, daily_dir, photo_index=0, filename="cover_topic.jpg")
        
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
        c_img.save(bg_png)
        
        intro_ts = os.path.join(temp_dir, "chunk_intro.ts")
        if cover_photo and os.path.exists(cover_photo):
            subprocess.run(["ffmpeg", "-y", "-loop", "1", "-i", cover_photo, "-i", bg_png, "-t", "3.0", "-filter_complex", "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=24[bg];[bg][1:v]overlay=0:0", "-c:v", "libx264", "-preset", "ultrafast", intro_ts], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=#141432:s=1080x1920:d=3.0:r=24", "-i", bg_png, "-filter_complex", "[0:v][1:v]overlay=0:0", "-c:v", "libx264", "-preset", "ultrafast", intro_ts], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        concat_list.append(f"file 'chunk_intro.ts'")
        
        # 2. 본문 컷
        print("  -> 본문 컷 렌더링 중...")
        chunk_idx = 0
        for section_index, sec in enumerate(sections):
            current_sec = 0.0
            text = clean_subtitle_text(sec.get("narration", sec.get("text", "")))
            keyword = sec["bg_keyword"]
            narration_length = narration_lengths[section_index]
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
                    subprocess.run(["ffmpeg", "-y", "-stream_loop", "-1", "-ss", str(current_sec), "-i", bg_path, "-i", overlay_png, "-t", str(chunk_duration), "-filter_complex", "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=24[bg];[bg][1:v]overlay=0:0", "-c:v", "libx264", "-preset", "ultrafast", ts_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=#323232:s=1080x1920:d={chunk_duration}:r=24", "-i", overlay_png, "-filter_complex", "[0:v][1:v]overlay=0:0", "-c:v", "libx264", "-preset", "ultrafast", ts_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                
                concat_list.append(f"file 'chunk_body_{chunk_idx}.ts'")
                chunk_idx += 1
                current_sec += chunk_duration
                
        # 3. 아웃트로 (3줄 요약) 컷 추가 (4초)
        if summary_lines:
            print("  -> 아웃트로 컷 렌더링 중...")
            original_cover = script_data.get("cover_title", "오늘의 1분 상식")
            summary_text = f"오늘의 상식\n[{original_cover}]\n" + "\n".join(summary_lines)
            summary_png_path = create_pil_text_clip(summary_text, font_path, 50, temp_dir, "summary")
            summary_photo = get_pexels_photo(topic_str, daily_dir, photo_index=1, filename="summary_topic.jpg")
            
            s_overlay = os.path.join(temp_dir, "summary_overlay.png")
            s_img = Image.open(summary_png_path)
            s_draw = ImageDraw.Draw(s_img)
            s_draw.text(((1080 - (h_bbox[2] - h_bbox[0])) / 2, 150), header_str, font=font40, fill=(255, 255, 255, 220), stroke_width=2, stroke_fill='black')
            s_img.save(s_overlay)
            
            outro_ts = os.path.join(temp_dir, "chunk_outro.ts")
            if summary_photo and os.path.exists(summary_photo):
                subprocess.run(["ffmpeg", "-y", "-loop", "1", "-i", summary_photo, "-i", s_overlay, "-t", "4.0", "-filter_complex", "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=24[bg];[bg][1:v]overlay=0:0", "-c:v", "libx264", "-preset", "ultrafast", outro_ts], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=#0a0a1e:s=1080x1920:d=4.0:r=24", "-i", s_overlay, "-filter_complex", "[0:v][1:v]overlay=0:0", "-c:v", "libx264", "-preset", "ultrafast", outro_ts], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            concat_list.append(f"file 'chunk_outro.ts'")
            
        print("  -> 비디오 합치기(Concat) 및 오디오 병합 중...")
        concat_txt_path = os.path.join(temp_dir, "concat.txt")
        with open(concat_txt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(concat_list))
            
        raw_video_ts = os.path.join(temp_dir, "raw_video.ts")
        subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_txt_path, "-c", "copy", raw_video_ts], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        output_path = os.path.join(daily_dir, "final_shorts.mp4")
        subprocess.run(["ffmpeg", "-y", "-i", raw_video_ts, "-i", raw_audio_path, "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", output_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        print(f"영상 렌더링 완료: {output_path}")
        return output_path
    except Exception as e:
        print(f"영상 렌더링 오류: {e}")
        return None