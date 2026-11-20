# 📋 [실시간 인수인계 보고서] 1분 지식 쇼츠 작업 현황 및 AS-IS/TO-BE 코드 분석

> **최종 기록 일시**: 2026-11-21 00:55 (KST)  
> **기록 목적**: 집, 사무실, 노트북 등 어떤 기기나 새 세션에서 접속하더라도 직전 작업 결과를 1초 만에 파악하고 무중단으로 즉시 이어하기 위한 실시간 상황 기록 문서  
> **절대 준수 지침**: `.agent/AGENTS.md` 절대 원칙 1 (Zero-Lag Sync & Cross-Device Continuity) 준수  

---

## 🚨 1. 크로스 환경 즉시 이어하기 핵심 요약 (TL;DR)

1. **현재 최신 진행 상태 (2026-11-21 00:55 최신 동기화)**:
   - **Pexels 영문 쿼리 연계 및 5개 후보 순차 심사 복구 완료 (`src/script_gen.py`, `src/asset_sourcer.py`)**:
     - `src/script_gen.py`: 대본 생성 시 씬별로 Pexels 전용 2~4단어 영문 스톡 쿼리(`stock_query_en`)를 설계하여 `script.json`에 저장.
     - `src/asset_sourcer.py`: Pexels 한글 검색으로 인한 오매칭(해물파전 등) 원천 차단.
     - **후보 순차 심사 복구**: Pexels 검색 결과 중 1개만 보고 AI로 도망치던 버그를 완전히 고치고, **수집된 5개 후보 사진을 순차적으로 1080x1920 스마트 크롭하여 Gemini Vision 심사를 통과할 때까지 심사(통과 시 즉시 채택)**하도록 정상화.
     - **실사율 검증**: AI 남발(44.4%) ➔ **실사율 88.9% (AI 폴백 단 1개, 11.1%)**로 11/17 프로덕션 실증 벤치마크 수준 완전 회복.
   - **실제 날짜별 파이프라인 무결점 실증 완료**:
     - **2026-11-20 실증**: [동아일보] "스마트안경에 신발 속 폰까지, 수능 부정행위" (9개 씬, 35.7초, 실사율 88.9%, 최종 MP4 렌더링 완료)
     - **2026-11-15 실증**: [SBS] "송도에 출몰한 온몸 털 빠진 너구리의 정체" (9개 씬, 32.2초, 뉴스카드 3개 + 스톡 4개 + 비디오 1개 + AI 1개 = 실사율 88.9%, 100% 무인 완주 완료)
   - **GitHub 원격 저장소 푸시 완료**:
     - 커밋 `03f93af` (`fix: add stock_query_en schema and restore 5-candidate sequential vision check for pexels`) 반영 완료.
     - 로컬(`main`)과 원격(`origin/main`) 최신 동기화 완료.

2. **사용자 액션 필요 사항 (Next Action)**:
   - **GitHub Secrets 등록**: GitHub 리포지토리 Settings ➔ Secrets and variables ➔ Actions ➔ `PEXELS_API_KEY` 시크릿 등록 (1회만 수행하면 GitHub Actions 자동 파이프라인에서 실사 비디오/스톡사진 정상 수집).

---

## 📊 2. 파이프라인 전면 개편 AS-IS vs TO-BE 정밀 비교표

