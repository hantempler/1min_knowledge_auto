import json
import os
import re
import sys
import random
from urllib.parse import quote

import requests

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config


ALLOWED_LICENSE_MARKERS = (
    "/by/",
    "/by-sa/",
    "/zero/",
)


def _is_youtube_safe_license(track: dict) -> bool:
    license_url = (track.get("license_ccurl") or "").lower()
    if not license_url or any(marker in license_url for marker in ("/by-nc", "/by-nd")):
        return False
    return any(marker in license_url for marker in ALLOWED_LICENSE_MARKERS)


def _music_tag(topic: str) -> str:
    topic_text = (topic or "").lower()
    if any(word in topic_text for word in ("과학", "의료", "기술", "원리", "우주")):
        return "lofi"
    if any(word in topic_text for word in ("경제", "금리", "물가", "사회")):
        return "chillout"
    if any(word in topic_text for word in ("역사", "문화", "유래", "추분", "계절")):
        return "acoustic"
    return "piano"


def download_bgm(topic: str, output_dir: str = None):
    """Jamendo에서 편안하고 잔잔한 연주곡 위주의 CC 라이선스 음악을 내려받는다."""
    client_id = os.getenv("JAMENDO_CLIENT_ID")
    if not client_id:
        print("JAMENDO_CLIENT_ID가 없어 BGM 없이 진행합니다.")
        return None

    if output_dir is None:
        output_dir = config.DATA_DIR
    os.makedirs(output_dir, exist_ok=True)
    bgm_path = os.path.join(output_dir, "bgm.mp3")
    license_path = os.path.join(output_dir, "bgm_license.json")
    for stale_path in (bgm_path, license_path):
        if os.path.exists(stale_path):
            os.remove(stale_path)

    tag = _music_tag(topic)
    try:
        tracks = []
        for search_tag in dict.fromkeys((tag, "relaxing", "background")):
            params = {
                "client_id": client_id,
                "format": "json",
                "limit": 50,
                "tags": search_tag,
                "audioformat": "mp32",
                "include": "licenses",
                "order": "popularity_total",
                "vocalinstrumental": "instrumental"
            }
            response = requests.get(
                "https://api.jamendo.com/v3.0/tracks/",
                params=params,
                timeout=15,
            )
            response.raise_for_status()
            tracks.extend(response.json().get("results", []))
            
        if not tracks:
            print(f"Jamendo에서 {tag} BGM을 찾지 못했습니다.")
            return None

        valid_tracks = [t for t in tracks if _is_youtube_safe_license(t)]
        if not valid_tracks:
            print("YouTube 상업적 이용에 적합한 CC 라이선스 BGM을 찾지 못했습니다.")
            return None
            
        # 무작위로 하나 선택하여 매번 다른 곡이 나오도록 함
        track = random.choice(valid_tracks)
        audio_url = track.get("audio")
        if not audio_url:
            return None

        print(f"  -> 선정된 BGM: {track.get('name')} by {track.get('artist_name')} (태그: {tag})")

        with requests.get(audio_url, stream=True, timeout=60) as audio_response:
            audio_response.raise_for_status()
            with open(bgm_path, "wb") as file:
                for chunk in audio_response.iter_content(chunk_size=8192):
                    file.write(chunk)

        license_info = {
            "provider": "Jamendo",
            "track_id": track.get("id"),
            "title": track.get("name"),
            "artist": track.get("artist_name"),
            "url": track.get("shareurl"),
            "license": track.get("license_ccurl") or track.get("license"),
            "youtube_use": "commercial_use_allowed_with_attribution",
            "attribution_required": True,
            "tag": tag,
        }
        with open(license_path, "w", encoding="utf-8") as file:
            json.dump(license_info, file, indent=2, ensure_ascii=False)
        return bgm_path
    except Exception as error:
        print(f"BGM 다운로드 중 오류 발생: {error}")
        return None
