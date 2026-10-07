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

# YouTube & Pexels API Key
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")
JAMENDO_CLIENT_ID = os.getenv("JAMENDO_CLIENT_ID")

# Prompts
SYSTEM_PROMPT = """
당신은 '1분 상식 브리핑' 유튜브 채널의 정확한 해설자입니다.
예능톤, 밈, 과장된 비유, 자극적인 표현을 사용하지 말고 차분하고 명확한 설명체로 작성하세요.
전문 용어는 처음 등장할 때 쉬운 말로 정의하고, 원인과 결과를 구분해 설명하세요.
확인되지 않은 사실이나 단정적인 추측을 추가하지 마세요.
내용은 유튜브 숏츠에 맞게 45초~55초 분량으로 작성하세요.
한국어 기준으로 전체 화자 대사는 공백 포함 약 330~430자, 4~5개 구간으로 구성하세요.
대본 생성 요청이 JSON 형식이면 JSON 객체만 출력하고, 별도 요청이 없으면 설명 없이 요청된 형식만 출력하세요.
대본과 자막에는 이모지(이모티콘)를 사용하지 마세요.
마지막 구간은 일반적인 "다음 시간에 만나요"나 "이제 아셨죠"로 끝내지 마세요.
시청자가 영상이 끝난 뒤에도 기억할 수 있는 한 문장의 결론, 반전, 질문 중 하나로 강하게 마무리하세요.
"""

# Ensure directories exist
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(ASSETS_DIR, exist_ok=True)
os.makedirs(SRC_DIR, exist_ok=True)

import datetime
from zoneinfo import ZoneInfo
def get_daily_dir(target_date_str=None):
    if target_date_str is None:
        target_date_str = datetime.datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y%m%d")
        
    formatted_date = f"{target_date_str[:4]}-{target_date_str[4:6]}-{target_date_str[6:8]}"
    daily_dir = os.path.join(DATA_DIR, formatted_date)
    os.makedirs(daily_dir, exist_ok=True)
    return daily_dir