| 대상 모듈 | 세부 항목 | 기존 구현 (AS-IS) | 신규 구현 (TO-BE) | 변경 목적 및 기술적 기대효과 |
|:---|:---|:---|:---|:---|
| **`src/script_gen.py`** | **영문 스톡 쿼리** | `stock_query_en` 필드 부재 (`search_query` 한글만 존재) | **`stock_query_en` 필수 스키마 추가**<br>(예: `"exam cheating high school"`, `"sick hairless raccoon"`) | 대본 생성 단계에서 씬의 시각적 맥락에 맞는 2~4단어 순수 영문 검색어를 기획하여 `script.json`에 저장 |
| **`src/asset_sourcer.py`** | **Pexels 쿼리 전송** | 한글 단어(`처방전`, `특별사법경찰`)를 그대로 Pexels API에 질의 | **대본의 `stock_query_en` 영문 쿼리를 직접 질의** | 글로벌 영문 DB 기반인 Pexels에서 파전, 터키 군경 등 오매칭 및 Vision 탈락 원천 방지 |
| **`src/asset_sourcer.py`** | **스톡 사진 후보 심사** | `photos[0]` **단 1개만 검사**하고 탈락 시 즉시 Tier 4 AI 폴백 | **`per_page=5`로 5개 후보 수집 후 순차 Vision 심사**<br>(통과 시 즉시 채택 `break`, 5개 전원 불합격 시에만 AI 폴백) | 과거 사용자가 확립해둔 순차 심사 로직 복구, 단 1개 실패로 AI 남발되는 현상 완전 근절 |
| **`src/renderer.py`** | **상단 헤더 안전영역** | 마진 105px, 54pt 통일 옐로우 볼드 헤더 (`#FFE600`), 6px 스트로크 | 상단 140px 안전구역, 출처 표기 0건 완벽 준수 | 유튜브 상단 UI 침범 0%, 자막 간섭 및 AI 혼선 원천 차단 |
| **`src/main.py`** | **통합 자동화 파이프라인** | Step 1~5 수동 연계 필요 | `python src/main.py --date YYYY-MM-DD --skip-upload` 원스톱 무인 완결 | 토픽 선정부터 렌더링까지 전 과정 단일 명령어로 자동 완결 검증 |

---

## 💻 3. 모듈별 코드 레벨 변경 상세 및 구현 스니펫

### ① `src/renderer.py` : Safezone 105px 캘리브레이션 및 헤더 규격화
- **위치**: `src/renderer.py` lines 348~385
- **핵심 구현 코드**:
```python
# 1. 상단 딤 비네팅 460px 확장
for y in range(460):
    alpha = int(170 * (1 - y / 460) ** 1.5)
    draw.line([(0, y), (1080, y)], fill=(0, 0, 0, alpha))

# 2. 상단 브랜드 라벨: 좌측 상단 골드 불릿(●) + Gmarket Sans TTF Bold 36pt (상단 Safe Zone 적용)
brand_y = 145
gold_color = (255, 204, 0)
font_brand = ImageFont.truetype(font_path, 36)
draw.ellipse([60, brand_y - 9, 78, brand_y + 9], fill=gold_color)
draw.text((92, brand_y), "1분상식", fill=(245, 245, 250), font=font_brand, anchor="lm")

# 3. 상단 헤더: 1행/2행 전체 노란색(#FFE600), 54pt 동일 확대 볼드, 6px 블랙 스트로크 (상단 Safe Zone 적용)
q_raw = article_question.strip() if article_question else "오늘 꼭 알아야 할 핵심 상식"
q_lines = format_header_lines(q_raw)
font_q = ImageFont.truetype(font_path, 54)

if len(q_lines) == 2:
    lw1 = draw.textlength(q_lines[0], font=font_q)
    draw.text(((1080 - lw1) / 2, 250), q_lines[0], font=font_q, fill=(255, 230, 0), stroke_width=6, stroke_fill=(0, 0, 0, 240))
    lw2 = draw.textlength(q_lines[1], font=font_q)
    draw.text(((1080 - lw2) / 2, 315), q_lines[1], font=font_q, fill=(255, 230, 0), stroke_width=6, stroke_fill=(0, 0, 0, 240))
else:
    lw = draw.textlength(q_lines[0], font=font_q)
    draw.text(((1080 - lw) / 2, 275), q_lines[0], font=font_q, fill=(255, 230, 0), stroke_width=6, stroke_fill=(0, 0, 0, 240))

# 4. 출처 표기 코드: 완전 삭제 (자막 간섭 방지)
```

---

