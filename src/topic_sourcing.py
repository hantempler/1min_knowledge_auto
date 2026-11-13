# -*- coding: utf-8 -*-
"""
[Step 2] 80+개 언론사 랭킹 기사 기반 킬러 토픽 자동 선별기
- 정치/연예/단순범죄/단순시황 1차 즉시 탈락
- [인체·건강 공포], [내 지갑·손실회피], [일상 습관 상식 파괴] 3대 킬러 영역 자동 채점
- 기사 원문 본문(#dic_area) 실시간 수집 및 팩트 기반 데이터 구축
- data/used_topics.json 중복 방지 연동
"""
import os
import sys
import json
import time
from google import genai
from google.genai import types

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

import config
from scraper import get_naver_ranking_by_date, fetch_article_body

TARGET_PRESS = [
    "조선일보", "중앙일보", "동아일보", "매일경제", "한국경제",
    "연합뉴스", "YTN", "SBS", "JTBC", "MBC",
    "서울경제", "이데일리", "머니투데이", "농민신문", "아이뉴스24"
]

def select_best_killer_topic(target_date_str: str, force_refresh: bool = False) -> dict:
    clean_date = target_date_str.replace("-", "").strip()
    out_file = os.path.join(config.DATA_DIR, f"topic_selection_{clean_date}.json")

    if not force_refresh and os.path.exists(out_file) and os.path.getsize(out_file) > 100:
        print(f"  [Step 2 Topic] 캐시된 주제 로드 ({clean_date}): {out_file}", flush=True)
        with open(out_file, "r", encoding="utf-8") as f:
            return json.load(f)

    # 1. 해당 날짜의 랭킹 기사 전수 확보
    all_articles = get_naver_ranking_by_date(target_date_str, force_refresh=force_refresh)

    # 2. 주요 언론사 기사로 1차 압축
    candidates = []
    for a in all_articles:
        if a["press"] in TARGET_PRESS:
            candidates.append(f"[{a['press']}] {a['title']} (URL: {a['url']})")

    print(f"  🎯 [Step 2 Topic] 주요 {len(TARGET_PRESS)}대 언론사 랭킹 후보 {len(candidates)}건 심사 중...", flush=True)

    # 3. 과거 다룬 주제(used_topics.json) 로드
    used_topics_path = os.path.join(config.DATA_DIR, "used_topics.json")
    past_topics = []
    if os.path.exists(used_topics_path) and os.path.getsize(used_topics_path) > 2:
        try:
            with open(used_topics_path, "r", encoding="utf-8") as uf:
                used_list = json.load(uf)
                for item in used_list:
                    if isinstance(item, dict):
                        past_topics.append(item.get("topic") or item.get("title", ""))
                    elif isinstance(item, str):
                        past_topics.append(item)
        except Exception:
            pass

    past_context = ""
    if past_topics:
        past_context = f"\n[과거 다룬 주제 목록 - 중복 절대 금지]\n다음 주제와 중복되거나 유사한 것은 절대 제외하세요:\n" + ", ".join(past_topics[-40:]) + "\n"

    client = genai.Client(vertexai=True, project=config.GCP_PROJECT_ID, location=config.GCP_LOCATION)

    prompt = f"""
당신은 대한민국 1위 유튜브 지식 쇼츠(1분미만 스타일)의 메인 총괄 에디터입니다.
{target_date_str} 실시간 네이버 랭킹 뉴스 목록 중에서, 유튜브 쇼츠 시청자가 0.1초 만에 엄지를 멈추고 끝까지 볼 수밖에 없는 [단 1개의 최고 킬러 토픽]을 자동 선정하세요.

[후보 기사 목록 (총 {len(candidates)}건 중 상위)]
{chr(10).join(candidates[:70])}
{past_context}
[선정 절대 가드레일]
1. ❌ 무조건 탈락: 정치인 공방, 연예인 사생활/학폭, 단순 범죄 사건(성폭행, 살인 등), 단순 주가/코스피 수치 나열.
2. ⭕ 최우선 선정 (시청자가 클릭 안 하고 못 배기는 3대 영역):
   - [인체/건강/생존 충격]: 내 몸에 생기는 이상 신호, 매일 먹고 쓰는 물질의 충격적 의학 팩트, 질병 경고.
   - [내 지갑/손실회피]: 전 국민이 쓰는 대형 서비스의 피해, 신종 금융 덫, 세금/환급/과태료, 돈 지키는 상식.
   - [일상 습관 반전]: 누구나 매일 하는 사소한 행동의 위험성이나 상식 파괴.

반드시 아래 JSON 형태로만 출력하세요:
{{
  "date": "{target_date_str}",
  "selected_article_title": "원문 기사 제목",
  "press": "언론사명",
  "url": "기사 링크",
  "shorts_title": "1분미만 스타일 0초 훅 제목 (25자 이내)",
  "category": "의료/건강, 금융/경제, 생활/안전, 과학/기술 중 하나",
  "why_viral": "왜 이 주제가 시청자의 본능을 찌르고 조회수를 폭발시킬 수 있는지 1문장",
  "knowledge_core": "영상에서 다룰 1분 지식의 핵심 반전 원리 및 해결책 (2문장)"
}}
"""

    selection = None
    for attempt in range(5):
        try:
            resp = client.models.generate_content(
                model=config.MODEL_FAST,
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.3)
            )
            selection = json.loads(resp.text.strip())
            break
        except Exception as e:
            err_str = str(e)
            print(f"  ⚠️ [Step 2 Topic 지연/에러] {err_str[:100]}...", flush=True)
            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                time.sleep(25 + attempt * 10)
            else:
                time.sleep(3)

    if not selection:
        raise RuntimeError("토픽 자동 선정 실패 (재시도 초과)")

    # 4. 선정된 기사의 실제 본문 크롤링
    print(f"  📰 [Step 2 Topic] 기사 원문 본문 수집 중: {selection['url']}...", flush=True)
    body_text = fetch_article_body(selection["url"])
    selection["article_body"] = body_text[:3000] if body_text else selection["selected_article_title"]

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(selection, f, ensure_ascii=False, indent=2)

    # used_topics.json에 선정된 주제 실시간 자동 추가 (중복 방지 영구화)
    try:
        used_list = []
        if os.path.exists(used_topics_path) and os.path.getsize(used_topics_path) > 2:
            with open(used_topics_path, "r", encoding="utf-8") as uf:
                used_list = json.load(uf)
        
        # 중복 등록 방지
        existing_titles = [item.get("topic", "") if isinstance(item, dict) else str(item) for item in used_list]
        if selection.get("shorts_title") not in existing_titles:
            used_list.append({
                "date": target_date_str,
                "category": selection.get("category", "생활/안전"),
                "topic": selection.get("shorts_title", ""),
                "press": selection.get("press", ""),
                "url": selection.get("url", "")
            })
            with open(used_topics_path, "w", encoding="utf-8") as uf:
                json.dump(used_list, uf, ensure_ascii=False, indent=2)
            print(f"  📌 [중복 방지] used_topics.json에 주제 기록 완료: {selection['shorts_title']}", flush=True)
    except Exception as e:
        print(f"  ⚠️ used_topics.json 갱신 실패: {e}", flush=True)

    print(f"  ✨ [Step 2 Topic 완료] 1위 선정: [{selection['press']}] {selection['shorts_title']}", flush=True)
    return selection

if __name__ == "__main__":
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    test_date = "2026-11-12"
    sel = select_best_killer_topic(test_date)
    print("\n[토픽 선별 결과]")
    print(json.dumps(sel, ensure_ascii=False, indent=2))
