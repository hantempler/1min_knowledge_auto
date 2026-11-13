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

def determine_publish_mode(schedule_hour_kst: int = 19, schedule_min_kst: int = 0) -> tuple:
    """
    당일 영상 발행 모드 결정:
    1. 현재 시각이 저녁 7시(19:00 KST) 이전인 경우:
       -> 당일 저녁 7시 정각 예약 공개 (privacyStatus: 'private', publishAt: 당일 19:00 UTC)
    2. 현재 시각이 이미 저녁 7시(19:00 KST)를 지난 경우:
       -> 내일로 미루지 않고 즉시 전체 공개 (privacyStatus: 'public', publishAt: None)
    
    반환값: (privacy_mode, publish_at_utc, scheduled_kst_str, log_message)
    """
    now_kst = datetime.datetime.now(ZoneInfo("Asia/Seoul"))
    target_kst = now_kst.replace(hour=schedule_hour_kst, minute=schedule_min_kst, second=0, microsecond=0)
    
    if now_kst < target_kst:
        target_utc = target_kst.astimezone(ZoneInfo("UTC"))
        publish_at_utc = target_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        kst_str = target_kst.strftime("%Y-%m-%d %H:%M:%S")
        log_msg = f"당일 저녁 {schedule_hour_kst}시 예약 발행 (예약 일시: {kst_str} KST)"
        return "private", publish_at_utc, kst_str, log_msg
    else:
        log_msg = f"당일 저녁 {schedule_hour_kst}시 경과 -> 즉시 전체 공개 (public) 발행"
        return "public", None, None, log_msg

def run_pipeline(
    target_date_str: str = None,
    force_refresh: bool = False,
    voice_name: str = "Puck",
    output_dir: str = None,
    bgm: str = "auto",
    slot: str = "auto",
    skip_upload: bool = False,
    schedule_hour: int = 19
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

    # Step 6: 유튜브 동적 메타데이터 생성 및 매일 저녁 7시(19:00 KST) 예약 업로드
    yt_meta = generate_youtube_metadata(script_data, topic_info)
    upload_url = None
    scheduled_kst = None
    if not skip_upload:
        # 안전한 딕셔너리 키 추출 (KeyError 원천 방어)
        yt_title = yt_meta.get("title") or yt_meta.get("youtube_title") or f"{topic_info.get('shorts_title', '1분 상식')} #shorts"
        yt_desc = yt_meta.get("description") or yt_meta.get("youtube_description") or ""
        yt_tags = yt_meta.get("tags") or yt_meta.get("youtube_tags") or ["1분상식", "쇼츠"]

        # 발행 모드 결정 (19시 이전: 당일 19시 예약 / 19시 이후: 즉시 전체 공개)
        privacy_mode, publish_at_utc, scheduled_kst, publish_log = determine_publish_mode(schedule_hour_kst=schedule_hour)
        print(f"\n[Step 6] 유튜브 업로드 진행 중... ({publish_log})", flush=True)

        upload_url = upload_video(
            video_path=video_path,
            title=yt_title,
            description=yt_desc,
            tags=yt_tags,
            privacy_status=privacy_mode,
            publish_at=publish_at_utc
        )
        if upload_url:
            if scheduled_kst:
                print(f"  🎉 [YouTube 예약 업로드 성공] {upload_url} (공개 예정: {scheduled_kst} KST)", flush=True)
            else:
                print(f"  🎉 [YouTube 즉시 전체공개 성공] {upload_url}", flush=True)
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
        if scheduled_kst:
            print(f"   ▶ 공개 예약일: {scheduled_kst} KST", flush=True)
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
        "youtube_scheduled_kst": scheduled_kst,
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
    parser.add_argument("--schedule-hour", type=int, default=19, help="유튜브 예약 발행 KST 시 (기본값: 19 = 저녁 7시)")
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
        skip_upload=args.skip_upload,
        schedule_hour=args.schedule_hour
    )

if __name__ == "__main__":
    main()
