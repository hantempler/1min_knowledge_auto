import json
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from google import genai
from google.genai import types

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from scraper import get_naver_headlines, get_am_news_data, get_pm_viral_data

def get_todays_topic(daily_dir=None, reference_date=None, target_category=None, slot="morning"):
    """오전(AM: 1분 팩트)과 오후(PM: 도파민 썰)에 맞춰 맞춤형 주제를 선정한다."""
    if daily_dir is None:
        daily_dir = config.DATA_DIR
    if reference_date is None:
        reference_date = datetime.now(ZoneInfo("Asia/Seoul")).date()
    elif isinstance(reference_date, str):
        clean_date = reference_date.replace("-", "").strip()
        reference_date = datetime.strptime(clean_date, "%Y%m%d").date()

    slot_norm = config.normalize_slot(slot)
    date_text = reference_date.strftime("%Y년 %m월 %d일")
    
    # 1. 슬롯별 맞춤 데이터 수집
    if slot_norm == "morning":
        print("  -> [오전/AM] 실생활·경제 랭킹 뉴스 수집 중...")
        try:
            news_data = get_am_news_data()
        except Exception as e:
            print(f"AM 뉴스 수집 실패: {e}")
            news_data = get_naver_headlines()
    else:
        print("  -> [오후/PM] 도파민 썰 & 기상천외 토픽 소스 수집 중...")
        try:
            news_data = get_pm_viral_data()
        except Exception as e:
            print(f"PM 소스 수집 실패: {e}")
            news_data = get_naver_headlines()
        
    news_context = ""
    if news_data:
        news_context = "[수집된 실시간 토픽 및 뉴스 후보 목록]\n"
        for idx, news in enumerate(news_data[:15], 1):
            news_context += f"{idx}. ({news.get('category', '기타')}) {news.get('title', '')} - {news.get('content', '')[:120]}\n"
    else:
        news_context = "[수집된 실시간 토픽 및 뉴스 후보 목록]\n데이터 수집에 실패하여 일반적인 흥미 주제 풀에서 선택합니다."

    # 기존 주제 이력(History) 로드
    used_topics_path = os.path.join(config.DATA_DIR, "used_topics.json")
    used_topics = []
    if os.path.exists(used_topics_path) and os.path.getsize(used_topics_path) > 2:
        try:
            with open(used_topics_path, "r", encoding="utf-8") as f:
                used_topics = json.load(f)
        except Exception as e:
            print(f"기존 주제 목록 읽기 실패: {e}")


    used_topics_context = ""
    if used_topics:
        used_topics_context = "\n[과거 다룬 주제 목록 - 중복 절대 금지]\n다음은 이전에 다루었던 주제들입니다. 이 목록에 있는 주제와 겹치거나 의미상 유사한 것은 절대 선정하지 마세요:\n" + ", ".join(used_topics[-40:]) + "\n"

    client = genai.Client(
        vertexai=True,
        project=config.GCP_PROJECT_ID,
        location=config.GCP_LOCATION,
    )
    
    cat_instruction = ""
    if target_category:
        cat_instruction = f"\n[필수 지정 카테고리]: 이번 영상은 반드시 '{target_category}' 분야에 관련된 주제를 선정하세요. (category 필드는 반드시 '{target_category}'로 지정)\n"

    # 슬롯별 선정 프롬프트 분기
    if slot_norm == "morning":
        role_instruction = """
당신은 출근길 시청자를 위한 '모닝 1분 팩트'의 메인 에디터입니다.
벤치마킹: 한국의 '1분미만', 글로벌 'How Money Works'

[오전 주제 선정 3대 원칙]
1. [피부 체감 & 손실 회피]: 오늘 뉴스를 바탕으로 시청자의 '내 지갑(돈), 일상 생활, 세금/제도, 건강/테크'에 직결되는 실전 지식 1개를 선정하세요. 단순 정치 공방이나 먼 나라 이야기는 탈락입니다.
2. [제목 프레이밍]: 신문 사설 같은 딱딱한 제목 대신, 시청자가 '어? 나 저거 모르는데?' 하고 엄지를 멈추게 하는 호기심 유발형 질문 또는 단정형 문장으로 작성하세요.
   (예: '금리가 내려도 내 대출 이자는 왜 바로 안 깎일까?', '스마트폰 배터리 수명 2배 늘리는 충전법의 진실', '전기세 폭탄 피하는 에어컨 설정 1위')
3. [시각적 구현 가능성]: Pexels 스톡 영상에서 스마트폰, 돈, 영수증, 은행, 사무실, 일상 가전 등 명확한 실물 사물이나 행동을 찾을 수 있는 소재여야 합니다.
"""
    else:
        role_instruction = """
당신은 퇴근길·취침 전 시청자의 뇌를 깨우는 '나이트 도파민 썰'의 메인 스토리텔러입니다.
벤치마킹: 글로벌 'Zack D. Films', 'MagnatesMedia', '사물궁이'

[오후 주제 선정 5대 바이럴 앵글 - 반드시 아래 5개 중 하나에 해당하는 주제만 선정]
1. 역사적 레전드 삽질: 선한 의도로 시작했다가 최악의 파멸을 맞은 사건 (예: 쥐 잡으라고 돈 줬더니 쥐 농장 차린 사건)
2. 인체/물리의 기괴한 원리: 극한 상황에서 몸속이나 기계 속에서 벌어지는 일 (예: 물에 빠졌을 때 폐와 기도에서 일어나는 1분의 진실)
3. 대기업/천재의 흑역사: 거대 브랜드나 국가가 숨기고 싶어했던 실수 (예: 코카콜라가 출시 3개월 만에 폐기한 음료)
4. 상식 파괴 진실 폭로: 우리가 학교나 사회에서 100% 믿고 있던 거짓말의 반전
5. 극한의 가상 시뮬레이션: 만약 ~하면 어떻게 될까? (예: 전 세계 모기가 하루 만에 멸종하면 벌어지는 일)

[제목 프레이밍]: 첫 문장을 듣자마자 친구한테 떠들고 싶어지는 도파민 유발형 제목으로 뽑으세요.
"""

    prompt = f"""
기준 날짜: {date_text} (한국 표준시 KST)
슬롯: {slot_norm.upper()} ({'오전 모닝 1분 팩트' if slot_norm == 'morning' else '오후 나이트 도파민 썰'})

{role_instruction}
{used_topics_context}
{news_context}
{cat_instruction}

반드시 아래 JSON만 출력하세요. 백틱이나 부연 설명 없이 순수 JSON만 반환하세요:
{{
  "topic": "시선을 사로잡는 강력한 숏츠 제목 (25자 이내)",
  "category": "{target_category if target_category else '경제, 기술, 역사, 과학, 사회, 생활, 의료, 우주, 환경, 문화 중 하나'}",
  "why_today": "이 주제가 왜 오늘 시청자에게 중요한지 1문장 (50~80자)",
  "knowledge_angle": "영상에서 다룰 핵심 원리, 반전 또는 실전 해결책 (1~2문장)",
  "slot": "{slot_norm}",
  "confidence": 0.95
}}
"""
    try:
        response = client.models.generate_content(
            model=config.MODEL_FAST,
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json"),
        )
        selection = json.loads(response.text.strip())
        topic = selection.get("topic", "").strip()
        if not topic:
            raise ValueError("Vertex AI가 주제를 반환하지 않았습니다.")

        # 10대 카테고리 매핑 및 정규화
        VALID_CATEGORIES = ["과학", "기술", "역사", "경제", "사회", "문화", "생활", "우주", "의료", "환경"]
        if target_category and target_category in VALID_CATEGORIES:
            selection["category"] = target_category
        else:
            raw_cat = selection.get("category", "").strip()
            matched_cat = None
            for vc in VALID_CATEGORIES:
                if vc in raw_cat:
                    matched_cat = vc
                    break
            selection["category"] = matched_cat if matched_cat else ("경제" if slot_norm == "morning" else "역사")

        selection["slot"] = slot_norm
        selection["reference_date"] = reference_date.isoformat()
        selection["selected_at"] = datetime.now(ZoneInfo("Asia/Seoul")).isoformat()
        os.makedirs(daily_dir, exist_ok=True)
        with open(os.path.join(daily_dir, "0_topic_selection.json"), "w", encoding="utf-8") as file:
            json.dump(selection, file, ensure_ascii=False, indent=2)
            
        # 새로운 주제 히스토리에 누적 업데이트
        if topic not in used_topics:
            used_topics.append(topic)
            with open(used_topics_path, "w", encoding="utf-8") as file:
                json.dump(used_topics, file, ensure_ascii=False, indent=2)

                
        return topic
    except Exception as error:
        import traceback
        traceback.print_exc()
        print(f"Vertex AI 주제 선정 오류: {error}")
        return None



if __name__ == "__main__":
    print("오늘의 오전 주제:", get_todays_topic(slot="morning"))
    print("오늘의 오후 주제:", get_todays_topic(slot="evening"))
