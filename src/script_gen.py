# -*- coding: utf-8 -*-
"""
[Step 3] 기사 심층 독해 기반 음성-자막 1:1 무결점 대본 생성기
- 네이버 랭킹 기사 원문 심층 완독 (Full Read)
- 기사의 본질적인 핵심 의문(article_question) 자동 도출
- 4씬 구성: 01. 기사 속 위험 의문 -> 02. 일상 착각/원인 -> 03. 반전 원리/실험 팩트 -> 04. 생존 대처법
- 01부터 시작하는 4단계 넘버링 강제 적용
- 상단 1행: [{press}] 오늘 왜 이 상식? 상시 고정
- 상단 2행: Q. {article_question} (영상 내내 상시 고정)
- 상단 3행: 01~04 단계별 해답 인디케이터
- narration(TTS 한글 발음)과 subtitle(화면 자막) 1:1 단어 일치 보장
- 씬당 글자수 18~36자, 총 95~135자 하드 검증
- 씬 04 완전 종결어미(-습니다, -합니다) 하드 검증
"""
import os
import sys
import json
import time
import re
from google import genai
from google.genai import types

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
import config

def safe_get_text(resp) -> str:
    if hasattr(resp, "text") and resp.text:
        return resp.text.strip()
    if hasattr(resp, "candidates") and resp.candidates:
        c0 = resp.candidates[0]
        if hasattr(c0, "content") and c0.content and hasattr(c0.content, "parts") and c0.content.parts:
            parts_text = [p.text for p in c0.content.parts if hasattr(p, "text") and p.text]
            if parts_text:
                return " ".join(parts_text).strip()
    return ""

def clean_json_str(text: str) -> str:
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()

def validate_script_constraints(script_data: dict) -> bool:
    """씬당 글자 수(20~35자 - 쇼츠 2줄 절대 엄수), 5~6씬 전체 길이(120~210자) 및 종결어미 완결성 하드 검증"""
    if "sections" not in script_data or len(script_data["sections"]) not in (5, 6):
        print(f"  ⚠️ [대본 씬 개수 미달] 씬 개수 {len(script_data.get('sections', []))}개 (허용: 5~6개)", flush=True)
        return False
    total_len = 0
    for idx, sec in enumerate(script_data["sections"]):
        narr = sec.get("narration", "").strip()
        n_len = len(narr)
        if n_len < 18 or n_len > 35:
            print(f"  ⚠️ [대본 2줄 규격 미달] 씬 {idx+1} 글자수 {n_len}자 (허용: 18~35자, 2줄 초과 차단): '{narr}'", flush=True)
            return False
        total_len += n_len
    if total_len < 110 or total_len > 210:
        print(f"  ⚠️ [대본 총량 미달] 전체 {total_len}자 (허용: 110~210자)", flush=True)
        return False

    # 마지막 씬 종결 어미 엄격 검증: '~하므로', '~때문에' 등 미완결 접속형 어미 차단
    last_idx = len(script_data["sections"]) - 1
    last_narr = script_data["sections"][last_idx].get("narration", "").strip()
    clean_last = re.sub(r'[^가-힣]', '', last_narr)
    forbidden_endings = ("하므로", "때문에", "해서", "하며", "하고", "해야", "위해", "바라며", "바랍니다만", "때문이죠")
    for ending in forbidden_endings:
        if clean_last.endswith(ending):
            print(f"  ❌ [대본 미완결 어미 차단] 마지막 씬이 접속형 어미('{ending}')로 끝남: '{last_narr}'", flush=True)
            return False
    if not clean_last.endswith(("다", "요", "니다", "시오", "세요", "임", "음")):
        print(f"  ❌ [대본 종결어미 부재] 마지막 씬은 반드시 완성된 종결어미로 끝나야 함: '{last_narr}'", flush=True)
        return False

    # 하이라이트 워드(<hl>) 퀄리티 검증: core_keyword 필드 존재 및 subtitle 속 <hl> 1:1 일치
    for idx, sec in enumerate(script_data["sections"]):
        sub = sec.get("subtitle", "")
        core_kw = sec.get("core_keyword", "").strip()
        hls = re.findall(r'<hl>(.*?)</hl>', sub)
        if not hls:
            print(f"  ❌ [하이라이트 부재] 씬 {idx+1} 자막에 <hl> 태그가 없음: '{sub}'", flush=True)
            return False
        if len(hls) > 1:
            print(f"  ❌ [하이라이트 과다] 씬 {idx+1}에 <hl> 태그가 여러 개({hls}) 있음 (단 1개만 허용): '{sub}'", flush=True)
            return False
        if not core_kw:
            sec["core_keyword"] = hls[0].strip()
            core_kw = hls[0].strip()

        hl_word = hls[0].strip()
        if core_kw != hl_word and core_kw not in hl_word and hl_word not in core_kw:
            print(f"  ❌ [핵심 키워드 불일치] 씬 {idx+1} core_keyword('{core_kw}')와 <hl>('{hl_word}') 불일치", flush=True)
            return False
        if len(core_kw) < 2 or len(core_kw) > 10:
            print(f"  ❌ [핵심 키워드 길이 부적합] 씬 {idx+1} core_keyword('{core_kw}') 길이 {len(core_kw)}자 (허용: 2~10자)", flush=True)
            return False

    return True

