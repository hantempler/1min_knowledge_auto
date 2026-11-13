# -*- coding: utf-8 -*-
"""
[Step 4] 원테이크 TTS 음성 합성 및 Whisper 씬별 칼싱크 분석기
- gemini-2.5-flash-preview-tts (us-central1, 24kHz 모노 원테이크)
- faster-whisper CPU 기반 단어 정밀 분석 -> 씬별 durations 산출 (최소 2.0초 보장)
"""
import os
import sys
import wave
import json
import time
import re
import numpy as np
import scipy.signal
from google import genai
from google.genai import types

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
import config

def normalize_text_for_tts(text: str) -> str:
    """TTS 발음을 부드럽게 만들기 위한 전처리"""
    text = re.sub(r'<.*?>', '', text) # 태그 제거
    text = text.replace("~", "에서 ")
    text = text.replace("/", " 또는 ")
    text = text.replace("%", " 퍼센트")
    return text.strip()

def generate_onetake_tts(text: str, out_wav_path: str, voice_name: str = "Puck", force_refresh: bool = False) -> str:
    """Gemini 2.5 Flash Preview TTS로 원테이크 고음질 음성 생성"""
    if not force_refresh and os.path.exists(out_wav_path) and os.path.getsize(out_wav_path) > 10000:
        print(f"  [Step 4 TTS] 기존 오디오 재사용: {out_wav_path}", flush=True)
        return out_wav_path

    os.makedirs(os.path.dirname(os.path.abspath(out_wav_path)), exist_ok=True)
    clean_text = normalize_text_for_tts(text)
    print(f"  🎙️ [Step 4 TTS] 원테이크 음성 합성 요청 (성우: {voice_name}, 글자수: {len(clean_text)})...", flush=True)

    client_us = genai.Client(vertexai=True, project=config.GCP_PROJECT_ID, location="us-central1")
    
    for attempt in range(5):
        try:
            resp = client_us.models.generate_content(
                model=getattr(config, "MODEL_TTS", "gemini-2.5-flash-preview-tts"),
                contents=clean_text,
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice_name)
                        )
                    )
                )
            )
            for part in resp.candidates[0].content.parts:
                if part.inline_data:
                    with wave.open(out_wav_path, "wb") as wf:
                        wf.setnchannels(1)
                        wf.setsampwidth(2)
                        wf.setframerate(24000)
                        wf.writeframes(part.inline_data.data)
                    print(f"  ✨ [Step 4 TTS 성공] {out_wav_path} ({os.path.getsize(out_wav_path)} bytes)", flush=True)
                    return out_wav_path
        except Exception as e:
            err_str = str(e)
            print(f"  ⚠️ [Step 4 TTS 지연/에러] {err_str[:100]}...", flush=True)
            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                time.sleep(20 + attempt * 10)
            else:
                time.sleep(3)

    raise RuntimeError("TTS 원테이크 오디오 생성 실패")

def align_scenes_whisper(audio_path: str, sections: list, out_json_path: str = None) -> list:
    """faster-whisper로 원테이크 음성을 분석하여 씬별 지속시간(durations) 산출"""
    from faster_whisper import WhisperModel
    print("  🎧 [Step 4 Whisper] 원테이크 오디오 단어 칼싱크 분석 중...", flush=True)

    with wave.open(audio_path, 'rb') as wf:
        framerate = wf.getframerate()
        total_audio_dur = wf.getnframes() / float(framerate)
        frames = wf.readframes(wf.getnframes())
        audio_np = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0

    audio_16k = scipy.signal.resample(audio_np, int(len(audio_np) * 16000 / framerate))
    model = WhisperModel('base', device='cpu', compute_type='int8')
    segments, _ = model.transcribe(audio_16k, word_timestamps=True, language='ko')
    words = [(w.word.strip(), w.start, w.end) for s in segments for w in s.words if w.word.strip()]

    num_sections = len(sections)
    start_times = [0.0]

    for sec_idx in range(1, num_sections):
        sec = sections[sec_idx]
        kw = sec.get("anchor_word", sec.get("keyword", "")).strip()
        narr = sec.get("narration", "")
        # 후보 단어 리스트: 앵커 단어 및 씬 나레이션 앞부분 3단어 (2글자 이상)
        narr_tokens = [re.sub(r'[^\w]', '', w) for w in narr.split() if len(re.sub(r'[^\w]', '', w)) >= 2]
        cands = []
        if kw and len(re.sub(r'[^\w]', '', kw)) >= 2:
            cands.append(re.sub(r'[^\w]', '', kw))
        cands.extend(narr_tokens[:3])

        min_allowed_time = start_times[-1] + 2.0
        found_t = None

        for w, st, et in words:
            if st >= min_allowed_time:
                clean_w = re.sub(r'[^\w]', '', w)
                if not clean_w:
                    continue
                matched = False
                for c in cands:
                    if c == clean_w or (len(c) >= 2 and len(clean_w) >= 2 and (clean_w.startswith(c) or c.startswith(clean_w))):
                        matched = True
                        break
                if matched:
                    found_t = st
                    break

        if found_t is None or found_t <= start_times[-1]:
            remaining_sections = num_sections - sec_idx
            remaining_time = max(total_audio_dur - start_times[-1], remaining_sections * 2.5)
            found_t = start_times[-1] + (remaining_time / (remaining_sections + 1))

        start_times.append(round(found_t, 2))

    start_times.append(round(total_audio_dur, 2))

    durations = []
    for i in range(num_sections):
        dur = float(round(start_times[i+1] - start_times[i], 2))
        dur = max(dur, 2.0)
        durations.append(dur)
        title_label = sections[i].get('header_main', f'씬 {i}')
        print(f"    -> 씬 {i} [{title_label}]: {start_times[i]:5.2f}s ~ {start_times[i+1]:5.2f}s ({dur:.2f}초)", flush=True)

    if out_json_path:
        os.makedirs(os.path.dirname(os.path.abspath(out_json_path)), exist_ok=True)
        with open(out_json_path, "w", encoding="utf-8") as f:
            json.dump({
                "total_duration": float(total_audio_dur),
                "start_times": [float(t) for t in start_times],
                "durations": durations
            }, f, ensure_ascii=False, indent=2)

    return durations

def process_audio_and_sync(script_data: dict, output_dir: str, voice_name: str = "Puck", force_refresh: bool = False) -> tuple:
    temp_dir = os.path.join(output_dir, "temp")
    os.makedirs(temp_dir, exist_ok=True)
    out_wav = os.path.join(temp_dir, "audio_onetake.wav")
    ts_json = os.path.join(temp_dir, "timestamps.json")

    full_narration = " ".join([sec["narration"] for sec in script_data["sections"]])
    generate_onetake_tts(full_narration, out_wav, voice_name=voice_name, force_refresh=force_refresh)
    durations = align_scenes_whisper(out_wav, script_data["sections"], ts_json)
    return out_wav, durations

if __name__ == "__main__":
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    test_date = "2026-11-12"
    clean_d = test_date.replace("-", "")
    script_file = os.path.join(config.DATA_DIR, f"script_{clean_d}.json")
    if os.path.exists(script_file):
        with open(script_file, "r", encoding="utf-8") as f:
            s_data = json.load(f)
        out_d = os.path.join(config.DATA_DIR, test_date)
        wav_p, durs = process_audio_and_sync(s_data, out_d, voice_name="Puck", force_refresh=True)
        print(f"\n[오디오 싱크 결과] 오디오: {wav_p}, 씬별 길이: {durs}")
    else:
        print(f"대본 파일 부재: {script_file}")
