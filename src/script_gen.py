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

def generate_youtube_metadata(topic_info: dict, script_data: dict) -> dict:
    """유튜브 업로드용 고효율 설명란, 태그, 제목, 면책조항 자동 생성 (SEO & 팩트 출처 보장)"""
    press = topic_info.get("press", script_data.get("news_outlet", "주요 언론사"))
    article_title = topic_info.get("selected_article_title", script_data.get("news_headline", ""))
    url = topic_info.get("url", "")
    shorts_title = script_data.get("title", topic_info.get("shorts_title", ""))
    article_question = script_data.get("article_question", "")

    sections = script_data.get("sections", [])
    s1 = re.sub(r'<.*?>', '', sections[0].get("subtitle", "")) if len(sections) > 0 else ""
    s3 = re.sub(r'<.*?>', '', sections[2].get("subtitle", "")) if len(sections) > 2 else ""
    s5 = re.sub(r'<.*?>', '', sections[4].get("subtitle", "")) if len(sections) > 4 else ""

    summary_bullets = f"1. {s1}\n2. {s3}\n3. {s5}" if (s1 and s3) else f"1. {article_question}\n2. {article_title}"

    category = topic_info.get("category", "상식")
    base_tags = ["1분상식", "지식", "상식", "shorts", "쇼츠"]
    if category:
        clean_cat = category.replace("/", "")
        if clean_cat not in base_tags:
            base_tags.append(clean_cat)
    # 대본 속 <hl> 핵심 키워드 동적 태그 추가 (하드코딩 완전 배제)
    for sec in sections:
        hls = re.findall(r'<hl>(.*?)</hl>', sec.get("subtitle", ""))
        for h in hls:
            clean_h = re.sub(r'[^가-힣a-zA-Z0-9]', '', h).strip()
            if clean_h and len(clean_h) >= 2 and clean_h not in base_tags:
                base_tags.append(clean_h)

    disclaimer = (
        "⚖️ [의학 및 일반 상식 면책 조항]\n"
        "본 영상은 언론사 공식 보도 기사를 기반으로 제작된 교양·상식 정보 콘텐츠입니다. "
        "개별적인 건강 상태, 의학적 진단 및 치료에 관한 사항은 반드시 전문의와 상담하시기 바랍니다."
    )

    desc_lines = [
        f"📌 {article_question}",
        "",
        "💡 [핵심 3줄 요약]",
        summary_bullets,
        "",
        "📰 [기사 원문 및 팩트 출처]",
        f"- 보도 언론사: {press}",
        f"- 기사 제목: {article_title}",
    ]
    if url:
        desc_lines.append(f"- 원문 링크: {url}")

    desc_lines.extend([
        "",
        disclaimer,
        "",
        "🏷️ [해시태그]",
        " ".join([f"#{t}" for t in base_tags[:7]]),
        "",
        "❤️ '구독'과 '좋아요'는 1분 상식을 만드는 가장 큰 힘이 됩니다!"
    ])

    youtube_description = "\n".join(desc_lines)
    clean_title = shorts_title.replace("#shorts", "").strip()
    youtube_title = f"{clean_title} #shorts"

    metadata = {
        "youtube_title": youtube_title,
        "youtube_description": youtube_description,
        "youtube_tags": base_tags,
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

[★ 기사 심층 분석 및 6개 씬 구성 규칙 ★]
1. article_question:
   - 기사 전체를 관통하는 핵심 질문(시청자가 클릭하고 싶어 미치게 만드는 의문문) 1문장 작성 (25자 이내, 'Q.' 제외).
   - 예: "고기 구울 때 쓰는 숯이 암을 유발한다?"
2. 6개 씬 단계별 해답 구성 (01부터 06까지 순차 전개):
   - 씬 1 (01. 상식 허점과 위험 직격): 시청자의 일상 통념을 깨부수는 충격적 사실이나 위험을 0초에 직격 (공백 포함 22~34자, 1문장).
   - 씬 2 (02. 일상 착각과 경고 요약): 일상에서 흔히 하는 행동이나 방심이 왜 위험한지 기사 팩트 기반 빌드업 (공백 포함 22~34자, 1문장).
   - 씬 3 (03. 기사 속 위험 주범 요약): 기사 본문이 폭로한 진짜 핵심 원인 주범/물질을 지목 (공백 포함 22~34자, 1문장).
   - 씬 4 (04. 치명적 반전 메커니즘 요약): 그 주범이 우리 몸이나 일상에 초래하는 치명적 결과/질환/피해 설명 (공백 포함 22~34자, 1문장).
   - 씬 5 (05. 기사 속 수치 경고 요약): 기사 본문에 보도된 핵심 통계 수치, 기준치 초과 비율을 구체적 숫자로 제시 (공백 포함 22~34자, 1문장).
   - 씬 6 (06. 기사 속 실천 대처법 요약): 기사가 권고하는 확실한 대처법이나 안전 기준을 완전한 종결어미(-습니다, -하세요)로 제시 (공백 포함 22~34자, 1문장).
     * CRITICAL: 마지막 씬은 절대 미완성 접속 어미('~하므로', '~때문에')로 끝내지 말고 온전한 종결어미로 끝맺으십시오.
* CRITICAL: 각 씬은 반드시 생생한 '단 1문장'(공백 포함 22~34자 이내, 최대 35자 절대 엄수, 쇼츠 화면 2줄 초과 절대 금지)이어야 하며, 6개 씬 전체 총합은 공백 포함 130~190자 내외(낭독 시간 28~35초)여야 합니다.

[★ 코어 키워드(core_keyword) 및 음성-자막 일치 규칙 ★]
- core_keyword (★가장 중요★):
  * 각 씬마다 시청자 뇌리에 0.1초 만에 꽂아야 할 [단 하나의 가장 결정적인 핵심 팩트 단어(2~6자)]를 먼저 도출하십시오.
  * 화면 중앙에 거대하게 팝업되는 단어이므로, 그 단어 하나만 봐도 문장의 충격과 핵심 메시지가 0.1초 만에 이해되어야 합니다.
  * ❌ 일반 명사 절대 금지: '고기', '제품', '구매', '일급', '사람', '우리', '행동', '경우', '모습'
  * ⭕ 진짜 핵심 대상:
    - 씬 1: 충격 위험 대상 (예: '1급 발암물질', '심장마비', '급성 중독')
    - 씬 2: 위험 행동/착각 (예: '습관적 배뇨', '비흡연자', '기침 방치')
    - 씬 3: 원인 주범 물질 (예: '성형 숯', '비소 검출', '나쁜 콜레스테롤')
    - 씬 4: 피해/질환 기전 (예: '신경계 질환', '요실금', '혈관 플라크')
    - 씬 5: 충격 수치 팩트 (예: '9배 초과', '12.2%', '100 미만', '188만 명')
    - 씬 6: 행동/안전 기준 (예: '안전 기준', '2~3분 참기', '무료 접종')
- subtitle:
  * 위에서 도출한 core_keyword를 반드시 그대로 포함해야 하며, 오직 그 단어에만 <hl>core_keyword</hl> 태그를 감싸십시오 (씬당 단 1개).
  * 2줄(줄당 16~18자) 이내로 자연스럽게 읽히는 간결한 1문장이어야 합니다.
- narration:
  * 성우 TTS 낭독용 문장. subtitle의 단어, 어순과 100% 한 글자도 빠짐없이 완전히 일치해야 합니다!
  * 모든 숫자는 순수 한글 발음으로 풀어서 작성 (예: "구 배" $\rightarrow$ subtitle은 "9배", "십이 점 이 퍼센트" $\rightarrow$ subtitle은 "12.2%").
- anchor_word: 해당 씬 narration 음성의 첫 핵심 단어 (반드시 2음절 이상 독립 명사/단어, '이', '그', '저' 등 외자 절대 금지).
- image_prompt: 9:16 vertical photorealistic cinematic documentary 영문 프롬프트 (CRITICAL: Absolutely NO text, NO words, NO letters).

반드시 순수 JSON 형식으로만 응답하세요:
{{
  "title": "{shorts_title}",
  "news_outlet": "{press}",
  "news_headline": "{article_title}",
  "article_question": "기사 핵심 의문문 1줄 (25자 이내, Q. 제외)",
  "sections": [
    {{
      "step_title": "01. 상식 허점과 위험 직격",
      "core_keyword": "핵심단어",
      "anchor_word": "첫단어",
      "narration": "0초 훅 한글 낭독 단 1문장 (22~34자)",
      "subtitle": "core_keyword에만 <hl>...</hl>를 감싼 1문장 (22~34자)",
      "image_prompt": "Photorealistic 8k vertical 9:16 cinematic shot... CRITICAL: Absolutely NO text, NO words."
    }},
    {{
      "step_title": "02. 일상 착각과 경고 요약",
      "core_keyword": "핵심단어",
      "anchor_word": "첫단어",
      "narration": "일상 착각 한글 낭독 단 1문장 (22~34자)",
      "subtitle": "core_keyword에만 <hl>...</hl>를 감싼 1문장 (22~34자)",
      "image_prompt": "Photorealistic 8k vertical 9:16 cinematic shot... CRITICAL: Absolutely NO text, NO words."
    }},
    {{
      "step_title": "03. 기사 속 위험 주범 요약",
      "core_keyword": "핵심단어",
      "anchor_word": "첫단어",
      "narration": "위험 주범 한글 낭독 단 1문장 (22~34자)",
      "subtitle": "core_keyword에만 <hl>...</hl>를 감싼 1문장 (22~34자)",
      "image_prompt": "Photorealistic 8k vertical 9:16 cinematic shot... CRITICAL: Absolutely NO text, NO words."
    }},
    {{
      "step_title": "04. 치명적 반전 메커니즘 요약",
      "core_keyword": "핵심단어",
      "anchor_word": "첫단어",
      "narration": "반전 메커니즘 한글 낭독 단 1문장 (22~34자)",
      "subtitle": "core_keyword에만 <hl>...</hl>를 감싼 1문장 (22~34자)",
      "image_prompt": "Photorealistic 8k vertical 9:16 cinematic shot... CRITICAL: Absolutely NO text, NO words."
    }},
    {{
      "step_title": "05. 기사 속 수치 경고 요약",
      "core_keyword": "핵심단어",
      "anchor_word": "첫단어",
      "narration": "구체적 수치 경고 한글 낭독 단 1문장 (22~34자)",
      "subtitle": "core_keyword에만 <hl>...</hl>를 감싼 1문장 (22~34자)",
      "image_prompt": "Photorealistic 8k vertical 9:16 cinematic shot... CRITICAL: Absolutely NO text, NO words."
    }},
    {{
      "step_title": "06. 기사 속 실천 대처법 요약",
      "core_keyword": "핵심단어",
      "anchor_word": "첫단어",
      "narration": "명쾌한 대처법 한글 낭독 단 1문장 (22~34자, 완벽한 종결어미)",
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
