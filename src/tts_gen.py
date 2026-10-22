import os
import re
import unicodedata
from xml.sax.saxutils import escape
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config


def clean_narration(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = re.sub(r"\([^()]*\)", " ", text)
    text = text.replace("%", "퍼센트")
    text = text.replace("㎡", "제곱미터")
    text = text.replace("m²", "제곱미터")
    text = text.replace("㎥", "세제곱미터")
    text = text.replace("km", "킬로미터")
    text = text.replace("kg", "킬로그램")
    text = text.replace("cm", "센티미터")
    text = text.replace("mm", "밀리미터")
    text = text.replace("…", ". ")
    text = re.sub(r"[‘’'`\"]", "", text)
    text = re.sub(r"[^\w\s.,!?가-힣a-zA-Z0-9]", " ", text)
    text = re.sub(r"(?<=\d)\s+(?=(억|조|만|천|백|십|원|층|개|명)\b)", "", text)
    # 조사(은/는/이/가/을/를/의/로/에/와/과/도/만) 뒤의 불필요한 쉼표 제거 (한 호흡 자연 낭독)
    text = re.sub(r'([은는이가을를의로에와과도만])\s*,\s*', r'\1 ', text)
    # 짧은 접속부사 뒤의 불필요한 쉼표 제거
    text = re.sub(r'\b(결국|또한|따라서|한편|하지만|다만|이처럼|그렇다면|물론)\s*,\s*', r'\1 ', text)
    text = re.sub(r"\s+([.,!?])", r"\1", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def build_ssml(section_texts: list[str]) -> str:
    speech_parts = ["<speak>"]
    section_rates = ("97%", "99%", "98%", "100%")
    for index, section_text in enumerate(section_texts):
        clean_text = clean_narration(section_text)
        if clean_text:
            rate = section_rates[index % len(section_rates)]
            sentences = re.split(r"(?<=[.!?])\s*", clean_text)
            speech_parts.append(f'<prosody rate="{rate}">')
            for sentence in sentences:
                if sentence.strip():
                    escaped = escape(sentence.strip())
                    ssml_sentence = re.sub(r",\s*", '<break time="120ms"/> ', escaped)
                    speech_parts.append(ssml_sentence)
                    speech_parts.append('<break time="220ms"/>')
            speech_parts.append("</prosody>")
            speech_parts.append('<break time="550ms"/>')
    speech_parts.append("</speak>")
    return "".join(speech_parts)



def _tts_client_parts(category: str = None, slot: str = "morning"):
    from google.cloud import texttospeech
    client = texttospeech.TextToSpeechClient()
    slot_norm = config.normalize_slot(slot)
    slot_conf = config.SLOT_CONFIG.get(slot_norm, config.SLOT_CONFIG["morning"])
    
    # 슬롯 전담 보이스 우선 적용 (슬롯 성격에 최적화된 성우)
    voice_name = slot_conf.get("voice", getattr(config, "DEFAULT_VOICE_NAME", "ko-KR-Neural2-C"))
    speaking_rate = slot_conf.get("speaking_rate", 1.15)
    pitch = slot_conf.get("pitch", 0.0)

    print(f"  -> TTS [{slot_norm.upper()}] 전담 성우: {voice_name} (속도: {speaking_rate}x, 카테고리: {category or '기본'})")
    voice = texttospeech.VoiceSelectionParams(
        language_code="ko-KR",
        name=voice_name
    )
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3,
        speaking_rate=speaking_rate,
        pitch=pitch
    )
    return client, voice, audio_config


def _synthesize_ssml(client, ssml_text: str, voice, audio_config) -> bytes:
    from google.cloud import texttospeech
    synthesis_input = texttospeech.SynthesisInput(ssml=ssml_text)
    response = client.synthesize_speech(
        input=synthesis_input, voice=voice, audio_config=audio_config
    )
    return response.audio_content


def generate_tts_per_section(script_data: dict, daily_dir: str = None, slot: str = "morning"):
    """구간별로 합성해 실제 발화 길이를 측정한다."""
    if daily_dir is None:
        daily_dir = config.DATA_DIR
    try:
        from moviepy.editor import AudioFileClip, concatenate_audioclips
        import json as _json

        sections = script_data.get("script_sections", [])
        section_texts = [
            sec.get("narration", sec.get("text", "")).strip()
            for sec in sections
        ]
        if not any(section_texts):
            raise ValueError("읽을 대본이 없습니다.")

        # 카테고리 및 슬롯 정보 추출
        category = script_data.get("category", "")
        detected_slot = script_data.get("slot", slot)
        if daily_dir:
            try:
                topic_file = os.path.join(daily_dir, "0_topic_selection.json")
                if os.path.exists(topic_file):
                    with open(topic_file, "r", encoding="utf-8") as f:
                        t_data = _json.load(f)
                        if not category:
                            category = t_data.get("category", "")
                        detected_slot = t_data.get("slot", detected_slot)
            except Exception:
                pass

        client, voice, audio_config = _tts_client_parts(category, slot=detected_slot)
        tmp_dir = os.path.join(daily_dir, "temp_tts")
        os.makedirs(tmp_dir, exist_ok=True)

        section_clips = []
        durations = []
        for index, text in enumerate(section_texts):
            ssml_text = build_ssml([text])
            audio_content = _synthesize_ssml(client, ssml_text, voice, audio_config)
            sec_path = os.path.join(tmp_dir, f"sec_{index}.mp3")
            with open(sec_path, "wb") as out:
                out.write(audio_content)
            clip = AudioFileClip(sec_path)
            section_clips.append(clip)
            durations.append(round(clip.duration, 3))
            print(f"  -> 구간 {index + 1} 합성 완료: {durations[-1]}초")

        final_audio = concatenate_audioclips(section_clips)

        output_path = os.path.join(daily_dir, "4_audio.mp3")
        final_audio.write_audiofile(output_path, fps=44100, logger=None)
        print(f'Audio content written to file "{output_path}"')

        durations_path = os.path.join(daily_dir, "4_audio_durations.json")
        with open(durations_path, "w", encoding="utf-8") as f:
            _json.dump({"durations": durations}, f, ensure_ascii=False, indent=2)

        return output_path, durations
    except Exception as e:
        print(f"TTS 생성 오류: {e}")
        return None, None


if __name__ == "__main__":
    import json
    import glob
    candidates = sorted(glob.glob(os.path.join(config.DATA_DIR, "*", "3_script.json")))
    if candidates:
        with open(candidates[-1], "r", encoding="utf-8") as f:
            data = json.load(f)
            generate_tts_per_section(data, os.path.dirname(candidates[-1]))
    else:
        print("테스트용 대본(3_script.json)이 없습니다.")