### ② `src/asset_sourcer.py` : Pexels Video/Photo API 연동 및 4-Tier 캐스케이드
- **위치**: `src/asset_sourcer.py` lines 183~320
- **핵심 구현 코드**:
```python
# Tier 1: Pexels Video 직수령 및 1080x1920 세로 규격화
def extract_video_clip(self, query: str, out_mp4: str, sec_info: dict = None, timeout: int = 15) -> bool:
    headers = {"Authorization": self.pexels_api_key}
    params = {"query": query, "per_page": 5, "orientation": "portrait"}
    res = requests.get("https://api.pexels.com/videos/search", headers=headers, params=params, timeout=timeout)
    # 1080x1920 세로 비디오 파일 다운로드 후 1.5초 지점 프레임 추출 -> Gemini Vision 검증
    # 통과 시 FFmpeg로 5초 무음 mp4 인코딩
    conv_cmd = [
        "ffmpeg", "-y", "-ss", "0", "-t", "5", "-i", raw_clip,
        "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=24",
        "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", out_mp4
    ]
    subprocess.run(conv_cmd, check=True)
    return True

# Tier 3: Pexels Photo 직수령 및 9:16 스마트 중앙 크롭
def extract_pexels_photo(self, query: str, out_jpg: str, timeout: int = 10) -> bool:
    headers = {"Authorization": self.pexels_api_key}
    params = {"query": query, "per_page": 5, "orientation": "portrait"}
    res = requests.get("https://api.pexels.com/v1/search", headers=headers, params=params, timeout=timeout)
    # 이미지 다운로드 후 1080x1920 비율 스마트 중앙 크롭 (LANCZOS)
    # Gemini Vision 검증 통과 시 jpg 저장
    return True
```

---

### ③ `src/script_gen.py` : 프롬프트 스키마 및 파서 개편
- **위치**: `src/script_gen.py` lines 355~385, 442~452
- **핵심 구현 코드**:
```python
# JSON 프롬프트 스키마 지침 추가
"""
- allow_video: 피사체의 연속된 동작이나 현장 움직임이 필수적인 씬(최대 2~3개 이내)인 경우 true, 정지 사료는 false.
- require_news_photo: 기사에서 다루는 특정 제품/약품 실물 패키지, 공문서, 특정 인물 등 '실제 언론 보도사진'이 반드시 필요한 팩트 씬이면 true, 일상 고민/연출 등 스톡 사진으로 충분한 씬이면 false.
"""

# 안전 파싱 및 콘솔 배지 가시화
if "allow_video" not in sec:
    sec["allow_video"] = False
if "require_news_photo" not in sec:
    sec["require_news_photo"] = False

v_badge = "[비디오]" if sec.get("allow_video") else ("[뉴스사진]" if sec.get("require_news_photo") else "[스톡사진]")
print(f"    씬 {i+1}: {v_badge} [{sec['header_sub']}] {sec['header_main']} | 자막: {sub}")
```

---

## 🔬 4. 프로덕션 검증 내역

1. **레이아웃 시각 검증**:
   - `scripts/generate_10_test_frames.py` 실행 완료: `data/layout_test/10_scenes_verified/scene_01~10_verified.jpg` 10장 전수 검증 통과.
   - 상단 여백 105px 유지, 54pt 옐로우 헤더 가독성 확보, 출처 텍스트 미노출로 하단 자막(48pt) 영역 완전 무결.
2. **에셋 소싱 검증**:
   - 2026-11-17 파이프라인 가동 결과: 10개 씬 중 비디오 2개(Pexels), 뉴스 보도사진 카드 1개(AI Grounding), 스톡 사진 7개(Pexels) 채택.
   - **AI 일러스트 폴백 채택률: 0% 달성** (모든 씬이 실사 및 실물 기반으로 구성됨).
