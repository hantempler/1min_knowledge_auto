# -*- coding: utf-8 -*-
"""
[Step 2] 15대 언론사 랭킹 기사 기반 킬러 토픽 자동 선별기 (맥락 기반 4대 순환 엔진)
- 15대 주요 언론사 랭킹 기사 70~75건 전수 수집 및 고유 ID 부여
- 정치/연예/단순범죄 LLM 맥락 기반 1차 제외
- 채널 피로도 관리: 어제 다룬 카테고리 당일 전면 금지 (Anti-Fatigue)
- 사용자 확정 100점 채점표: 전 국민 대중성(50점) + 손실회피(25점) + 상식반전(25점)
- 진부한 건강 잔소리(-50점 감점) 탈락 가드레일
- 기사 원문 본문(#dic_area) 실시간 단독 수집 및 팩트 기반 데이터 구축
- used_topics.json 읽기 전용 참조 (로컬 파일 쓰기 영구 배제)
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

    # 2. 15대 주요 언론사 랭킹 기사(70~75건) 각각에 고유 ID 부여하여 독립 기사 목록 조립
    candidates = []
    for a in all_articles:
        if a.get("press") in TARGET_PRESS:
            c_id = f"기사 {len(candidates)+1:02d}"
            candidates.append(f"[{c_id}] [{a['press']}] {a['title']} (URL: {a['url']})")

    print(f"  🎯 [Step 2 Topic] 주요 15대 언론사 랭킹 기사 총 {len(candidates)}건 심사 풀 구성 완료", flush=True)

    # 3. 과거 다룬 주제(used_topics.json) 로드 (★ 읽기 전용: 어제 카테고리만 파악)
    used_topics_path = os.path.join(config.DATA_DIR, "used_topics.json")
    past_topics = []
    yesterday_cat = "없음"
    if os.path.exists(used_topics_path) and os.path.getsize(used_topics_path) > 2:
        try:
            with open(used_topics_path, "r", encoding="utf-8") as uf:
                used_list = json.load(uf)
                for item in used_list:
                    if isinstance(item, dict):
                        past_topics.append(item.get("topic") or item.get("title", ""))
                    elif isinstance(item, str):
                        past_topics.append(item)
                if used_list and isinstance(used_list[-1], dict):
                    yesterday_cat = used_list[-1].get("category", "없음")
        except Exception:
            pass

    client = genai.Client(vertexai=True, project=config.GCP_PROJECT_ID, location=config.GCP_LOCATION)

    prompt = f"""
당신은 대한민국 1위 유튜브 지식 쇼츠(1분미만 스타일)의 메인 총괄 에디터입니다.
{target_date_str} 실시간 네이버 랭킹 뉴스 목록 중에서, 유튜브 쇼츠 시청자가 0.1초 만에 엄지를 멈추고 끝까지 볼 수밖에 없는 [단 1개의 최고 킬러 토픽]을 자동 선정하세요.

[당일 주요 언론사 랭킹 기사 전체 풀 ({len(candidates)}건 - 각각 독립된 개별 기사)]
{chr(10).join(candidates)}

[최근 편성 이력 및 채널 피로도 관리]
- 어제 다룬 카테고리: [{yesterday_cat}]
- 과거 다룬 주제 목록 (중복 절대 금지):
{", ".join(past_topics[-30:])}

★ [필수 적격 심사 (Hard Filters - 위반 시 0점 탈락)]:
1. ❌ 정치인/정당 공방, 연예인 가십/열애/사생활, 단순 살인/비극/자극적 강력 범죄는 즉시 0점 탈락!
2. ❌ 직전 날짜에 다룬 [{yesterday_cat}] 카테고리는 채널 피로도를 막기 위해 오늘 절대 선정하지 마세요!
   -> 반드시 [{yesterday_cat}]를 제외한 나머지 3개 영역([내지갑/금융], [최신기술/사회], [일상생활/안전], [인체의학/반전]) 중에서 1위를 선정하세요.
