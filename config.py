import os
from dotenv import load_dotenv

# Directory Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.join(BASE_DIR, "config")
DATA_DIR = os.path.join(BASE_DIR, "data")
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
SRC_DIR = os.path.join(BASE_DIR, "src")

ENV_PATH = os.path.join(CONFIG_DIR, '.env')
load_dotenv(ENV_PATH)

# GCP / Vertex AI 설정 (기존 history_shorts_v1과 동일하게 세팅)
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.path.join(CONFIG_DIR, "application_default_credentials.json")
GCP_PROJECT_ID = "project-beba2bf6-d235-4031-ba5"
GCP_LOCATION = "us-central1"

# 모델 티어링: 가벼운 작업(주제/조사/검증)은 flash, 대본만 pro
MODEL_FAST = "gemini-2.5-flash"
MODEL_PRO = "gemini-2.5-pro"

# YouTube & Pexels API Key
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")
JAMENDO_CLIENT_ID = os.getenv("JAMENDO_CLIENT_ID")

# 10대 카테고리별 Neural2 전담 앵커 매핑 매트릭스
CATEGORY_VOICE_MAP = {
    # 남성 메인 앵커 (ko-KR-Neural2-C): 신뢰감, 무게감 있는 시사·원리
    "경제": "ko-KR-Neural2-C",
    "역사": "ko-KR-Neural2-C",
    "사회": "ko-KR-Neural2-C",
    "과학": "ko-KR-Neural2-C",
    "우주": "ko-KR-Neural2-C",
    # 여성 지적 앵커 (ko-KR-Neural2-A): 스마트하고 세련된 전문 지식
    "기술": "ko-KR-Neural2-A",
    "의료": "ko-KR-Neural2-A",
    "환경": "ko-KR-Neural2-A",
    # 여성 친근 앵커 (ko-KR-Neural2-B): 밝고 따뜻한 일상 교양
    "생활": "ko-KR-Neural2-B",
    "문화": "ko-KR-Neural2-B",
}
DEFAULT_VOICE_NAME = "ko-KR-Neural2-C"

# ==============================================================================
# AM / PM 이원화 프롬프트 시스템 (벤치마킹: 1분미만 & How Money Works vs Zack D. & MagnatesMedia)
# ==============================================================================
AM_SYSTEM_PROMPT = """
당신은 출근길·등교길 시청자에게 오늘 가장 유용한 지식을 전달하는 '모닝 1분 팩트' 쇼츠의 크리에이터입니다.
벤치마킹 모델은 한국의 '1분미만'과 글로벌 'How Money Works'입니다.

[핵심 작성 원칙]
1. [0초 룰 (Cold Open)]: '안녕하세요', '오늘 알아볼 것은' 같은 형식적인 인사를 0.1초도 넣지 마세요. 첫 문장부터 시청자의 손실 회피 심리나 호기심을 찌르는 훅으로 바로 시작하세요. (예: '오늘 뉴스에 뜬 이 소식, 모르면 당신 통장만 털립니다', '우리가 매일 쓰는 이 물건, 사실은...')
2. [피부 체감형 번역]: 어려운 경제·과학 용어나 정책을 시청자의 돈, 일상, 지갑, 건강에 직결되는 비유로 번역하세요.
3. [속도감 있는 호흡]: 군더더기 없는 단문 위주로 작성하며, 4~5개 컷, 전체 공백 포함 320~400자 분량으로 압축하세요.
4. [이모지·특수기호 금지]: 화면 렌더링 시 깨짐을 방지하기 위해 이모티콘(🚀, ✅ 등)은 절대 사용하지 마세요.
5. [마무리]: '오늘 동료들에게 아는 척하기 딱 좋은 한 줄 팩트'로 깔끔하게 정리하세요.
"""

