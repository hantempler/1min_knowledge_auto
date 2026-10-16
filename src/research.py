import json
import os
import sys
from urllib.parse import urlparse

import requests
from google import genai
from google.genai import types

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config


def _is_valid_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _is_reachable(url: str, timeout: int = 10) -> bool:
    """URL이 실제로 존재하는지 확인한다. HEAD를 먼저 쓰고, 미지원 시 GET으로 재시도한다.
    401/403은 봇 차단일 가능성이 높아 존재하는 것으로 간주하고, 404/410만 없는 것으로 본다."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    }
    try:
        response = requests.head(url, timeout=timeout, allow_redirects=True, headers=headers)
        if response.status_code == 405:
            response = requests.get(url, timeout=timeout, allow_redirects=True, headers=headers, stream=True)
        return response.status_code in {200, 201, 202, 203, 204, 206, 301, 302, 303, 307, 308, 401, 403}
    except requests.RequestException:
        return False


def _filter_reachable_sources(sources: list) -> list:
    reachable = [s for s in sources if _is_reachable(s.get("url", ""))]
    dropped = len(sources) - len(reachable)
    if dropped:
        print(f"  -> 접속 불가 출처 {dropped}건 제외")
    return reachable


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
            model=config.MODEL_FAST,
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json"),
        )
        brief = json.loads(response.text.strip())
        if not _validate_brief(brief):
            raise ValueError("조사 카드의 필수 필드 또는 출처 형식이 올바르지 않습니다.")

        brief["sources"] = _filter_reachable_sources(brief["sources"])
        if not brief["sources"]:
            raise ValueError("접속 가능한 출처가 하나도 없습니다.")

        os.makedirs(daily_dir, exist_ok=True)
        path = os.path.join(daily_dir, "1_research_brief.json")
        with open(path, "w", encoding="utf-8") as file:
            json.dump(brief, file, ensure_ascii=False, indent=2)
        return brief
    except Exception as error:
        print(f"조사 카드 생성 오류: {error}")
        return None
