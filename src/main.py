# -*- coding: utf-8 -*-
"""
[Main Pipeline] 네이버 랭킹 뉴스 기반 쇼츠 완전 자동화 통합 파이프라인
- 날짜(YYYY-MM-DD) 기준 Step 1 ~ Step 5 무인 자동 완결
  1. Step 1: 네이버 실시간 랭킹 뉴스 83개 언론사 전수 수집 (scraper.py)
  2. Step 2: 1위 킬러 토픽 자동 선정 및 기사 본문 수집 (topic_sourcing.py)
  3. Step 3: 음성-자막 1:1 일치 4씬 대본 생성 (script_gen.py)
  4. Step 4: 원테이크 TTS 및 Whisper 정밀 싱크 분석 (tts_gen.py)
  5. Step 5: 48pt 자막 & 2.4s 엔딩 영상 렌더링 및 프레임 추출 (renderer.py)
"""
import os
import sys
import json
import time
import argparse
import datetime
from zoneinfo import ZoneInfo

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# 상위 폴더(루트)를 모듈 경로에 추가
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

import config
from scraper import get_naver_ranking_by_date
from topic_sourcing import select_best_killer_topic
from script_gen import generate_script, generate_youtube_metadata
from tts_gen import process_audio_and_sync
from renderer import render_news_short
from upload_youtube import upload_video

