# 📋 [실시간 인수인계 보고서] 1분 지식 쇼츠 작업 현황 및 AS-IS/TO-BE 코드 분석

> **최종 기록 일시**: 2026-11-20 18:58 (KST)  
> **기록 목적**: 집, 사무실, 노트북 등 어떤 기기나 새 세션에서 접속하더라도 직전 작업 결과를 1초 만에 파악하고 무중단으로 즉시 이어하기 위한 실시간 상황 기록 문서  
> **절대 준수 지침**: `.agent/AGENTS.md` 절대 원칙 1 (Zero-Lag Sync & Cross-Device Continuity) 준수  

---

## 🚨 1. 크로스 환경 즉시 이어하기 핵심 요약 (TL;DR)

1. **현재 최신 진행 상태 (2026-11-20 프로덕션 완결)**:
   - **2026-11-17 데일리 쇼츠 제작 및 유튜브 예약 업로드 100% 완료**:
     - **주제**: [서울경제] "매일 마시는 '이 음료'가 대장 근육을 살리는 이유"
     - **유튜브 실물 링크**: **[https://youtu.be/WL4Y4gfC6DI](https://youtu.be/WL4Y4gfC6DI)** (2026-11-17 19:00 KST 골든타임 예약 발행 완료)
     - **완성 영상**: `data/2026-11-17/2026-11-17.mp4` (12.32 MB, 39.6초, 1080x1920)
     - `data/used_topics.json` 최신 등록 완료.
   - **비주얼 에셋 소싱 4-Tier 하이브리드 캐스케이드 전면 개편 완료 (`src/asset_sourcer.py`, `src/script_gen.py`)**:
     - 기존 불안정했던 `yt-dlp` 전면 폐기 ➔ **Pexels Video API 공식 연동** (1080x1920 네이티브 세로 FHD, 워터마크 0%, 레터박스 0%).
     - **Pexels Photo API 연동** (스마트 9:16 크롭 + Vertex AI Vision 검증).
     - **4-Tier Cascade**: Tier 1(Pexels Video) ➔ Tier 2(Google Grounding 보도사진 뉴스카드) ➔ Tier 3(Pexels 고화질 스톡 포토) ➔ Tier 4(Gemini Nano Banana AI 실사 폴백).
   - **상단 헤더 안전영역(Safezone) 캘리브레이션 완료 (`src/renderer.py`)**:
     - 옵션 2 기준 마진 105px 확보 (`brand_y = 145`, 질문 1행 `y=250`, 2행 `y=315`). 유튜브 상단 UI 침범 0%.
     - 질문 헤더 1행/2행 전체 54pt 통일 볼드, 100% 노란색 (`#FFE600`), 6px 스트로크 통일.
     - 사용자 지침에 따라 **출처 표기 전면 배제** (자막 간섭 및 AI 혼선 원천 차단).
   - **토픽 선정 엔진(`src/topic_sourcing.py`) 전면 개편 및 실측 테스트 검증 완료 (2026-11-20 18:56 KST)**:
     - **키워드 하드코딩 완전 삭제**: 인위적 키워드 필터링(`exclude_keywords`, `TAXONOMY` 등) 전면 영구 삭제.
     - **15대 언론사 랭킹 전수 인덱싱**: 주요 15대 언론사 랭킹 기사 총 75건 풀(`[기사 01]`~`[기사 75]`)을 Gemini 3.5 Flash에 직공급.
     - **사용자 지정 100점 채점제 도입**: 대중성(50점) / 손실회피(25점) / 상식반전(25점) 정량 채점.
     - **Anti-Fatigue 가드레일**: `used_topics.json`에서 전날 카테고리 읽기 전용 참조 후 배제 + 서울경제 연속 선정 배제.
     - **Git 충돌 원천 차단**: `used_topics.json` 로컬 쓰기 코드 완전 삭제 및 Git `skip-worktree` 적용.
     - **실제 테스트 검증 통과 (`--date 2026-11-20 --force`)**:
       - 1위 선정: `[기사 49]` [머니투데이] `"갑자기 쌀뜨물 설사"…10년 만에 콜레라 국내 감염 확인`
       - 쇼츠 제목: `10년 만에 한국 덮친 '쌀뜨물 설사'의 정체` (카테고리: `인체의학/반전`)
       - 점수: 대중성 46/50 | 손실회피 24/25 | 상식반전 23/25 | 총점 93/100
       - 기사 본문 1,434자 정상 수집 완료 (`data/topic_selection_20261120.json`). 로컬 Git 변경 오염 0건.

2. **지금 바로 시작해야 할 작업 (Next Action)**:
   - 사용자 승인 하에 당일(`2026-11-20`) 쇼츠 후속 파이프라인 진행: Step 3 대본 생성(`python src/script_gen.py`) $\rightarrow$ Step 4 TTS $\rightarrow$ Step 5-A Pexels 에셋 소싱 $\rightarrow$ Step 5-B 렌더링.
   - 또는 변경된 소스코드 일괄 커밋(`git add src/ .gitignore .agent/`).

---

## 📊 2. 파이프라인 전면 개편 AS-IS vs TO-BE 정밀 비교표

| 대상 모듈 | 세부 항목 | 기존 구현 (AS-IS) | 신규 구현 (TO-BE) | 변경 목적 및 기술적 기대효과 |
|:---|:---|:---|:---|:---|
| **`src/renderer.py`** | **상단 딤 비네팅** | `range(380)` 선형 딤 그라데이션 | **`range(460)`** 확장 딤 그라데이션 | 상단 마진 확장에 맞추어 배경 영상 대비 텍스트 시인성 80px 추가 확보 |
| | **브랜드 라벨** | 중앙 상단 배치<br>`(1080-cw)/2, y=75`<br>스카이블루 텍스트 (`#38BDF8`) | **좌측 상단 골드 불릿 + 화이트 볼드**<br>`x=60, brand_y=145`<br>골드 원(`r=9`, `#FFCC00`) + Gmarket Sans 36pt | 유튜브 앱 상단 검색/카메라 UI 겹침 완전 방지, 레퍼런스 디자인 100% 일치 |
| | **질문 헤더 폰트** | 1행: 화이트 38pt (`y=135`)<br>2행: 옐로우 44pt (`y=190`)<br>4px 블랙 스트로크 | **1행/2행 전체 54pt 통일 확대 볼드**<br>**전체 100% 옐로우 (`#FFE600`) 통일**<br>**6px 블랙 스트로크 (`(0, 0, 0, 240)`)** | 가독성 편차 해소, 모바일 환경에서 시선 즉각 집중 유도 |
| | **질문 헤더 위치** | 1행 `y=135`, 2행 `y=190` | **1행 `y=250`, 2행 `y=315`**<br>(단일행일 경우 `y=275`) | 라벨-헤더 간격 105px 안전 여백 확보 (Option 2 레이아웃 확정) |
| | **출처 표기** | 자막 상단/하단 출처 텍스트 표기 | **출처 표기 코드 전면 삭제** | 부정확한 출처 표기 방지 및 하단 본문 자막(48pt)과의 간섭 완전 차단 |
| | **하이브리드 인코딩** | 단일 스틸 이미지 루프 + ZoomPan 단독 | **Video / Still 하이브리드 분기 인코딩**<br>- 비디오: 무음 5초 trim 루프 인코딩<br>- 카드/스톡: ZoomPan + 콜아웃 팝업 | Pexels 세로 동영상 씬과 스틸 이미지 씬을 단일 FFmpeg 타임라인으로 병합 |
| | **CLI 실행 지원** | 하드코딩 날짜(`2026-11-13`) | **`--date`, `--bgm`, `--force` argparse 체계** | 전체 파이프라인 실행 없이 특정 일자 렌더러만 단독 디버깅 가능 |
| **`src/asset_sourcer.py`** | **소싱 아키텍처** | **3-Tier 구조**<br>(유튜브영상 $\rightarrow$ 보도사진 $\rightarrow$ AI) | **4-Tier 폭포수(Cascade) 구조**<br>(Pexels영상 $\rightarrow$ 뉴스카드 $\rightarrow$ Pexels사진 $\rightarrow$ AI) | AI 생성물 특유의 이질감 배제, 100% 실사/실물 위주 고품질 구성 |
| | **Tier 1 비디오 소싱** | `yt-dlp` 기반 유튜브 검색 & 컷<br>(워터마크, 가로 레터박스, 20초 타임아웃) | **Pexels Video API 직수령**<br>(1080x1920 세로 FHD, 1초 다운로드,<br>1.5초 프레임 Gemini Vision 검증) | 워터마크 0%, 레터박스 0%, 초고속 무결점 다운로드 및 시각적 검증 통과 |
| | **Tier 2 뉴스 보도사진** | 모든 씬에서 기사 사진 억지 검색 | **`require_news_photo=True` 씬만 선별 가동**<br>(약품 실물, 공문서, 통계 그래프 등) | 공식 사료가 필수적인 씬에만 검색 집중, 9:16 블러 배경 + 라운딩(r=28) 플로팅 카드 합성 |
| | **Tier 3 스톡 사진** | 별도 스톡 엔진 부재 (즉시 AI 생성) | **Pexels Photo API 연동 (`extract_pexels_photo`)**<br>(세로 고화질 스톡 $\rightarrow$ 9:16 스마트 크롭) | 감정/상황/일상 연출 씬에서 불필요한 AI 생성 방지, 자연스러운 실사 채택 |
| | **Tier 4 AI 폴백** | 1~2단계 탈락 시 즉시 AI 생성 | **1~3단계 전원 탈락 시에만 최종 안전망 가동**<br>(Gemini Nano Banana 2.1) | 파이프라인 무중단성 유지하면서 실제 AI 채택률은 0%대로 최소화 |
| **`src/script_gen.py`** | **프롬프트 스키마** | `allow_video` (bool) 필드만 정의 | **`allow_video` + `require_news_photo` (bool) 2원화** | 씬별로 비디오/실사보도사진/스톡사진 필요 여부를 기획 단계에서 선별 |
| | **파서 방어 코드** | `allow_video` 누락 방어만 존재 | `allow_video`, `require_news_photo` 기본값(`False`) 방어 및 `[비디오]/[뉴스사진]/[스톡사진]` 로그 출력 | JSON 파싱 시 KeyError 예방 및 기획 단계 에셋 할당 현황 가시화 |
| **`src/upload_youtube.py`** | **실행 인터페이스** | 단순 스크립트 실행 형태 | **`--date`, `--mode`, `--schedule-hour` CLI 지원** | 골든타임(19:00 KST) 예약, 즉시 공개, 특정 날짜 지정 업로드 단독 실행 지원 |
| **`src/tts_gen.py`** | **실행 인터페이스** | 하드코딩 날짜(`2026-11-12`) | **`--date`, `--force` CLI 지원** | 오디오 음성 합성 및 Whisper 싱크 타임스탬프 단독 추출 가능 |
| **`scripts/generate_10_test_frames.py`** | **레이아웃 검증기** | 부재 (영상 인코딩 완료 후에만 확인 가능) | **10개 씬 전수 레이아웃 합성 검증기 신설**<br>(10장 프레임 이미지 초고속 출력) | Safezone, 헤더, 콜아웃, 하단 자막 겹침 여부를 인코딩 전 5초 만에 사전 전수 검증 |
| **`data/used_topics.json`** | **데이터 등록 상태** | 2026-11-16 (오젬픽 실명)까지 등록 | **2026-11-17 (대장 근육 음료) 등록 완료** | 당일 발행 완료된 뉴스 주제 및 언론사 URL 중복 방지 DB 동기화 |

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
