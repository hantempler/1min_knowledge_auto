import os
import json
import sys
import logging
import time
import traceback

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
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# src 내부 모듈 임포트
import config
from topic_sourcing import get_todays_topic
from script_gen import generate_script
from research import generate_research_brief
from fact_check import fact_check_script
from bgm import download_bgm
from tts_gen import generate_tts_per_section
from renderer import render_video
from upload_youtube import upload_video

def _run_pipeline(target_date_str=None, skip_upload=False, target_category=None, slot="auto"):
    slot_norm = config.resolve_slot(slot)
    slot_conf = config.SLOT_CONFIG.get(slot_norm, config.SLOT_CONFIG["morning"])
    print(f"=== 1분 상식 파이프라인 시작 [{slot_conf['header_badge']} (슬롯: {slot_norm})] ===")
    
    # 0. 작업 폴더 생성 (오전/오후 슬롯 분리)
    daily_dir = config.get_daily_dir(target_date_str, slot=slot_norm)
    print(f"\n[0/8] 작업 폴더 준비: {daily_dir}")
    
    # 1. 주제 선정
    topic_file = os.path.join(daily_dir, "0_topic_selection.json")
    if os.path.exists(topic_file):
        print(f"\n[1/8] (캐시됨) [{slot_norm.upper()}] 주제 로드 중...")
        with open(topic_file, "r", encoding="utf-8") as f:
            topic = json.load(f).get("topic")
    else:
        print(f"\n[1/8] [{slot_norm.upper()}] 맞춤 주제 선정 중...")
        topic = get_todays_topic(daily_dir, reference_date=target_date_str, target_category=target_category, slot=slot_norm)
        
    print(f"-> 오늘의 주제: {topic}")
    if not topic:
        raise RuntimeError("주제 선정 실패. 파이프라인을 중단합니다.")
        
    # 2. 지식 조사 카드 작성
    research_file = os.path.join(daily_dir, "1_research_brief.json")
    legacy_research_file = os.path.join(daily_dir, "1_research.json")
    if not os.path.exists(research_file) and os.path.exists(legacy_research_file):
        print("\n[2/8] 구 형식 조사 카드 발견. 새 파일명으로 이관합니다...")
        with open(legacy_research_file, "r", encoding="utf-8") as f:
            research_brief = json.load(f)
        with open(research_file, "w", encoding="utf-8") as f:
            json.dump(research_brief, f, ensure_ascii=False, indent=2)
    elif os.path.exists(research_file):
        print("\n[2/8] (캐시됨) 주제 조사 및 출처 정리 로드 중...")
        with open(research_file, "r", encoding="utf-8") as f:
            research_brief = json.load(f)
    else:
        print("\n[2/8] 주제 조사 및 출처 정리 중...")
        research_brief = generate_research_brief(topic, daily_dir)
        
    if not research_brief:
        raise RuntimeError("조사 카드 생성 실패. 파이프라인을 중단합니다.")

    # 3-4. 대본 작성 + 팩트체크 (자동수정 루프)
    def _needs_revision(check: dict | None) -> bool:
        if not check:
            return True
        return not check.get("approved")

    script_file = os.path.join(daily_dir, "3_script.json")
    fact_check_file = os.path.join(daily_dir, "2_fact_check.json")
    script_data = None
    fact_check = None
    feedback = None

    for attempt in range(1, 4):
        if attempt == 1 and os.path.exists(script_file):
            print("\n[3/8] (캐시됨) 대본 로드 중...")
            with open(script_file, "r", encoding="utf-8") as f:
                script_data = json.load(f)
        else:
            if attempt == 1:
                print(f"\n[3/8] [{slot_norm.upper()}] 0초 훅 & 스토리텔링 대본 작성 중...")
            else:
                print(f"\n[3/8] 팩트체크 지적 반영하여 대본 재생성 중... ({attempt}/3)")
            script_data = generate_script(topic, daily_dir, research_brief, feedback=feedback, slot=slot_norm)

        if not script_data:
            raise RuntimeError("대본 작성 실패. 파이프라인을 중단합니다.")
        print(f"-> 컷 수: {len(script_data.get('script_sections', []))}컷")

        if attempt == 1 and os.path.exists(fact_check_file) and feedback is None:
            print("\n[4/8] (캐시됨) 대본 사실관계 검토 로드 중...")
            with open(fact_check_file, "r", encoding="utf-8") as f:
                fact_check = json.load(f)
        else:
            print("\n[4/8] 대본 사실관계 검토 중...")
            fact_check = fact_check_script(topic, research_brief, script_data, daily_dir)

        if not _needs_revision(fact_check):
            print("-> 팩트체크 통과")
            break

        feedback = fact_check
        if attempt < 3:
            print(f"-> 지적 {len(fact_check.get('issues', []))}건 발견. 수정 후 재생성합니다.")
        else:
            raise RuntimeError("대본 사실 검토를 통과하지 못했습니다. 2_fact_check.json을 확인하세요.")

    # 5. 음성 합성 (슬롯별 속도 및 전담 성우)
    audio_path = os.path.join(daily_dir, "4_audio.mp3")
    if not os.path.exists(audio_path):
        audio_path = os.path.join(daily_dir, "4_audio.wav")

    durations_path = os.path.join(daily_dir, "4_audio_durations.json")
    section_durations = None
    if os.path.exists(audio_path):
        print(f"\n[5/8] (캐시됨) AI 성우 음성(TTS) 로드 중... ({audio_path})")
        if os.path.exists(durations_path):
            try:
                with open(durations_path, "r", encoding="utf-8") as f:
                    section_durations = json.load(f).get("durations")
            except Exception as e:
                print(f"구간 길이 파일 읽기 실패: {e}")
    else:
        print(f"\n[5/8] AI 성우 음성(TTS) 생성 중 (슬롯: {slot_norm.upper()}, {slot_conf['speaking_rate']}x 배속)...")
        audio_path, section_durations = generate_tts_per_section(script_data, daily_dir, slot=slot_norm)

    if not audio_path:
        raise RuntimeError("음성 생성 실패. 파이프라인을 중단합니다.")

    # 6. 슬롯 분위기에 맞는 BGM 다운로드
    print(f"\n[6/8] [{slot_norm.upper()}] 분위기에 맞는 BGM 다운로드 중...")
    bgm_path = download_bgm(topic, daily_dir, slot=slot_norm)
        
    # 7. 영상 렌더링 (슬롯 배지 + 테마 컬러)
    print(f"\n[7/8] 영상 및 자막 렌더링 중 (테마: {slot_conf['theme']})...")
    video_path = render_video(audio_path, script_data, daily_dir, topic, bgm_path, section_durations, slot=slot_norm)
    if not video_path:
        raise RuntimeError("영상 렌더링 실패. 파이프라인을 중단합니다.")
        
    if skip_upload:
        print(f"\n[8/8] (업로드 건너뜀) 로컬 영상 렌더링 완료: {video_path}")
        print("\n=== 파이프라인 완료 ===")
        return video_path

    # 8. 유튜브 업로드 (OAuth 연동)
    print("\n[8/8] 유튜브 쇼츠 자동 업로드 중 (비공개 상태로 업로드)...")
    cover_title = script_data.get("cover_title", topic)
    title = f"{slot_conf['title_prefix']} {cover_title}"
    
    useful_title = script_data.get("useful_source_title", "")
    useful_url = script_data.get("useful_source_url", "")
    
    description = f"{topic}에 대한 {slot_conf['header_badge']}입니다!\n\n"
    if useful_title and useful_url:
        description += f"💡 오늘 소개된 유용한 정보:\n👉 {useful_title}\n🔗 {useful_url}\n\n"
    license_path = os.path.join(daily_dir, "bgm_license.json")
    if bgm_path and os.path.exists(license_path):
        with open(license_path, encoding="utf-8") as file:
            bgm_license = json.load(file)
        description += (
            "🎵 BGM: {title} - {artist}\n"
            "🔗 {url}\n"
            "📄 License: {license}\n\n"
        ).format(**bgm_license)

    if slot_norm == "morning":
        description += "#쇼츠 #지식브리핑 #1분상식 #상식 #경제 #생활꿀팁"
    else:
        description += "#쇼츠 #지식브리핑 #1분상식 #미스터리 #역사 #교양"
    
    upload_url = upload_video(video_path, title, description)
    
    print("\n=== 파이프라인 완료 ===")
    if upload_url:
        print(f"업로드 주소: {upload_url}")
    else:
        raise RuntimeError("업로드 실패 또는 주소를 받아오지 못했습니다.")
    return video_path