def run_pipeline(
    target_date_str: str = None,
    force_refresh: bool = False,
    voice_name: str = "Puck",
    output_dir: str = None,
    bgm: str = "auto",
    slot: str = "auto",
    skip_upload: bool = False
) -> dict:
    start_time = time.time()
    
    if not target_date_str:
        now_kst = datetime.datetime.now(ZoneInfo("Asia/Seoul"))
        target_date_str = now_kst.strftime("%Y-%m-%d")

    clean_date = target_date_str.replace("-", "").strip()
    formatted_date = f"{clean_date[:4]}-{clean_date[4:6]}-{clean_date[6:8]}"
    
    if not output_dir:
        output_dir = os.path.join(config.DATA_DIR, formatted_date)
    os.makedirs(output_dir, exist_ok=True)

    print("\n" + "=" * 75, flush=True)
    print(f"🚀 [1분 상식 파이프라인 가동] 날짜: {formatted_date} (출력: {output_dir})", flush=True)
    print("=" * 75, flush=True)

    # Step 1: 랭킹 뉴스 크롤링
    print("\n[Step 1] 네이버 랭킹 뉴스 83개 언론사 전수 수집 중...", flush=True)
    articles = get_naver_ranking_by_date(formatted_date, force_refresh=force_refresh)
    print(f"  -> 수집 완료: 총 {len(articles)}개 기사 확보", flush=True)

    # Step 2: 킬러 토픽 자동 선정
    print("\n[Step 2] 1위 킬러 토픽 자동 심사 및 본문 수집 중...", flush=True)
    topic_info = select_best_killer_topic(formatted_date, force_refresh=force_refresh)
    print(f"  -> 선정 완료: [{topic_info['press']}] {topic_info['shorts_title']}", flush=True)

    # Step 3: 4씬 대본 생성 (1:1 음성-자막 일치)
    print("\n[Step 3] 1:1 음성-자막 무결점 대본 생성 중...", flush=True)
    script_data = generate_script(topic_info, force_refresh=force_refresh, output_dir=output_dir)
    print(f"  -> 대본 완료: {len(script_data['sections'])}개 씬 생성 완료", flush=True)

    # Step 4: 원테이크 TTS & Whisper 싱크 분석
    print("\n[Step 4] 원테이크 TTS 및 Whisper 단어 싱크 분석 중...", flush=True)
    audio_path, durations = process_audio_and_sync(
        script_data, output_dir, voice_name=voice_name, force_refresh=force_refresh
    )
    print(f"  -> 오디오 싱크 완료: 총 {sum(durations):.1f}초 (씬별: {durations})", flush=True)

    # Step 5: 3단 상시 인식 헤더 & 48pt 하이라이트 자막 렌더링
    print("\n[Step 5] 3단 상시 인식 헤더 및 48pt 자막 렌더링 중 (엔딩 슬라이드 제거)...", flush=True)
    video_path = render_news_short(
        script_data, durations, audio_path, output_dir, formatted_date,
        category=topic_info.get("category"), bgm_filename=bgm, force_refresh=force_refresh
    )

    # Step 6: 유튜브 동적 메타데이터(제목·설명·태그) 생성 및 업로드
    yt_meta = generate_youtube_metadata(script_data, topic_info)
    upload_url = None
    if not skip_upload:
        print("\n[Step 6] 동적 메타데이터 기반 유튜브 업로드 진행 중...", flush=True)
        upload_url = upload_video(
            video_path=video_path,
            title=yt_meta["title"],
            description=yt_meta["description"],
            tags=yt_meta.get("tags"),
            privacy_status="private"
        )
        if upload_url:
            print(f"  🎉 [YouTube 업로드 성공] {upload_url}", flush=True)
        else:
            print("  ⚠️ [YouTube 업로드 실패 또는 인증 미설정]", flush=True)
    else:
        print("\n[Step 6] --skip-upload 설정에 따라 유튜브 업로드를 건너뜁니다.", flush=True)

    elapsed = round(time.time() - start_time, 1)
    print("\n" + "=" * 75, flush=True)
    print(f"🎉 [{formatted_date} 쇼츠 영상 제작 완료!] 소요 시간: {elapsed}초", flush=True)
    print(f"   ▶ 완성 비디오: {video_path}", flush=True)
    if upload_url:
        print(f"   ▶ 유튜브 주소: {upload_url}", flush=True)
    print(f"   ▶ 검증 프레임: {output_dir}/frame_s0~s3.jpg", flush=True)
    print("=" * 75 + "\n", flush=True)

    summary = {
        "status": "success",
        "date": formatted_date,
        "slot": slot,
        "topic": topic_info,
        "script": script_data,
        "durations": durations,
        "video_path": video_path,
        "youtube_url": upload_url,
        "youtube_metadata": yt_meta,
        "output_dir": output_dir,
        "elapsed_sec": elapsed
    }
    
    with open(os.path.join(output_dir, "pipeline_run.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    return summary

def main():
    parser = argparse.ArgumentParser(description="1분 상식 쇼츠 자동화 파이프라인 (news_pilot 기반)")
    parser.add_argument("--date", type=str, default=None, help="제작할 날짜 (YYYY-MM-DD)")
    parser.add_argument("--slot", type=str, default="auto", help="발행 슬롯 (auto/morning/evening)")
    parser.add_argument("--category", type=str, default=None, help="타겟 카테고리 (하위 호환)")
    parser.add_argument("--force", action="store_true", help="기존 캐시 무시하고 강제 재생성")
    parser.add_argument("--voice", type=str, default="Puck", help="TTS 성우 (Puck, Fenrir 등)")
    parser.add_argument("--bgm", type=str, default="auto", help="BGM 파일명 또는 별칭 (auto, danger, upbeat, mystery 등)")
    parser.add_argument("--skip-upload", action="store_true", help="유튜브 업로드를 건너뛰고 영상만 렌더링")
    
    args = parser.parse_args()

    target_date = args.date
    if not target_date:
        now_kst = datetime.datetime.now(ZoneInfo("Asia/Seoul"))
        target_date = now_kst.strftime("%Y-%m-%d")

    run_pipeline(
        target_date_str=target_date,
        force_refresh=args.force,
        voice_name=args.voice,
        bgm=args.bgm,
        slot=args.slot,
        skip_upload=args.skip_upload
    )

if __name__ == "__main__":
    main()
