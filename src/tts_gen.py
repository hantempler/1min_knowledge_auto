import os
import re
import unicodedata
from xml.sax.saxutils import escape
from google.cloud import texttospeech
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
                    speech_parts.append(escape(sentence.strip()))
                    speech_parts.append('<break time="180ms"/>')
            speech_parts.append("</prosody>")
            speech_parts.append('<break time="500ms"/>')
    speech_parts.append("</speak>")
    return "".join(speech_parts)


def generate_tts(script_data: dict, daily_dir: str = None):
    if daily_dir is None:
        daily_dir = config.DATA_DIR
    try:
        # JSON에서 전체 텍스트 추출
        sections = script_data.get("script_sections", [])
        section_texts = [
            sec.get("narration", sec.get("text", "")).strip()
            for sec in sections
        ]
        ssml_text = build_ssml(section_texts)
        if ssml_text == "<speak></speak>":
            raise ValueError("읽을 대본이 없습니다.")
        
        client = texttospeech.TextToSpeechClient()

        synthesis_input = texttospeech.SynthesisInput(ssml=ssml_text)

        voice = texttospeech.VoiceSelectionParams(
            language_code="ko-KR",
            name="ko-KR-Neural2-C"
        )

        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3,
            speaking_rate=1.0,
            pitch=0.0
        )

        response = client.synthesize_speech(
            input=synthesis_input, voice=voice, audio_config=audio_config
        )

        output_path = os.path.join(daily_dir, "4_audio.mp3")
        with open(output_path, "wb") as out:
            out.write(response.audio_content)
            print(f'Audio content written to file "{output_path}"')
            
        return output_path
    except Exception as e:
        print(f"TTS 생성 오류: {e}")
        return None

if __name__ == "__main__":
    import json
    test_script_path = os.path.join(config.DATA_DIR, "latest_script.json")
    if os.path.exists(test_script_path):
        with open(test_script_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            generate_tts(data)
    else:
        print("최신 대본(JSON) 파일이 없습니다.")