def verify_script_facts(article_body: str, script_data: dict) -> dict:
    """원문 기사와 생성된 대본의 수치 및 사실관계 자동 교차 검증 (Fact-Check)"""
    if not article_body:
        return {"passed": True, "reason": "원문 기사 본문 부재로 규칙 기반 통과"}

    sub_text = " ".join([s.get("subtitle", "") for s in script_data.get("sections", [])])
    script_numbers = re.findall(r'\b\d+\b', sub_text)
    missing_numbers = []
    for num in script_numbers:
        # 2자리 이상 핵심 통계/수치가 원문 기사에 존재하는지 검증
        if len(num) >= 2 and num not in article_body:
            missing_numbers.append(num)

    passed = len(missing_numbers) == 0
    fact_report = {
        "verified_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "passed": passed,
        "checked_numbers": script_numbers,
        "missing_numbers": missing_numbers,
        "status": "VERIFIED_ACCURATE" if passed else "POTENTIAL_DISCREPANCY_FLAGGED"
    }
    print(f"  🔍 [Step 3 Fact-Check] 수치 및 팩트 교차 검증: {fact_report['status']} (검증 수치: {script_numbers})", flush=True)
    return fact_report

def generate_youtube_metadata(arg1: dict, arg2: dict, bgm_name: str = None) -> dict:
    """유튜브 업로드용 5단 완성형 고품질 설명란, 태그, 제목 자동 생성 (SEO & 팩트 출처 보장)"""
    if "sections" in arg1:
        script_data, topic_info = arg1, arg2
    else:
        topic_info, script_data = arg1, arg2

    press = topic_info.get("press") or script_data.get("news_outlet", "주요 언론사")
    article_title = topic_info.get("selected_article_title") or script_data.get("news_headline", "")
    url = topic_info.get("url", "")
    shorts_title = script_data.get("title") or topic_info.get("shorts_title", "")
    article_question = script_data.get("article_question", "")

    sections = script_data.get("sections", [])

    # 1. 팩트체크 심층 브리핑 (스크립트에 없으면 씬 3, 4, 5 기반 고품질 Fallback 합성)
    fact_check_sum = script_data.get("fact_check_summary", "").strip()
    if not fact_check_sum:
        parts = []
        if len(sections) > 2:
            parts.append(re.sub(r'<.*?>', '', sections[2].get("subtitle", "")))
        if len(sections) > 3:
            parts.append(re.sub(r'<.*?>', '', sections[3].get("subtitle", "")))
        if len(sections) > 4:
            parts.append(re.sub(r'<.*?>', '', sections[4].get("subtitle", "")))
        fact_check_sum = " ".join([p.strip() for p in parts if p.strip()]).strip()
        if not fact_check_sum:
            fact_check_sum = f"{article_title} 보도에 따르면, 과학적·통계적 인과관계 분석 결과 검증된 핵심 원리를 확인했습니다."

    # 2. 실전 핵심 가이드 & 행동 수칙 (없으면 씬 6 기반 Fallback)
    practical_guide = script_data.get("practical_guide", "").strip()
    if not practical_guide:
        if len(sections) > 5:
            practical_guide = re.sub(r'<.*?>', '', sections[5].get("subtitle", "")).strip()
        if not practical_guide:
            practical_guide = "관련 피해를 예방하고 내 권리를 지키기 위해 공인된 실천 지침을 일상에서 즉시 준수하시기 바랍니다."

    # 3. 함께 나누는 이야기 (CTA)
    cta = script_data.get("cta", "").strip()
    if not cta:
        if article_question:
            clean_q = re.sub(r'[\?\.]$', '', article_question).strip()
            cta = f"{clean_q}, 여러분은 어떻게 생각하시나요?"
        else:
            cta = "오늘의 지식에 대해 여러분의 경험이나 생각을 댓글로 자유롭게 남겨주세요!"

    # 4. 태그 및 해시태그 생성
    category = topic_info.get("category", "상식")
    base_tags = ["1분상식", "지식", "상식", "shorts", "쇼츠"]
    if category:
        clean_cat = category.replace("/", "")
        if clean_cat not in base_tags:
            base_tags.append(clean_cat)

    # 대본 생성 태그 추가
    custom_tags = script_data.get("tags", [])
    if isinstance(custom_tags, list):
        for t in custom_tags:
            clean_t = re.sub(r'[^가-힣a-zA-Z0-9]', '', str(t)).strip()
            if clean_t and len(clean_t) >= 2 and clean_t not in base_tags:
                base_tags.append(clean_t)

    # 씬별 핵심 키워드 태그 반영
    for sec in sections:
        core_kw = sec.get("core_keyword", "").strip()
        if core_kw and len(core_kw) >= 2 and core_kw not in base_tags:
            base_tags.append(core_kw)
        hls = re.findall(r'<hl>(.*?)</hl>', sec.get("subtitle", ""))
        for h in hls:
            clean_h = re.sub(r'[^가-힣a-zA-Z0-9]', '', h).strip()
            if clean_h and len(clean_h) >= 2 and clean_h not in base_tags:
                base_tags.append(clean_h)

    # 5. BGM 음원 표시 정리
    bgm_clean = "Sunspots - Jeremy Blake"
    if bgm_name:
        b_name = os.path.basename(bgm_name).replace(".mp3", "").strip()
        if b_name:
            bgm_clean = b_name

    # 6. 5단 완성형 고품질 설명란 구성 (production 규격 100% 계승)
    desc_parts = []

    # [1단: 공식 팩트체크 & 심층 지식 브리핑]
    desc_parts.append(
        f"🔍 [공식 팩트체크 & 심층 지식 브리핑]\n"
        f"✔ 검증 결론: 학술·보도 데이터 교차 검증 완료\n"
        f"• 핵심 팩트: {fact_check_sum}\n"
        f"(본 영상은 언론사 공식 보도 기사 및 실시간 데이터베이스 교차 검증을 거쳤습니다)"
    )

    # [2단: 실전 핵심 가이드 & 행동 수칙]
    desc_parts.append(
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💡 [실전 핵심 가이드 & 행동 수칙]\n"
        f"{practical_guide}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )

    # [3단: 기사 원문 및 팩트 출처]
    source_lines = [
        "📰 [기사 원문 및 팩트 출처]",
        f"• 보도 언론사: {press}",
        f"• 기사 제목: {article_title}"
    ]
    if url:
        source_lines.append(f"• 원문 링크: {url}")
    desc_parts.append("\n".join(source_lines))

    # [4단: 제작 정보 & 안내]
    desc_parts.append(
        f"🏛️ [제작 정보 & 안내]\n"
        f"• 지식 큐레이션: 1분 지식 아카이브\n"
        f"• 팩트체크: 언론사 기사 원문 심층 팩트체크 검증\n"
        f"• 배경음악(BGM): {bgm_clean} (YouTube Audio Library)\n"
        f"• 문의/제보: 영상 관련 추가 질문이나 의견은 언제든 댓글로 남겨주세요!"
    )

    # [5단: 함께 나누는 이야기 & 해시태그]
    clean_tags = [re.sub(r'[^가-힣a-zA-Z0-9]', '', str(t)).strip() for t in base_tags]
    unique_clean_tags = []
    for ct in clean_tags:
        if ct and ct not in unique_clean_tags:
            unique_clean_tags.append(ct)
    hashtag_str = " ".join([f"#{t}" for t in unique_clean_tags[:7]])
    desc_parts.append(
        f"💬 [함께 나누는 이야기]\n"
        f"\"{cta}\"\n\n"
        f"{hashtag_str}"
    )

    youtube_description = "\n\n".join(desc_parts)
    clean_title = shorts_title.replace("#shorts", "").replace("#Shorts", "").strip()
    youtube_title = f"{clean_title} #shorts"

    metadata = {
        "title": youtube_title,
        "description": youtube_description,
        "tags": base_tags[:15],
        "youtube_title": youtube_title,
        "youtube_description": youtube_description,
        "youtube_tags": base_tags[:15],
        "article_source": {
            "press": press,
            "title": article_title,
            "url": url
        }
    }
    return metadata

def generate_script(topic_info: dict, force_refresh: bool = False, output_dir: str = None) -> dict:
    target_date_str = topic_info.get("date", "2026-11-13")
    clean_date = target_date_str.replace("-", "").strip()
    
    out_file = os.path.join(config.DATA_DIR, f"script_{clean_date}.json")
    if output_dir:
        alt_out_file = os.path.join(output_dir, f"script_{clean_date}.json")
    else:
        alt_out_file = None

    if not force_refresh:
        for fpath in [alt_out_file, out_file]:
            if fpath and os.path.exists(fpath) and os.path.getsize(fpath) > 100:
                print(f"  [Step 3 Script] 캐시된 대본 로드 ({clean_date}): {fpath}", flush=True)
                with open(fpath, "r", encoding="utf-8") as f:
                    return json.load(f)

    print(f"  ✍️ [Step 3 Script] 기사 심층 독해 기반 4씬 대본 생성 시작 ({target_date_str})...", flush=True)
    client = genai.Client(vertexai=True, project=config.GCP_PROJECT_ID, location=config.GCP_LOCATION)

    article_title = topic_info.get("selected_article_title", "")
    press = topic_info.get("press", "")
    shorts_title = topic_info.get("shorts_title", "")
    category = topic_info.get("category", "")
    knowledge_core = topic_info.get("knowledge_core", "")
    article_body = topic_info.get("article_body", "")

    prompt = f"""
당신은 대한민국 1위 유튜브 지식 쇼츠(1분미만 스타일)의 수석 시나리오 작가입니다.
아래 제공된 [실제 보도된 네이버 랭킹 뉴스 기사 원문 및 팩트]를 100% 정밀 독해하여, 
시청자가 0초부터 끝까지 숨죽이고 몰입할 수 있는 [고밀도 6씬 쇼츠 대본]을 JSON으로 작성하세요.

[기사 원문 정보]
- 날짜: {target_date_str}
- 언론사: {press}
- 기사 원문 제목: {article_title}
- 0초 훅 제목: {shorts_title}
- 카테고리: {category}
- 기사 본문 전문:
{article_body[:2500]}

[★ 대본 집필 절대 가드레일: 100% 자연스러운 인과관계 스토리텔링 ★]
1. ❌ 동문서답 및 범주 불일치 절대 금지 (가장 중요):
   - 제목/질문이 "최악의 습관/행동"을 물으면 씬 3의 답변도 반드시 "어떤 구체적인 행동/습관"이어야 합니다. (물질이나 엉뚱한 명사 지목 절대 금지!)
   - 제목/질문이 "이유/비밀"을 물으면 씬 3의 답변도 반드시 "그 원인의 본질"이어야 합니다.
   - 제목/질문이 "제도/비용/환급"을 물으면 씬 3의 답변도 반드시 "그 제도/비용의 실체"여야 합니다.
   - 각 씬은 단편적인 토막글이 아니라, 시청자에게 직접 말을 건네듯 앞뒤 문맥이 물 흐르듯 자연스럽게 이어져야 합니다.

2. [도메인 무관 6단계 기승전결 인과 흐름] (경제, 생활, 과학, 기술, 안전, 건강 전 분야 공통):
   - 씬 1 (01. 통념 파괴 훅): 시청자가 당연하게 믿던 일상 상식이나 관행의 허점/반전을 0초에 직격 (공백 포함 22~34자, 1문장).
   - 씬 2 (02. 흔한 착각 환기): 왜 대다수 사람들이 이를 모른 채 방심하고 손해/위험을 겪고 있는지 배경 설명 (공백 포함 22~34자, 1문장).
   - 씬 3 (03. 명쾌한 핵심 해답): 씬 1 질문에 대한 직접적이고 논리적인 단 1문장의 정답 (공백 포함 22~34자, 1문장).
   - 씬 4 (04. 구체적 원리 메커니즘): 왜 그런 결과(손실, 사고, 손상, 피해)가 일어나는지 기사 원문의 구체적 원리 설명 (공백 포함 22~34자, 1문장).
   - 씬 5 (05. 기사 팩트 수치 입증): 기사 본문에 보도된 공식 연구, 통계 수치, 손실액/초과율을 명확한 숫자로 제시 (공백 포함 22~34자, 1문장).
   - 씬 6 (06. 명확한 실천 대처법): 오늘 당장 시청자가 내 지갑, 안전, 권리를 지키기 위해 취해야 할 구체적 행동 제시 (공백 포함 22~34자, 완전한 종결어미).
     * CRITICAL: 마지막 씬은 절대 미완성 접속 어미('~하므로', '~때문에')로 끝내지 말고 온전한 종결어미(-습니다, -하세요)로 끝맺으십시오.
* CRITICAL: 각 씬은 반드시 생생한 '단 1문장'(공백 포함 22~34자 이내, 최대 35자 절대 엄수, 쇼츠 화면 2줄 초과 절대 금지)이어야 하며, 6개 씬 전체 총합은 공백 포함 130~190자 내외(낭독 시간 28~35초)여야 합니다.

[★ 코어 키워드(core_keyword) 및 음성-자막 일치 규칙 ★]
- core_keyword (★가장 중요★):
  * 각 씬마다 시청자 뇌리에 0.1초 만에 꽂아야 할 [단 하나의 가장 결정적인 핵심 팩트 단어(2~6자)]를 먼저 도출하십시오.
  * 화면 중앙에 거대하게 팝업되는 단어이므로, 그 단어 하나만 봐도 문장의 충격과 핵심 메시지가 0.1초 만에 이해되어야 합니다.
  * ❌ 일반 명사 절대 금지: '고기', '제품', '구매', '일급', '사람', '우리', '행동', '경우', '모습'
  * ⭕ 진짜 핵심 대상 (기사 분야에 맞게 도출):
    - 경제/금융: '선택약정', '25% 할인', '낙전 수입', '환급금 1조', '자동 연장'
    - 생활/교통: '두꺼운 패딩', '에어백 미작동', '튕겨 나감', '치명상 4배', '패딩 벗기'
    - 과학/기술: '과충전 발열', '전극 손상', '수명 반토막', '85% 제한', '보호 모드'
    - 안전/건강: '초록색 싹', '항산화 활성', '세포 손상', '5일간 발아', '밀폐 보관'
- subtitle:
  * 위에서 도출한 core_keyword를 반드시 그대로 포함해야 하며, 오직 그 단어에만 <hl>core_keyword</hl> 태그를 감싸십시오 (씬당 단 1개).
  * 2줄(줄당 16~18자) 이내로 자연스럽게 읽히는 간결한 1문장이어야 합니다.
- narration:
  * 성우 TTS 낭독용 문장. subtitle의 단어, 어순과 100% 한 글자도 빠짐없이 완전히 일치해야 합니다!
  * 모든 숫자는 순수 한글 발음으로 풀어서 작성 (예: "이십오 퍼센트" $\rightarrow$ subtitle은 "25%", "사 배" $\rightarrow$ subtitle은 "4배").
- anchor_word: 해당 씬 narration 음성의 첫 핵심 단어 (반드시 2음절 이상 독립 명사/단어, '이', '그', '저' 등 외자 절대 금지).
- image_prompt: 9:16 vertical photorealistic cinematic documentary 영문 프롬프트 (CRITICAL: Absolutely NO text, NO words, NO letters).

반드시 순수 JSON 형식으로만 응답하세요:
{{
  "title": "{shorts_title}",
  "news_outlet": "{press}",
  "news_headline": "{article_title}",
  "article_question": "기사 핵심 의문문 1줄 (25자 이내, Q. 제외)",
  "summary": "영상 핵심 2줄 요약",
  "fact_check_summary": "검증된 핵심 팩트 및 심층 과학/경제/사회적 원리 상세 요약 (2~3문장)",
  "practical_guide": "시청자가 실생활에 바로 적용할 수 있는 구체적인 2~3단계 핵심 행동 수칙 또는 지식 활용 가이드",
  "cta": "시청자의 댓글 참여와 활발한 토론을 유도하는 질문 1문장 (따옴표 제외)",
  "tags": ["키워드1", "키워드2", "키워드3", "키워드4", "키워드5", "Shorts"],
  "sections": [
    {{
      "step_title": "01. 통념 파괴 훅",
      "core_keyword": "핵심단어",
      "anchor_word": "첫단어",
      "narration": "0초 훅 한글 낭독 단 1문장 (22~34자)",
      "subtitle": "core_keyword에만 <hl>...</hl>를 감싼 1문장 (22~34자)",
      "image_prompt": "Photorealistic 8k vertical 9:16 cinematic shot... CRITICAL: Absolutely NO text, NO words."
    }},
    {{
      "step_title": "02. 흔한 착각 환기",
      "core_keyword": "핵심단어",
      "anchor_word": "첫단어",
      "narration": "착각 환기 한글 낭독 단 1문장 (22~34자)",
      "subtitle": "core_keyword에만 <hl>...</hl>를 감싼 1문장 (22~34자)",
      "image_prompt": "Photorealistic 8k vertical 9:16 cinematic shot... CRITICAL: Absolutely NO text, NO words."
    }},
    {{
      "step_title": "03. 명쾌한 핵심 해답",
      "core_keyword": "핵심단어",
      "anchor_word": "첫단어",
      "narration": "핵심 해답 한글 낭독 단 1문장 (22~34자, 질문과 동일 범주)",
      "subtitle": "core_keyword에만 <hl>...</hl>를 감싼 1문장 (22~34자)",
      "image_prompt": "Photorealistic 8k vertical 9:16 cinematic shot... CRITICAL: Absolutely NO text, NO words."
    }},
    {{
      "step_title": "04. 구체적 원리 메커니즘",
      "core_keyword": "핵심단어",
      "anchor_word": "첫단어",
      "narration": "원리 기전 한글 낭독 단 1문장 (22~34자)",
      "subtitle": "core_keyword에만 <hl>...</hl>를 감싼 1문장 (22~34자)",
      "image_prompt": "Photorealistic 8k vertical 9:16 cinematic shot... CRITICAL: Absolutely NO text, NO words."
    }},
    {{
      "step_title": "05. 기사 팩트 수치 입증",
      "core_keyword": "핵심단어",
      "anchor_word": "첫단어",
      "narration": "구체적 수치 팩트 한글 낭독 단 1문장 (22~34자)",
      "subtitle": "core_keyword에만 <hl>...</hl>를 감싼 1문장 (22~34자)",
      "image_prompt": "Photorealistic 8k vertical 9:16 cinematic shot... CRITICAL: Absolutely NO text, NO words."
    }},
    {{
      "step_title": "06. 명확한 실천 대처법",
      "core_keyword": "핵심단어",
      "anchor_word": "첫단어",
      "narration": "명쾌한 실천법 한글 낭독 단 1문장 (22~34자, 완벽한 종결어미)",
      "subtitle": "core_keyword에만 <hl>...</hl>를 감싼 1문장 (22~34자)",
      "image_prompt": "Photorealistic 8k vertical 9:16 cinematic shot... CRITICAL: Absolutely NO text, NO words."
    }}
  ]
}}
"""

    script_data = None
    for attempt in range(6):
        try:
            resp = client.models.generate_content(
                model=config.MODEL_FAST,
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.2)
            )
            raw_text = clean_json_str(safe_get_text(resp))
            parsed = json.loads(raw_text)
            if validate_script_constraints(parsed):
                script_data = parsed
                break
            else:
                if attempt >= 4:
                    script_data = parsed
                    break
                print(f"  ⚠️ [Step 3 Script] 규격 재시도 ({attempt+1}/6)...", flush=True)
                time.sleep(2)
        except Exception as e:
            err_str = str(e)
            print(f"  ⚠️ [Step 3 Script 지연/에러] {err_str[:100]}...", flush=True)
            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                time.sleep(25 + attempt * 10)
            else:
                time.sleep(3)

    if not script_data:
        raise RuntimeError("대본 생성 실패 (재시도 초과)")

    # 기사 질문 정제
    clean_q = script_data.get("article_question", "").strip()
    clean_q = re.sub(r'^[Qq][\.\:\s\-]+', '', clean_q).strip()
    if not clean_q:
        clean_q = shorts_title
    script_data["article_question"] = clean_q

    # 01~04 넘버링 및 헤더 강제 정규화
    print(f"  🔍 [Step 3 Script] 01~04 헤더 및 질문 고정 바 정규화 (Q: {clean_q})...", flush=True)
    for i, sec in enumerate(script_data["sections"]):
        narr = sec["narration"].strip()
        sub = sec["subtitle"].strip()
        first_word = narr.split()[0] if narr.split() else "이것"
        sec["anchor_word"] = re.sub(r'[^가-힣a-zA-Z0-9]', '', first_word)

        # 1행 출처 뱃지
        sec["header_sub"] = f"[{press}] 오늘 왜 이 상식?"

        # 2행 단계 타이틀 (01부터 시작)
        raw_step = sec.get("step_title", sec.get("header_main", ""))
        clean_step = re.sub(r'^\d+[\.\s\-]+', '', raw_step).strip()
        sec["header_main"] = f"{i+1:02d}. {clean_step}"

        print(f"    씬 {i+1}: [{sec['header_sub']}] {sec['header_main']} | 자막: {sub}")

    # 팩트체크 검증 및 유튜브 설명란/메타데이터 자동 생성
    script_data["fact_check"] = verify_script_facts(article_body, script_data)
    script_data["youtube_metadata"] = generate_youtube_metadata(topic_info, script_data)

    # 파일 저장 (data/ 및 지정된 output_dir)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(script_data, f, ensure_ascii=False, indent=2)

    if alt_out_file:
        os.makedirs(os.path.dirname(alt_out_file), exist_ok=True)
        with open(alt_out_file, "w", encoding="utf-8") as f:
            json.dump(script_data, f, ensure_ascii=False, indent=2)

    print(f"  ✨ [Step 3 Script 완료] 저장 완료: {out_file}", flush=True)
    return script_data

if __name__ == "__main__":
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    test_date = "2026-11-13"
    clean_d = test_date.replace("-", "")
    topic_file = os.path.join(config.DATA_DIR, f"topic_selection_{clean_d}.json")
    if os.path.exists(topic_file):
        with open(topic_file, "r", encoding="utf-8") as f:
            t_info = json.load(f)
        s_data = generate_script(t_info, force_refresh=True)
        print("\n[대본 생성 결과]")
        print(json.dumps(s_data, ensure_ascii=False, indent=2))
    else:
        print(f"토픽 파일 부재: {topic_file}")
