import json
import os
import sys
from datetime import date, datetime
from zoneinfo import ZoneInfo

from google import genai
from google.genai import types

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from scraper import get_naver_headlines

def get_todays_topic(daily_dir=None, reference_date=None):
    """네이버 뉴스를 크롤링한 후, Vertex AI가 그 내용을 바탕으로 오늘의 상식 주제를 선정한다."""
    if daily_dir is None:
        daily_dir = config.DATA_DIR
    if reference_date is None:
        reference_date = datetime.now(ZoneInfo("Asia/Seoul")).date()

    date_text = reference_date.strftime("%Y년 %m월 %d일")
    
    # 1. 뉴스 데이터 수집
    print("  -> 실시간 주요 뉴스 수집 중...")
    try:
        news_data = get_naver_headlines()
    except Exception as e:
        print(f"뉴스 수집 실패: {e}")
        news_data = []
        
    news_context = ""
    if news_data:
        news_context = "[오늘의 주요 뉴스 목록]\n"
        for idx, news in enumerate(news_data[:15], 1): # 너무 많으면 토큰 낭비이므로 15개 제한
            news_context += f"{idx}. ({news['category']}) {news['title']}\n"
    else:
        news_context = "[오늘의 주요 뉴스 목록]\n뉴스 수집에 실패하여 현재 상황을 알 수 없습니다. 평년 기준의 일반적인 관심사를 바탕으로 작성해주세요."

    # 기존 주제 이력(History) 로드
    used_topics_path = os.path.join(config.DATA_DIR, "used_topics.json")
    used_topics = []
    if os.path.exists(used_topics_path):
        try:
            with open(used_topics_path, "r", encoding="utf-8") as f:
                used_topics = json.load(f)
        except Exception as e:
            print(f"기존 주제 목록 읽기 실패: {e}")

    used_topics_context = ""
    if used_topics:
        used_topics_context = "\n[과거 다룬 주제 목록 - 중복 절대 금지]\n다음은 이전에 다루었던 주제들입니다. 이 목록에 있는 주제와 겹치거나 의미상 매우 유사한 개념은 절대 선정하지 마세요:\n" + ", ".join(used_topics) + "\n"

    client = genai.Client(
        vertexai=True,
        project=config.GCP_PROJECT_ID,
        location=config.GCP_LOCATION,
    )
    
    prompt = f"""
기준 날짜: {date_text} (한국 표준시 KST, UTC+09:00)

당신은 '1분 상식 브리핑'의 주제 선정자입니다.
아래 제공된 [오늘의 주요 뉴스 목록]을 꼼꼼히 읽어보고, 오늘 대중들이 이 이슈를 이해하기 위해 가장 필요로 하는 핵심 상식이나 개념을 단 하나만 선정하세요.
{used_topics_context}
{news_context}

[당신의 역할 및 선정 기준]
1. 단순히 기사의 제목이나 단기 사건을 요약해서는 안 됩니다.
2. 현재 뉴스를 계기로 사람들이 가장 궁금해할 만한 과학 원리, 역사적 배경, 경제 개념, 사회 현상, 문화의 유래를 고르세요.
3. 예시: 한은 기준금리 동결 뉴스가 있다면 -> '금리와 환율의 상관관계 원리' 를 선정
4. 시청자가 제목만 보고도 호기심을 느낄 수 있도록 매력적인 상식 개념을 도출하세요.
5. 1분 안에 하나의 개념을 정확히 설명할 수 있도록 주제를 너무 넓지 않게 구체화하세요.
6. 인공지능, 챗GPT, 반도체, 로봇 주제는 제공된 뉴스에 직접적인 관련이 있을 때만 선택하세요.

반드시 아래 JSON만 출력하세요.
{{
  "topic": "선정한 짧은 상식 주제",
  "category": "과학, 역사, 경제, 사회, 문화, 생활 중 하나",
  "why_today": "제공된 뉴스와 연관지어, 왜 지금 이 상식에 관심을 가질 만한지 설명",
  "knowledge_angle": "1분 동안 설명할 핵심 원리 또는 배경",
  "confidence": 0.0
}}
"""
    try:
        response = client.models.generate_content(
            model="gemini-2.5-pro",
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json"),
        )
        selection = json.loads(response.text.strip())
        topic = selection.get("topic", "").strip()
        if not topic:
            raise ValueError("Vertex AI가 주제를 반환하지 않았습니다.")

        selection["reference_date"] = reference_date.isoformat()
        selection["selected_at"] = datetime.now(ZoneInfo("Asia/Seoul")).isoformat()
        os.makedirs(daily_dir, exist_ok=True)
        with open(os.path.join(daily_dir, "0_topic_selection.json"), "w", encoding="utf-8") as file:
            json.dump(selection, file, ensure_ascii=False, indent=2)
            
        # 새로운 주제 히스토리에 누적 업데이트
        if topic not in used_topics:
            used_topics.append(topic)
            with open(used_topics_path, "w", encoding="utf-8") as f:
                json.dump(used_topics, f, ensure_ascii=False, indent=2)
                
        return topic
    except Exception as error:
        print(f"Vertex AI 주제 선정 오류: {error}")
        return None


if __name__ == "__main__":
    print("오늘의 상식 주제:", get_todays_topic())
