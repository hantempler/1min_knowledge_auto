import os
import json
import sys

# 상위 폴더(루트)를 모듈 경로에 추가
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# src 내부 모듈 임포트
import config
from topic_sourcing import get_todays_topic
from script_gen import generate_script
from research import generate_research_brief
from fact_check import fact_check_script
from bgm import download_bgm
from tts_gen import generate_tts
from renderer import render_video
from upload_youtube import upload_video

def main():
    print("=== 1분 상식 브리핑 파이프라인 시작 (다이내믹 에디션 v2) ===")
    
    # 0. 작업 폴더 생성
    daily_dir = config.get_daily_dir()
    print(f"\n[0/5] 오늘자 작업 폴더 준비: {daily_dir}")
    
    # 1. 주제 선정
    topic_file = os.path.join(daily_dir, "0_topic_selection.json")
    if os.path.exists(topic_file):
        print("\n[1/8] (캐시됨) 최신 정세 기반 주제 로드 중...")
        with open(topic_file, "r", encoding="utf-8") as f:
            topic = json.load(f).get("topic")
    else:
        print("\n[1/8] 최신 정세 기반 주제 선정 중...")
        topic = get_todays_topic(daily_dir)
        
    print(f"-> 오늘의 주제: {topic}")
    if not topic:
        print("주제 선정 실패. 파이프라인을 종료합니다.")
        return
        
    # 2. 지식 조사 카드 작성
    research_file = os.path.join(daily_dir, "1_research_brief.json")
    if os.path.exists(research_file):
        print("\n[2/8] (캐시됨) 주제 조사 및 출처 정리 로드 중...")
        with open(research_file, "r", encoding="utf-8") as f:
            research_brief = json.load(f)
    else:
        print("\n[2/8] 주제 조사 및 출처 정리 중...")
        research_brief = generate_research_brief(topic, daily_dir)
        
    if not research_brief:
        print("조사 카드 생성 실패. 파이프라인을 종료합니다.")
        return

    # 3. 조사 카드 기반 스크립트 작성
    script_file = os.path.join(daily_dir, "3_script.json")
    if os.path.exists(script_file):
        print("\n[3/8] (캐시됨) 대본 로드 중...")
        with open(script_file, "r", encoding="utf-8") as f:
            script_data = json.load(f)
    else:
        print("\n[3/8] 조사 카드 기반 대본 작성 중...")
        script_data = generate_script(topic, daily_dir, research_brief)
        
    if not script_data:
        print("대본 작성 실패. 파이프라인을 종료합니다.")
        return
    print(f"-> 컷 수: {len(script_data.get('script_sections', []))}컷")
    
    # 4. 대본 사실 검토
    fact_check_file = os.path.join(daily_dir, "2_fact_check.json")
    if os.path.exists(fact_check_file):
        print("\n[4/8] (캐시됨) 대본 사실관계 검토 로드 중...")
        with open(fact_check_file, "r", encoding="utf-8") as f:
            fact_check = json.load(f)
    else:
        print("\n[4/8] 대본 사실관계 검토 중...")
        fact_check = fact_check_script(topic, research_brief, script_data, daily_dir)
        
    if not fact_check or not fact_check.get("approved"):
        print("대본 사실 검토를 통과하지 못했습니다. 2_fact_check.json을 확인하세요.")
        return

    # 5. 음성 합성
    audio_path = os.path.join(daily_dir, "4_audio.mp3")
    if not os.path.exists(audio_path):
        audio_path = os.path.join(daily_dir, "4_audio.wav")
        
    if os.path.exists(audio_path):
        print(f"\n[5/8] (캐시됨) AI 성우 음성(TTS) 로드 중... ({audio_path})")
    else:
        print("\n[5/8] AI 성우 음성(TTS) 생성 중 (Neural2-C 엔진)...")
        audio_path = generate_tts(script_data, daily_dir)
        
    if not audio_path:
        print("음성 생성 실패. 파이프라인을 종료합니다.")
        return

    # 6. 주제 분위기에 맞는 BGM 다운로드
    print("\n[6/8] 주제 분위기에 맞는 BGM 다운로드 중...")
    bgm_path = download_bgm(topic, daily_dir)
        
    # 7. 영상 렌더링 (BGM + Pexels + 3줄 요약 + 표지 + 상단 헤더)
    print("\n[7/8] 영상 및 자막 렌더링 중...")
    video_path = render_video(audio_path, script_data, daily_dir, topic, bgm_path)
    if not video_path:
        print("영상 렌더링 실패. 파이프라인을 종료합니다.")
        return
        
    # 8. 유튜브 업로드 (OAuth 연동)
    print("\n[8/8] 유튜브 쇼츠 자동 업로드 중 (비공개 상태로 업로드)...")
    cover_title = script_data.get("cover_title", topic)
    title = f"[1분 상식] {cover_title}"
    
    useful_title = script_data.get("useful_source_title", "")
    useful_url = script_data.get("useful_source_url", "")
    
    description = f"{topic}에 대한 오늘의 1분 상식 브리핑입니다!\n\n"
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
    description += "#쇼츠 #상식 #1분상식 #이슈"
    
    upload_url = upload_video(video_path, title, description)
    
    print("\n=== 파이프라인 완료 ===")
    if upload_url:
        print(f"업로드 주소: {upload_url}")
    else:
        print("업로드 실패 또는 주소를 받아오지 못했습니다.")

if __name__ == "__main__":
    main()
