import json
import os
import sys
from urllib.parse import urlparse

from google import genai
from google.genai import types

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config


def _is_valid_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _validate_brief(brief: dict) -> bool:
    required_fields = {
        "topic",
        "definition",
        "core_mechanism",
        "historical_or_real_example",
        "real_life_impact",
        "common_misunderstanding",
        "sources",
    }
    if not required_fields.issubset(brief):
        return False
    if not isinstance(brief["core_mechanism"], list) or not brief["core_mechanism"]:
        return False
    if not isinstance(brief["sources"], list) or not brief["sources"]:
        return False
    return all(
        isinstance(source, dict)
        and source.get("title")
        and _is_valid_url(source.get("url", ""))
        and source.get("claim_supported")
        for source in brief["sources"]
    )


def generate_research_brief(topic: str, daily_dir: str = None):
    if daily_dir is None:
        daily_dir = config.DATA_DIR

    client = genai.Client(
        vertexai=True,
        project=config.GCP_PROJECT_ID,
        location=config.GCP_LOCATION,
    )
    prompt = f"""
오늘의 1분 상식 주제는 다음과 같습니다: "{topic}"

이 주제로 짧은 지식 콘텐츠를 만들기 위한 조사 카드를 JSON으로 작성하세요.
대본을 쓰지 말고, 사실을 정리하는 연구 메모만 작성하세요.

필수 원칙:
1. 정의와 원인, 결과를 서로 구분하세요.
2. 가능하면 실제 역사적 사례나 관찰 가능한 사례를 하나 포함하세요.
3. 과장된 표현 대신 검증 가능한 표현을 사용하세요.
4. 출처는 실제로 존재하는 공공기관, 연구기관, 국제기구 또는 신뢰할 수 있는 사전의 직접 URL을 사용하세요.
5. 출처 URL을 모르면 추측하지 말고 해당 항목을 제외하세요.
6. JSON 외의 문장은 출력하지 마세요.

다음 필드를 반드시 포함하세요:
- topic: 주제
- definition: 1~2문장의 정확한 정의
- core_mechanism: 원인에서 결과로 이어지는 3~5단계 배열
- historical_or_real_example: 실제 사례 또는 역사적 사례
- real_life_impact: 시청자가 체감할 수 있는 영향
- common_misunderstanding: 자주 생기는 오해와 바로잡는 설명
- sources: title, url, claim_supported를 가진 출처 배열
"""

    try:
        response = client.models.generate_content(
            model="gemini-2.5-pro",
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json"),
        )
        brief = json.loads(response.text.strip())
        if not _validate_brief(brief):
            raise ValueError("조사 카드의 필수 필드 또는 출처 형식이 올바르지 않습니다.")

        os.makedirs(daily_dir, exist_ok=True)
        path = os.path.join(daily_dir, "1_research.json")
        with open(path, "w", encoding="utf-8") as file:
            json.dump(brief, file, ensure_ascii=False, indent=2)
        return brief
    except Exception as error:
        print(f"조사 카드 생성 오류: {error}")
        return None
