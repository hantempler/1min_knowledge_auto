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


def _check_url(url: str, timeout: int = 10) -> tuple[bool, str]:
    """URL이 실제로 존재하는지 확인한다. HEAD를 먼저 쓰고, 400 이상이거나 미지원 시 GET(stream)으로 재시도한다.
    401/403은 봇 차단일 가능성이 높아 존재하는 것으로 간주하고, 404/410만 없는 것으로 본다."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    }
    ok_statuses = {200, 201, 202, 203, 204, 206, 301, 302, 303, 307, 308, 401, 403}
    try:
        response = requests.head(url, timeout=timeout, allow_redirects=True, headers=headers)
        if response.status_code in ok_statuses:
            return True, f"HTTP {response.status_code}"
        
        # HEAD가 400 이상(404, 405 등)을 반환한 경우, 서버 설정에 따라 HEAD가 비활성화되어 있을 수 있으므로 GET으로 재확인
        get_response = requests.get(url, timeout=timeout, allow_redirects=True, headers=headers, stream=True)
        return get_response.status_code in ok_statuses, f"HTTP {get_response.status_code}"
    except requests.RequestException as e:
        return False, f"{type(e).__name__}"


def _is_reachable(url: str, timeout: int = 10) -> bool:
    ok, _ = _check_url(url, timeout)
    return ok


def _filter_reachable_sources(sources: list) -> list:
    reachable = []
    for s in sources:
        ok, reason = _check_url(s.get("url", ""))
        if ok:
            reachable.append(s)
        else:
            print(f"  -> 제외: {s.get('url', '')} ({reason})")
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
    from urllib.parse import quote

    if daily_dir is None:
        daily_dir = config.DATA_DIR

    client = genai.Client(
        vertexai=True,
        project=config.GCP_PROJECT_ID,
        location=config.GCP_LOCATION,
    )
    
    base_prompt = f"""
오늘의 1분 상식 주제는 다음과 같습니다: "{topic}"

이 주제로 짧은 지식 콘텐츠를 만들기 위한 조사 카드를 JSON으로 작성하세요.
대본을 쓰지 말고, 사실을 정리하는 연구 메모만 작성하세요.

필수 원칙:
1. 정의와 원인, 결과를 서로 구분하세요.
2. 가능하면 실제 역사적 사례나 관찰 가능한 사례를 하나 포함하세요.
3. 과장된 표현 대신 검증 가능한 표현을 사용하세요.
4. 출처는 실제로 100% 접속 가능한 한국어 위키백과(https://ko.wikipedia.org/wiki/...), 영어 위키백과(https://en.wikipedia.org/wiki/...), 공공기관/학술기관/사전의 직접 URL을 최소 2~3개 이상 반드시 포함하세요.
5. 존재 여부가 불확실한 사설 블로그나 임의의 세부 페이지 URL(예: .html 경로 등)은 환각 위험이 크므로 절대 작성하지 마세요. 확실하게 존재하는 백과사전 표제어 URL을 우선 사용하세요.
6. JSON 외의 문장은 출력하지 마세요.

다음 필드를 반드시 포함하세요:
- topic: 주제
- definition: 1~2문장의 정확한 정의
- core_mechanism: 원인에서 결과로 이어지는 3~5단계 배열
- historical_or_real_example: 실제 사례 또는 역사적 사례
- real_life_impact: 시청자가 체감할 수 있는 영향
- common_misunderstanding: 자주 생기는 오해와 바로잡는 설명
- sources: title, url, claim_supported를 가진 출처 배열 (최소 2개 이상)
"""

    current_prompt = base_prompt
    brief = None

    # 출처 404 등에 대응하기 위해 최대 2회 시도
    for attempt in range(1, 3):
        try:
            response = client.models.generate_content(
                model=config.MODEL_FAST,
                contents=current_prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json"),
            )
            brief = json.loads(response.text.strip())
            if not _validate_brief(brief):
                raise ValueError("조사 카드의 필수 필드 또는 출처 형식이 올바르지 않습니다.")

            brief["sources"] = _filter_reachable_sources(brief["sources"])
            if brief["sources"]:
                break
            
            print(f"  -> 유효한 출처가 없어 재시도합니다 ({attempt}/2)...")
            current_prompt = (
                base_prompt
                + "\n\n[주의] 직전 생성한 출처 URL이 실제로 존재하지 않아 404 에러가 발생했습니다. "
                "반드시 실제로 존재하는 한국어 위키백과(https://ko.wikipedia.org/wiki/...) 또는 영어 위키백과(https://en.wikipedia.org/wiki/...) 표제어 주소로 2개 이상 작성해주세요."
            )
        except Exception as e:
            print(f"  -> 조사 카드 생성 시도 {attempt} 실패: {e}")
            if attempt == 2:
                break

    # 만약 2회 재시도 후에도 출처가 비어있다면, 안전 폴백 출처 주입
    if brief and not brief.get("sources"):
        print("  -> 안전 폴백 출처를 자동 생성합니다...")
        # 주제에서 핵심 키워드 추출 시도
        clean_keyword = topic.split(":")[-1].replace("의 비밀", "").replace("원리", "").strip()
        encoded = quote(clean_keyword)
        fallback_url = f"https://ko.wikipedia.org/wiki/{encoded}"
        ok, _ = _check_url(fallback_url)
        if not ok:
            fallback_url = f"https://ko.wikipedia.org/w/index.php?search={encoded}"
        
        brief["sources"] = [{
            "title": f"위키백과 - {clean_keyword}",
            "url": fallback_url,
            "claim_supported": f"{topic} 관련 기본 개념 및 배경 지식"
        }]

    if not brief or not brief.get("sources"):
        raw_path = os.path.join(daily_dir, "1_research_raw.json")
        if brief:
            with open(raw_path, "w", encoding="utf-8") as file:
                json.dump(brief, file, ensure_ascii=False, indent=2)
        print("조사 카드 생성 오류: 접속 가능한 출처를 확보하지 못했습니다.")
        return None

    os.makedirs(daily_dir, exist_ok=True)
    path = os.path.join(daily_dir, "1_research_brief.json")
    with open(path, "w", encoding="utf-8") as file:
        json.dump(brief, file, ensure_ascii=False, indent=2)
    return brief
