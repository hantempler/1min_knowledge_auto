import json
import os
import sys

from google import genai
from google.genai import types

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config


def fact_check_script(topic: str, research_brief: dict, script_data: dict, daily_dir: str = None):
    if daily_dir is None:
        daily_dir = config.DATA_DIR

    client = genai.Client(
        vertexai=True,
        project=config.GCP_PROJECT_ID,
        location=config.GCP_LOCATION,
    )
    prompt = f"""
주제: {topic}

[조사 카드]
{json.dumps(research_brief, ensure_ascii=False, indent=2)}

[생성 대본]
{json.dumps(script_data, ensure_ascii=False, indent=2)}

생성 대본을 조사 카드와 대조해 사실 검토 결과를 JSON으로 작성하세요.
숏츠 시청자의 몰입을 위한 구어체 비유나 흥미 유발 오프닝 훅은 적극 허용하되,
명백한 수치 왜곡, 조사 카드에 없는 허위 사실 날조, 인과관계의 심각한 오류만 문제(issues)로 표시하세요.
경미한 문체나 흥미 위주의 표현은 approved: true로 통과시키세요.

필드:
- approved: 치명적인 사실 왜곡이나 허위 사실이 없으면 true, 있으면 false
- issues: 실제 사실과 어긋나는 치명적 오류 주장과 이유를 담은 문자열 배열
- corrections: 오류가 있을 경우 정확한 대체 문장 배열
- checked_claims: 검토한 핵심 주장과 판정(ok 또는 revise)을 담은 객체 배열
JSON만 출력하세요.

"""

    try:
        response = client.models.generate_content(
            model=config.MODEL_FAST,
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json"),
        )
        result = json.loads(response.text.strip())
        if not isinstance(result.get("approved"), bool):
            raise ValueError("팩트체크 결과에 approved가 없습니다.")

        os.makedirs(daily_dir, exist_ok=True)
        path = os.path.join(daily_dir, "2_fact_check.json")
        with open(path, "w", encoding="utf-8") as file:
            json.dump(result, file, ensure_ascii=False, indent=2)
        return result
    except Exception as error:
        print(f"팩트체크 오류: {error}")
        return None
