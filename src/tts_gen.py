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
    """하이브리드 칼싱크 정렬: 오디오 묵음 구간(Silence Gap) 분석과 Whisper 단어 인식을 결합하여 씬별 지속시간(durations) 산출"""
    print("  🎧 [Step 4 Audio Sync] 오디오 에너지 및 묵음 구간 정밀 칼싱크 분석 중...", flush=True)

    with wave.open(audio_path, 'rb') as wf:
        framerate = wf.getframerate()
        total_audio_dur = wf.getnframes() / float(framerate)
        frames = wf.readframes(wf.getnframes())
        audio_np = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0

    num_sections = len(sections)

    # 40ms 단위 RMS 에너지 계산으로 문장 간 자연스러운 무음 구간(Silence Gap) 탐색
    hop_sec = 0.04
    hop_len = int(framerate * hop_sec)
    n_hops = len(audio_np) // hop_len
    rms = np.array([np.sqrt(np.mean(audio_np[i*hop_len:(i+1)*hop_len]**2)) for i in range(n_hops)])

    thresh = max(0.012, np.mean(rms) * 0.12)
    min_sil_hops = int(0.20 / hop_sec)
    gaps = []
    in_sil = False
    start_h = 0

    for h in range(len(rms)):
        if rms[h] < thresh:
            if not in_sil:
                in_sil = True
                start_h = h
        else:
            if in_sil:
                in_sil = False
                sil_hops = h - start_h
                if sil_hops >= min_sil_hops:
                    t_st = start_h * hop_sec
                    t_et = h * hop_sec
                    if t_st > 1.2 and t_et < total_audio_dur - 0.8:
                        gaps.append((t_st, t_et, (t_st + t_et) / 2.0))

    expected_cuts = num_sections - 1

    if len(gaps) == expected_cuts:
        cut_points = [g[2] for g in gaps]
    else:
        # 갭 개수가 다를 경우 Whisper 단어/세그먼트 정밀 분석 결합
        from faster_whisper import WhisperModel
        audio_16k = scipy.signal.resample(audio_np, int(len(audio_np) * 16000 / framerate))
        model = WhisperModel('base', device='cpu', compute_type='int8')
        segments, _ = model.transcribe(audio_16k, word_timestamps=True, language='ko')
        seg_list = list(segments)

        if len(seg_list) == num_sections:
            cut_points = []
            for i in range(num_sections - 1):
                p_end = seg_list[i].end
                n_start = seg_list[i+1].start
                matched_gap = None
                for gst, get, gmid in gaps:
                    if gst >= p_end - 0.2 and get <= n_start + 0.2:
                        matched_gap = gmid
                        break
                if matched_gap:
                    cut_points.append(matched_gap)
                else:
                    cut_points.append((p_end + n_start) / 2.0 if n_start > p_end else n_start)
        else:
            expected_intervals = [total_audio_dur * (i / num_sections) for i in range(1, num_sections)]
            cut_points = []
            used_gap_indices = set()
            for exp_t in expected_intervals:
                best_idx = None
                min_dist = 9999.0
                for gi, (st, et, mid) in enumerate(gaps):
                    if gi not in used_gap_indices:
                        dist = abs(mid - exp_t)
                        if dist < min_dist:
                            min_dist = dist
                            best_idx = gi
                if best_idx is not None and min_dist < 2.5:
                    used_gap_indices.add(best_idx)
                    cut_points.append(gaps[best_idx][2])
                else:
                    cut_points.append(exp_t)
            cut_points.sort()

    start_times = [0.0] + [round(c, 2) for c in cut_points] + [round(total_audio_dur, 2)]
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
    import argparse
    from datetime import datetime
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Step 4: TTS 및 Whisper 싱크 정렬기")
    parser.add_argument("--date", type=str, default=datetime.now().strftime("%Y-%m-%d"), help="대상 일자 (YYYY-MM-DD)")
    parser.add_argument("--force", action="store_true", help="기존 오디오 무시하고 강제 재생성")
    args = parser.parse_args()

    clean_d = args.date.replace("-", "")
    script_file = os.path.join(config.DATA_DIR, f"script_{clean_d}.json")
    if os.path.exists(script_file):
        with open(script_file, "r", encoding="utf-8") as f:
            s_data = json.load(f)
        out_d = os.path.join(config.DATA_DIR, args.date)
        wav_p, durs = process_audio_and_sync(s_data, out_d, voice_name="Puck", force_refresh=args.force)
        print(f"\n[Step 4 오디오 싱크 완료] 오디오: {wav_p}")
        print(f"  총 소요 시간: {sum(durs):.2f}초")
        print(f"  씬별 durations: {durs}")
    else:
        print(f"대본 파일 부재: {script_file}")
