import os
import json
from google import genai
from google.genai import types
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

def generate_script(topic: str, daily_dir: str = None, research_brief: dict = None):
    if daily_dir is None:
        daily_dir = config.DATA_DIR
        
    client = genai.Client(vertexai=True, project=config.GCP_PROJECT_ID, location=config.GCP_LOCATION)
    
    # 주제 선정 배경(why_today) 읽어오기
    why_today = ""
    topic_file = os.path.join(daily_dir, "0_topic_selection.json")
    if os.path.exists(topic_file):
        try:
            with open(topic_file, "r", encoding="utf-8") as f:
                topic_data = json.load(f)
                why_today = topic_data.get("why_today", "")
        except Exception as e:
            print(f"주제 선정 데이터 읽기 실패: {e}")
            
    research_json = json.dumps(research_brief or {}, ensure_ascii=False, indent=2)
    why_today_context = f'\n[오늘의 주제 선정 배경 (참고용)]\n"{why_today}"\n' if why_today else ""
    
    prompt = f"""
{config.SYSTEM_PROMPT}

오늘의 1분 상식 주제: "{topic}"{why_today_context}

다음 조사 카드를 반드시 근거로 사용하세요. 조사 카드에 없는 사실을 새로 만들지 마세요.
{research_json}

위 주제로 유튜브 숏츠 대본을 작성해줘.
정확한 설명체로 작성해줘. 예능톤, 밈, 유행어, 과장된 비유, 감탄사 중심의 문장을 사용하지 마.
시청자가 개념을 이해할 수 있도록 정의, 작동 원리, 실제 사례 또는 영향 순서로 설명해.

[중요 조건]
1. 출력은 오직 **JSON 형식**이어야 해. 백틱(```json) 없이 바로 JSON 객체만 출력해.
2. `cover_title`: 영상 첫 화면에 노출될 짧고 명확한 제목 (15자 이내)
3. `script_sections`: 대본을 4~5개의 짧은 문단(각 5~10초 분량)으로 나눠서 배열로 구성해.
    - [오프닝 작성 규칙]: 제공된 `[오늘의 주제 선정 배경]`을 활용하여 첫 문단(`script_sections[0]`)을 작성해. 단, '최근 뉴스에서~', '오늘 알아볼 주제는~' 같은 정형화된 뉴스 앵커 톤의 도입부는 절대 쓰지 마. 시청자의 일상적인 호기심이나 궁금증을 자연스럽게 자극하며 바로 이야기의 본론으로 끌어들여.
    - [내용의 깊이 및 분할]: 겉핥기식 요약을 피하고, 주제에 대한 흥미로운 역사적 배경, 흔한 오해, 숨겨진 원리 등 깊이 있는 지식을 종합적으로 다뤄. 이 풍부한 이야기를 특정 틀에 얽매이지 말고, 내용의 논리적·시각적 전환(장면 전환)에 맞춰 자연스럽게 4~5개의 씬으로 분할해.
    - 각 객체는 `narration`(TTS가 읽을 대사), `caption`(화면에 표시할 짧은 자막), `bg_keyword`(Pexels 검색용 영어 장면 키워드 2~4단어)를 가져야 해.
    - `caption`은 한 화면에 읽히도록 짧게 만들고, 영문 병기와 이모지는 넣지 마.
    - `bg_keyword`는 추상 개념명(예: atmospheric refraction, inflation)이 아니라 실제 화면에 보일 장면(예: sun halo sky, sunrise horizon, autumn leaves closeup)을 사용해.
    - 자막 내용과 배경 장면이 직접 연결되어야 하며, 사람·도시·자연 등 검색 결과가 명확한 시각 소재를 우선해.
    - 전체 `narration`은 공백 포함 330~430자 분량으로 제한해. 설명을 반복하거나 인사말을 길게 쓰지 마.
    - 마지막 `narration`은 "다음 시간에 만나요", "이제 아셨죠", "1분 상식 끝" 같은 관성적인 마무리 없이 핵심을 한 문장으로 각인시키며 끝내.
4. 내용 구성: 단순 꿀팁이 아니라 시청자에게 명확한 '지식(교양, 원리, 유래 등)'을 하나 전달해야 해.
5. `summary_3_lines`: 대본 내용을 바탕으로 한 핵심 3줄 요약을 문자열 배열로 제공해. 단, '~입니다', '~습니다' 같은 서술어는 절대 쓰지 말고, 간결한 명사형 종결이나 음슴체('~임', '~함', '관측됨' 등)로 핵심만 요약해. 화면에 잘리지 않도록 각 줄은 공백을 포함하여 무조건 30자를 넘지 않게 극도로 짧게 작성해.
6. `useful_source_title`: 시청자가 이 상식을 더 깊이 알아볼 수 있는 실제 출처. 뉴스가 출처인 경우, 단순히 '네이버 뉴스 헤드라인'이 아니라 실제 '뉴스 기사의 제목'을 작성해. (예: '한국은행 경제용어사전', '구체적인 기사 제목')
7. `useful_source_url`: 위 소스에 대한 안내나 실제 URL. 뉴스가 출처인 경우, 포털 메인 주소(예: https://news.naver.com)가 아니라 해당 기사의 '실제 구체적인 URL(직접 링크)'을 제공해.

JSON 포맷 예시:
{{
    "cover_title": "빅스텝의 의미",
    "script_sections": [
        {{"narration": "빅스텝은 중앙은행이 기준금리를 한 번에 0.5퍼센트포인트 올리는 조치입니다.", "caption": "빅스텝의 정의", "bg_keyword": "interest rate"}},
        {{"narration": "금리가 오르면 대출 비용이 증가하고, 가계와 기업의 소비와 투자가 줄어들 수 있습니다.", "caption": "금리 인상이 소비와 투자에 미치는 영향", "bg_keyword": "bank building"}},
        {{"narration": "수요가 둔화되면 물가 상승 압력도 약해집니다.", "caption": "수요 둔화와 물가 상승 압력", "bg_keyword": "price chart"}},
        {{"narration": "따라서 빅스텝은 물가를 안정시키는 수단이지만, 경기 둔화라는 비용을 동반할 수 있습니다.", "caption": "물가 안정과 경기 둔화의 양면성", "bg_keyword": "economic chart"}}
    ],
    "summary_3_lines": [
        "1. 빅스텝은 기준금리를 0.5퍼센트포인트 인상하는 조치",
        "2. 소비와 투자를 줄여 물가 상승 압력을 낮춤",
        "3. 물가 안정과 경기 둔화가 함께 나타날 수 있음"
    ],
    "useful_source_title": "한국은행 경제용어사전",
    "useful_source_url": "검색창에 '한국은행 경제용어사전'을 검색하면 700개가 넘는 용어를 쉽게 볼 수 있어요!"
}}
"""
    
    try:
        response = client.models.generate_content(
            model='gemini-2.5-pro',
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
        
        # Pydantic/JSON parsing
        result = json.loads(response.text.strip())
        result["topic"] = topic
        sections = result.get("script_sections", [])
        if not 4 <= len(sections) <= 5:
            raise ValueError("script_sections는 4~5개여야 합니다.")
        narration_length = sum(
            len(section.get("narration", "")) for section in sections
        )
        if not 300 <= narration_length <= 500:
            raise ValueError(
                f"narration 분량이 적절하지 않습니다: {narration_length}자"
            )
        for section in sections:
            if not all(section.get(key) for key in ("narration", "caption", "bg_keyword")):
                raise ValueError("각 대본 구간에 narration, caption, bg_keyword가 필요합니다.")
            section["text"] = section["narration"]
        
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
    print("대본 생성 테스트:")
    res = generate_script(test_topic)
    print(json.dumps(res, ensure_ascii=False, indent=2))