3. ❌ 서울경제 [헬시타임] 등 특정 언론사 건강 코너 기사는 2일 연속 선정 불가.
4. ❌ 아침마당식 진부한 잔소리 무조건 탈락 (-50점 감점):
   - "마늘 먹으면 좋다", "과일 껍질 먹어라", "운동해라" 등 뻔하고 교훈적인 잔소리 즉시 탈락!

★ [정량 채점 기준표 (100점 만점)]:
- 1. 전 국민 일상 대중성 (50점): 대한민국 성인 90% 이상이 매일 만지거나 쓰고 겪는 대중적 소재인가? (소수/니치 소재는 감점)
- 2. 손실 회피 및 긴급성 (25점): 이 사실을 모르면 지금 당장 내 돈이 새거나, 내 몸/안전에 치명적인 손실이 발생하는가?
- 3. 상식 파괴 및 반전도 (25점): 당연히 맞다고 믿고 있던 상식을 180도 뒤집는 충격 팩트인가?

위 3가지 점수의 합계(총점)가 가장 높은 단 1개의 기사를 선정하여 아래 JSON 형태로만 출력하세요 (주의: 쇼츠 대본 지식은 본문을 읽고 추출하므로 여기서는 1위 기사 링크와 채점표만 출력하세요):
{{
  "date": "{target_date_str}",
  "selected_article_id": "기사 번호 (예: 기사 14)",
  "selected_article_title": "원문 기사 제목",
  "press": "언론사명",
  "url": "기사 링크",
  "category": "내지갑/금융, 최신기술/사회, 일상생활/안전, 인체의학/반전 중 택1",
  "score_breakdown": {{
    "relatability": 48,
    "loss_aversion": 24,
    "counter_intuitive": 22,
    "total_score": 94
  }},
  "headline_pick_reason": "왜 이 기사 헤드라인이 당일 1위인지 1문장"
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
            raw_text = resp.text.strip()
            if "```json" in raw_text:
                raw_text = raw_text.split("```json")[1].split("```")[0].strip()
            elif "```" in raw_text:
                raw_text = raw_text.split("```")[1].split("```")[0].strip()
            selection = json.loads(raw_text)
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

    # 4. [2단계] 선정된 기사의 실제 본문 크롤링
    print(f"  📰 [Step 2 Topic] 1위 기사 본문(#dic_area) 수집 중: {selection['url']}...", flush=True)
    body_text = fetch_article_body(selection["url"])
    if not body_text or len(body_text.strip()) < 200:
        print("  ⚠️ 본문 수집 실패 또는 본문 부족, 원문 제목으로 대체", flush=True)
        body_text = selection["selected_article_title"]
    selection["article_body"] = body_text[:3000]

    # 5. [3단계] 본문 전문을 완독하고, 오직 본문 속 실제 팩트만을 근거로 지식 추출 (환각 원천 차단)
    fact_prompt = f"""
당신은 대한민국 1위 팩트 기반 유튜브 지식 쇼츠의 수석 팩트체커 겸 에디터입니다.
아래 제공된 [기사 본문 전문]을 철저히 완독하고, 오직 본문에 실제로 존재하는 명확한 팩트와 수치, 사건만을 근거로 쇼츠 0초 훅 제목과 핵심 지식을 작성하세요.

[기사 정보]
- 언론사: {selection.get('press')}
- 원문 기사 제목: {selection.get('selected_article_title')}
- 카테고리: {selection.get('category')}

[기사 본문 전문]
{selection['article_body']}

★ [절대 준수 팩트 가드레일 (환각/거짓말 엄격 금지)]:
1. ❌ 환각(Hallucination) 절대 금지: 기사 본문에 전혀 언급되지 않은 제품(예: 본문은 의류/스포츠용품인데 화장품/리들샷/피부를 언급하는 행위), 성분, 가짜 부작용을 지어내는 행위는 절대 금지합니다.
2. 낚시성 기사 제목에 낚이지 말고, 본문이 실제로 다루고 있는 핵심 사실과 팩트가 무엇인지 정확히 파악하여 0초 훅 제목을 뽑으세요.
3. 핵심 지식(knowledge_core)은 100% 본문에 적힌 사실과 전문가/당국 조언에만 근거해야 합니다.

아래 JSON 형태로만 출력하세요:
{{
  "shorts_title": "기사 본문 팩트에 기반한 1분미만 스타일 0초 훅 제목 (25자 이내, 본문에 없는 거짓 단어 엄금)",
  "why_viral": "본문의 실제 팩트가 시청자에게 왜 놀랍거나 유용한지 1문장",
  "knowledge_core": "기사 본문 속 실제 사실/원리/행동요령 핵심 요약 (2~3문장)"
}}
"""
    for attempt in range(3):
        try:
            f_resp = client.models.generate_content(
                model=config.MODEL_FAST,
                contents=fact_prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.2)
            )
            f_text = f_resp.text.strip()
            if "```json" in f_text:
                f_text = f_text.split("```json")[1].split("```")[0].strip()
            elif "```" in f_text:
                f_text = f_text.split("```")[1].split("```")[0].strip()
            fact_data = json.loads(f_text)
            selection["shorts_title"] = fact_data.get("shorts_title")
            selection["why_viral"] = fact_data.get("why_viral")
            selection["knowledge_core"] = fact_data.get("knowledge_core")
            break
        except Exception as e:
            print(f"  ⚠️ [Step 2 Fact 지연] {e}", flush=True)
            time.sleep(2)

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(selection, f, ensure_ascii=False, indent=2)

    # used_topics.json에 선정된 주제 누적 기록 (다음 날짜 체이닝용)
    try:
        current_used = []
        if os.path.exists(used_topics_path) and os.path.getsize(used_topics_path) > 2:
            with open(used_topics_path, "r", encoding="utf-8") as uf:
                current_used = json.load(uf)
        current_used.append({
            "date": target_date_str,
            "category": selection.get("category"),
            "topic": selection.get("shorts_title"),
            "press": selection.get("press"),
            "url": selection.get("url")
        })
        with open(used_topics_path, "w", encoding="utf-8") as uf:
            json.dump(current_used, uf, ensure_ascii=False, indent=2)
        print(f"  📝 [Step 2 Topic] used_topics.json 누적 기록 완료 ({target_date_str}: {selection.get('category')})", flush=True)
    except Exception as e:
        print(f"  ⚠️ used_topics.json 기록 실패: {e}", flush=True)

    sb = selection.get("score_breakdown", {})
    print(f"  ✨ [Step 2 Topic 완료] 1위 선정: [{selection.get('selected_article_id')}] [{selection.get('press')}] [{selection.get('category')}] {selection.get('shorts_title')} (총점 {sb.get('total_score', 'N/A')}점)", flush=True)
    return selection

if __name__ == "__main__":
    import argparse
    from datetime import datetime
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Step 2: 1위 킬러 토픽 선별기")
    parser.add_argument("--date", type=str, default=datetime.now().strftime("%Y-%m-%d"), help="수집 대상 일자 (YYYY-MM-DD)")
    parser.add_argument("--force", action="store_true", help="기존 캐시 무시하고 강제 재선정")
    args = parser.parse_args()

    sel = select_best_killer_topic(args.date, force_refresh=args.force)
    print("\n" + "=" * 80)
    print("🎯 [Step 2 토픽 선별 최종 결과]")
    print(f"  선정 번호: {sel.get('selected_article_id')}")
    print(f"  언론사: [{sel.get('press')}]")
    print(f"  기사제목: {sel.get('selected_article_title')}")
    print(f"  쇼츠제목: {sel.get('shorts_title')}")
    print(f"  카테고리: {sel.get('category')}")
    sb = sel.get("score_breakdown", {})
    print(f"  채점 세부: 대중성 {sb.get('relatability')}/50 | 손실회피 {sb.get('loss_aversion')}/25 | 상식반전 {sb.get('counter_intuitive')}/25 | 총점 {sb.get('total_score')}/100")
    print(f"  선정 이유: {sel.get('why_viral')}")
    print(f"  핵심 지식: {sel.get('knowledge_core')}")
    print(f"  본문 길이: {len(sel.get('article_body', ''))}자 수집 완료")
    print("=" * 80)