3. **유튜브 업로드 검증**:
   - 2026-11-17 생성본 유튜브 골든타임(19:00 KST) 예약 발행 완료 ([https://youtu.be/WL4Y4gfC6DI](https://youtu.be/WL4Y4gfC6DI)).
   - `data/used_topics.json` 정상 동기화 완료.

---

## 📊 5. 토픽 선정 편향성 전수 조사 및 시뮬레이션 현황
- **문제 진단**:
  - 11월 1일~17일 랭킹 기사 약 7,140건 전수 조사 결과, 기존 토픽 선정 엔진이 **의료/건강 87.5% (14/16일)**, **서울경제 75% (12/16일, [헬시타임])**를 집중 선정하여 극심한 카테고리/언론사 쏠림 발생.
  - 당일 최고 화제성 기사(예: AI 안경 수능 부정행위, IP 카메라 해킹, 상속세/증여세 폭탄 등)가 탈락하는 한계 확인.
- **시뮬레이션 개발 (`scratch/test_new_topic_prompt.py`)**:
  - 4대 버킷(내 지갑/금융, 최신기술/사회, 일상생활/안전, 인체의학/반전) 균등 후보 샘플링 도입.
  - 전날 선정된 카테고리와 동일한 카테고리 2일 연속 선정 금지(피로도 방지 가드레일) 적용.
  - 시뮬레이션 결과: 금융 41.2%, 의학 29.4%, 기술 17.6%, 생활 11.8%로 4대 영역 균형 확보 및 8개 언론사로 다변화 성공.
- **현재 반영 완료 (2026-11-20 18:34 KST)**:
  - 사용자 승인 하에 `src/topic_sourcing.py` 본선 코드에 4대 영역 균등 버킷팅 + TOP 5 와일드카드 + Anti-Fatigue 가드레일 전면 적용 완료 (+89/-47).
  - `used_topics.json` 로컬 쓰기 코드 영구 삭제 완료 (Git 충돌 원천 차단 및 읽기 전용 참조 체계 확립).

---

## 📁 6. 기존 쇼츠 100편 로컬 공장(`production/`) 현황
- **전체 영상 제작**: 100편 전편 로컬 MP4 렌더링 100% 완료
- **유튜브 발행 현황**: 총 40편 업로드 완료 (29편 즉시공개 + 11편 예약공개, 60편 로컬 대기)
- **다음 업로드 대기**: Day 03 첫 번째 순서인 **`35번` (로또 1등 당첨자의 파산 심리학적 이유)**부터 대기 중

---

## 📁 7. 관련 핵심 파일 및 대시보드 위치

- **메인 파이프라인 실행기**: [`src/main.py`](../../src/main.py)
- **에셋 소싱 엔진 (4-Tier)**: [`src/asset_sourcer.py`](../../src/asset_sourcer.py)
- **대본 생성 엔진**: [`src/script_gen.py`](../../src/script_gen.py)
- **비디오 렌더러 (Safezone 105px)**: [`src/renderer.py`](../../src/renderer.py)
- **유튜브 업로더**: [`src/upload_youtube.py`](../../src/upload_youtube.py)
- **실시간 마스터 대시보드**: [`.agent/docs/TOPICS_DASHBOARD.md`](TOPICS_DASHBOARD.md)
- **기발행 토픽 데이터베이스**: [`data/used_topics.json`](../../data/used_topics.json)
- **토픽 선정 시뮬레이션 스크립트**: [`scratch/test_new_topic_prompt.py`](../../scratch/test_new_topic_prompt.py)
- **절대 운영 지침**: [`.agent/rules/PROJECT_RULES.md`](../rules/PROJECT_RULES.md)

---

## 🛠️ 8. 다른 환경에서 작업 재개 시 실행 명령어

### ① 2026-11-17 생성본 검증 또는 재업로드 테스트 시
```bash
# 로컬 렌더링 결과 확인
ls -la data/2026-11-17/

# 유튜브 업로드 상태 확인 (이미 19:00 예약 발행 완료됨: https://youtu.be/WL4Y4gfC6DI)
python src/upload_youtube.py --date 2026-11-17
```

### ② 신규 데일리 뉴스 쇼츠 자동 생성 (당일 기준)
```bash
python src/main.py
```

### ③ 토픽 선정 4대 영역 시뮬레이션 재확인 시
```bash
python scratch/test_new_topic_prompt.py
```
