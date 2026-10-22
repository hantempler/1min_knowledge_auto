import os
import json
from google import genai
from google.genai import types
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

def generate_script(topic: str, daily_dir: str = None, research_brief: dict = None, feedback: dict | None = None, slot: str = "morning"):
    if daily_dir is None:
        daily_dir = config.DATA_DIR
        
    client = genai.Client(vertexai=True, project=config.GCP_PROJECT_ID, location=config.GCP_LOCATION)
    
    # 주제 선정 데이터(0_topic_selection.json) 읽어오기
    why_today = ""
    category = ""
    detected_slot = slot
    topic_file = os.path.join(daily_dir, "0_topic_selection.json")
    if os.path.exists(topic_file):
        try:
            with open(topic_file, "r", encoding="utf-8") as f:
                topic_data = json.load(f)
                why_today = topic_data.get("why_today", "")
                category = topic_data.get("category", "")
                detected_slot = topic_data.get("slot", slot)
        except Exception as e:
            print(f"주제 선정 데이터 읽기 실패: {e}")
            
    slot_norm = config.normalize_slot(detected_slot)
    slot_conf = config.SLOT_CONFIG.get(slot_norm, config.SLOT_CONFIG["morning"])
    base_system_prompt = slot_conf["system_prompt"]

    research_json = json.dumps(research_brief or {}, ensure_ascii=False, indent=2)
    why_today_context = f'\n[오늘의 주제 선정 배경 (참고용)]\n"{why_today}"\n' if why_today else ""
    feedback_context = ""
    if feedback:
        feedback_context = f"""
[이전 대본에 대한 팩트체크 수정 요청 - 반드시 반영하세요]
{json.dumps(feedback, ensure_ascii=False, indent=2)}
위 issues/corrections에 나온 과장된 수치, 단정적 표현, 조사카드에 없는 내용을 모두 고쳐서 새로 작성하세요.
"""
    
    if slot_norm == "morning":
        slot_style_guide = """
[오전 모닝 1분 팩트 대본 작성 규칙 (벤치마킹: 1분미만, How Money Works)]
1. [첫 문장 (0초 훅)]: '안녕하세요', '오늘 알아볼 것은' 같은 형식적 인사를 0.1초도 넣지 마.
   - 첫 컷(script_sections[0])의 narration은 즉시 시청자의 손실 회피 심리나 궁금증을 강하게 찌르는 문장으로 시작해.
   - 예: "오늘 뉴스에 나온 이 소식, 모르면 당신 통장만 털립니다.", "우리가 매일 쓰는 이 물건, 사실은..."
2. [단문 중심의 속도감]: 문장을 늘어뜨리지 말고 핵심만 팍팍 꽂히게 단문 위주로 작성해.
3. [피부 체감 비유]: 복잡한 용어나 수치를 '내 월급, 전기세, 스마트폰, 장바구니' 등 생활 밀착 비유로 설명해.
4. [마무리]: '오늘 동료들에게 아는 척하기 딱 좋은 한 줄 팩트'로 깔끔하게 정리해.
"""
    else:
        slot_style_guide = """
[오후 나이트 도파민 썰 대본 작성 규칙 (벤치마킹: Zack D. Films, MagnatesMedia)]
1. [첫 문장 (0초 훅)]: 인사나 서론 없이 첫 프레임부터 충격적 상황이나 기괴한 호기심으로 낚아채.
   - 예: "사실 우리가 알던 ~는 완전한 사기극이었습니다.", "만약 인간이 번개에 맞으면 몸속 혈관은 어떻게 될까요?"
2. [갈등과 서스펜스]: [평화로운 착각] -> [치명적 삽질/비하인드] -> [충격적인 반전 결말] 구조로 친구에게 썰을 풀듯 흥미진진하게 전개해.
3. [시각적 장면 전환]: 각 컷마다 Pexels에서 검색하기 좋은 구체적인 시각 장면 키워드를 지정해.
4. [마무리]: 영상이 끝나도 여운이 남는 강렬한 반전이나 다음 생각을 유발하는 질문으로 끝내.
"""

    prompt = f"""
{base_system_prompt}

오늘의 주제: "{topic}"{why_today_context}

다음 조사 카드를 반드시 근거로 사용하세요. 조사 카드에 없는 허위 사실을 지어내지 마세요.
{research_json}
{feedback_context}

{slot_style_guide}

[중요 JSON 출력 조건]
1. 출력은 오직 **JSON 형식**이어야 해. 백틱(```json) 없이 바로 JSON 객체만 출력해.
2. `cover_title`: 영상 첫 화면에 노출될 짧고 강력한 제목 (15자 이내)
3. `script_sections`: 대본을 4~5개의 짧은 문단(각 6~9초 분량)으로 나눠서 배열로 구성해.
    - 각 객체는 다음 필드를 반드시 포함해야 해:
      - `narration`: TTS가 읽을 한 호흡의 구어체 대사
      - `caption`: 화면에 굵게 표시할 2줄 이내의 짧은 자막 (이모지 금지)
      - `highlight_word`: 자막 중 화면에서 노란색으로 가장 강조할 핵심 단어 1개 (예: "대출이자", "사기극", "폭발")
      - `bg_keyword`: Pexels 검색용 영어 구체적 장면 키워드 2~4단어 (추상명사 금지)
    - 전체 `narration`은 공백 포함 320~420자 분량으로 제한해.
4. `summary_takeaway`: 아웃트로에서 기억해야 할 1~2줄 핵심 요약/반전 (40~70자 내외).
5. `useful_source_title`: 시청자가 더 깊이 알아볼 수 있는 실제 출처/뉴스 기사 제목
6. `useful_source_url`: 위 출처의 안내 또는 실제 링크
7. `cover_keyword`: 표지 사진용 사물/건물/자연 Pexels 영어 키워드 2~4단어 (인물 얼굴 클로즈업 제외)
8. `summary_keyword`: 마무리 사진용 Pexels 영어 키워드 2~4단어
9. 모든 텍스트에 이모지나 특수기호(🚀, ✅ 등)는 절대 넣지 마 (렌더링 깨짐 방지).

JSON 포맷 예시:
{{
    "cover_title": "금리 인하의 비밀",
    "script_sections": [
        {{"narration": "금리가 내렸다는데 왜 내 대출 이자는 그대로일까요?", "caption": "금리 인하에도 대출 이자가 그대로인 이유", "highlight_word": "대출이자", "bg_keyword": "bank exterior architecture"}},
        {{"narration": "은행의 가산금리와 변동 주기 때문입니다.", "caption": "가산금리와 6개월 변동 주기의 비밀", "highlight_word": "가산금리", "bg_keyword": "money cash calculation"}},
        {{"narration": "기존 대출은 정해진 주기가 지나야 새 금리가 적용됩니다.", "caption": "주기가 지나야 적용되는 금리", "highlight_word": "변동주기", "bg_keyword": "calendar planner clock"}},
        {{"narration": "결국 내 대출 약정서의 금리 갱신 날짜를 확인해야 손해를 안 봅니다.", "caption": "대출 약정서 확인이 필수", "highlight_word": "약정서", "bg_keyword": "contract document signature"}}
    ],
    "summary_takeaway": "금리 인하 소식에 속지 말고, 내 대출 약정서의 금리 변동 주기를 먼저 확인하세요.",
    "useful_source_title": "한국은행 통화정책 안내",
    "useful_source_url": "한국은행 홈페이지 '통화정책' 메뉴에서 기준금리 변동 내역을 확인할 수 있습니다."
}}
"""
    
    try:
        response = client.models.generate_content(
            model=config.MODEL_PRO,
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
        
        # Pydantic/JSON parsing
        result = json.loads(response.text.strip())
        result["topic"] = topic
        result["slot"] = slot_norm
        if category:
            result["category"] = category
        sections = result.get("script_sections", [])
        if not 4 <= len(sections) <= 5:
            raise ValueError("script_sections는 4~5개여야 합니다.")
        narration_length = sum(
            len(section.get("narration", "")) for section in sections
        )
        if not 280 <= narration_length <= 500:
            raise ValueError(
                f"narration 분량이 적절하지 않습니다: {narration_length}자"
            )
        for section in sections:
            if not all(section.get(key) for key in ("narration", "caption", "bg_keyword")):
                raise ValueError("각 대본 구간에 narration, caption, bg_keyword가 필요합니다.")
            section["text"] = section["narration"]
            if "highlight_word" not in section or not section["highlight_word"]:
                words = section["caption"].split()
                section["highlight_word"] = words[0] if words else ""
        for key in ("cover_keyword", "summary_keyword"):
            if not result.get(key) or not result[key].strip():
                # 폴백
                result[key] = "abstract technology motion"
        
        # Save JSON script to data dir
        script_path = os.path.join(daily_dir, "3_script.json")
        with open(script_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
            
        return result
    except Exception as e:
        print(f"스크립트 생성 오류: {e}")
        return None

if __name__ == "__main__":
    test_topic = "연말정산 미리 준비하는 꿀팁"
    print("오전 대본 생성 테스트:")
    res_am = generate_script(test_topic, slot="morning")
    print(json.dumps(res_am, ensure_ascii=False, indent=2))