PM_SYSTEM_PROMPT = """
당신은 퇴근 후 지친 시청자의 뇌를 깨우는 '나이트 도파민 썰' 쇼츠의 스토리텔러입니다.
벤치마킹 모델은 글로벌 'Zack D. Films'와 'MagnatesMedia'입니다.

[핵심 작성 원칙]
1. [0초 룰 (Cold Open)]: 인사를 절대 하지 마세요. 첫 프레임부터 기괴한 호기심이나 역사적 삽질, 충격적인 상식 파괴로 시청자를 낚아채세요. (예: '사실 우리가 알고 있던 ~는 새빨간 거짓말이었습니다', '인류 역사상 가장 멍청했던 1초의 실수 TOP 1')
2. [서사적 갈등과 반전]: [평화로운 착각] -> [치명적 반전/삽질] -> [충격적인 결말/진실] 구조로 극적인 서스펜스를 연출하세요.
3. [몰입감과 템포]: 지루한 교과서 해설이 아니라 친구에게 흥미진진한 썰을 풀듯 리듬감 있게 작성하세요. 4~5개 컷, 전체 공백 포함 330~420자 분량.
4. [이모지·특수기호 금지]: 화면 렌더링 시 깨짐을 방지하기 위해 이모티콘(🚀, ✅ 등)은 절대 사용하지 마세요.
5. [마무리]: 영상이 끝나도 여운이 남는 강렬한 반전이나 다음 생각을 유발하는 질문으로 끝내세요.
"""

SYSTEM_PROMPT = AM_SYSTEM_PROMPT  # 기본 하위호환

SLOT_CONFIG = {
    "morning": {
        "slot_id": "morning",
        "title_prefix": "[1분 팩트]",
        "header_badge": "모닝 1분 팩트",
        "theme": "morning",
        "voice": "ko-KR-Neural2-A",  # 스마트하고 세련된 여성 앵커
        "speaking_rate": 1.05,
        "pitch": 0.0,
        "accent_color": (56, 189, 248),  # Sky blue
        "highlight_color": (250, 204, 21),  # Yellow
        "bgm_tags": "acoustic,chillout,ambient,pop,upbeat",
        "system_prompt": AM_SYSTEM_PROMPT,
    },
    "evening": {
        "slot_id": "evening",
        "title_prefix": "[도파민 썰]",
        "header_badge": "나이트 도파민 썰",
        "theme": "evening",
        "voice": "ko-KR-Neural2-C",  # 묵직하고 흡입력 있는 남성 스토리텔러
        "speaking_rate": 1.08,
        "pitch": -0.5,
        "accent_color": (244, 63, 94),  # Rose red/neon
        "highlight_color": (250, 204, 21),  # Yellow
        "bgm_tags": "cinematic,action,synthwave,soundtrack,electronic",
        "system_prompt": PM_SYSTEM_PROMPT,
    }
}



def normalize_slot(slot: str | None) -> str:
    """slot 인자를 morning 또는 evening으로 표준화"""
    if not slot:
        return "morning"
    s = str(slot).lower().strip()
    if s in ["morning", "am", "m"]:
        return "morning"
    if s in ["evening", "pm", "e", "night"]:
        return "evening"
    return "morning"

# Ensure directories exist
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(ASSETS_DIR, exist_ok=True)
os.makedirs(SRC_DIR, exist_ok=True)

import datetime
from zoneinfo import ZoneInfo

def get_daily_dir(target_date_str=None, slot=None):
    if target_date_str is None:
        target_date_str = datetime.datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y%m%d")
    clean_date = str(target_date_str).replace("-", "").strip()
    formatted_date = f"{clean_date[:4]}-{clean_date[4:6]}-{clean_date[6:8]}"
    if slot:
        norm_slot = normalize_slot(slot)
        daily_dir = os.path.join(DATA_DIR, f"{formatted_date}_{norm_slot}")
    else:
        daily_dir = os.path.join(DATA_DIR, formatted_date)
    os.makedirs(daily_dir, exist_ok=True)
    return daily_dir