def main():
    """실행 로그(pipeline.log)와 결과 요약(pipeline_run.json)을 남기는 진입점."""
    import argparse
    parser = argparse.ArgumentParser(description="1분 상식 브리핑 쇼츠 생성 파이프라인 (오전/오후 이원화)")
    parser.add_argument("--date", type=str, default=None, help="생성 기준 날짜 (YYYY-MM-DD 또는 YYYYMMDD)")
    parser.add_argument("--category", type=str, default=None, help="타겟 카테고리 (경제, 기술, 생활 등)")
    parser.add_argument("--slot", type=str, default="auto", choices=["auto", "morning", "evening", "am", "pm"], help="발행 슬롯 (auto: KST 시간대 자동 감지, morning/am: 오전 지식 브리핑, evening/pm: 오후 지식 브리핑)")
    parser.add_argument("--skip-upload", action="store_true", help="유튜브 업로드를 건너뛰고 영상만 렌더링")
    args = parser.parse_args()

    norm_slot = config.resolve_slot(args.slot)
    daily_dir = config.get_daily_dir(args.date, slot=norm_slot)
    log_path = os.path.join(daily_dir, "pipeline.log")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(),
        ],
        force=True,
    )
    run_state = {
        "status": "running",
        "log_file": log_path,
        "target_date": args.date,
        "slot": norm_slot,
        "category": args.category,
        "skip_upload": args.skip_upload
    }
    start = time.time()
    try:
        _run_pipeline(target_date_str=args.date, skip_upload=args.skip_upload, target_category=args.category, slot=norm_slot)
        run_state["status"] = "done"
    except Exception:
        logging.exception("파이프라인 예외 발생")
        run_state["status"] = "error"
        run_state["traceback"] = traceback.format_exc()
        raise
    finally:
        run_state["duration_sec"] = round(time.time() - start, 1)
        try:
            with open(os.path.join(daily_dir, "pipeline_run.json"), "w", encoding="utf-8") as f:
                json.dump(run_state, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.warning(f"pipeline_run.json 저장 실패: {e}")


if __name__ == "__main__":
    main()

