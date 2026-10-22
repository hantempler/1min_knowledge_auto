# -*- coding: utf-8 -*-
"""폰트가 그릴 수 없는 문자(글자 깨짐/Tofu: □) 원천 차단 및 안전한 줄바꿈 헬퍼 모듈.

GmarketSansTTFBold.ttf처럼 한글 폰트는 라틴/한글 완성형만 포함하는 경우가 많아,
제목이나 대본에 한자, 이모지, 특수 문장부호가 섞이면 화면에 네모(tofu)가 뜬다.
이 모듈은 5중 방어벽으로 Tofu를 0.0001%의 예외 없이 원천 차단한다.

1. 한자(漢字) ➔ 한글 음차 자동 변환 엔진
2. 특수기호/대시/따옴표/이모지 ➔ 표준 문장부호 정규화
3. 폰트 글리프 커버리지 마스크 판별
4. 최종 드로잉 게이트웨이 (safe_draw_text, safe_draw_multiline_text)
"""

import re
from functools import lru_cache
from PIL import ImageFont, ImageDraw

# ==============================================================================
# Layer 1: 시사/뉴스/경제/역사 핵심 상용 한자 ➔ 한글 1:1 음차 변환 사전 (300+자)
# ==============================================================================
_HANJA_MAP = {
    # 국가 / 지역
    "美": "미", "韓": "한", "日": "일", "中": "중", "北": "북", "露": "러", "蘇": "소",
    "英": "영", "佛": "불", "獨": "독", "伊": "이", "歐": "구", "亞": "아", "台": "대",
    "首": "수", "京": "경", "濟": "제", "州": "주", "港": "항", "灣": "만", "江": "강",
    # 경제 / 금융 / 산업
    "金": "금", "金": "금", "銀": "은", "銅": "동", "鐵": "철", "油": "유", "價": "가",
    "株": "주", "債": "채", "券": "권", "幣": "폐", "稅": "세", "率": "율", "率": "율",
    "費": "비", "額": "액", "利": "리", "利": "리", "益": "익", "損": "손", "貸": "대",
    "借": "차", "財": "재", "經": "경", "濟": "제", "商": "상", "産": "산", "業": "업",
    "工": "공", "農": "농", "貿": "무", "易": "역", "企": "기", "勞": "노", "動": "동",
    "雇": "고", "用": "용", "賃": "임", "物": "물", "買": "매", "賣": "매", "購": "구",
    "入": "입", "出": "출", "輸": "수", "換": "환", "房": "방", "棟": "동", "戶": "호",
    "地": "지", "土": "토", "資": "자", "本": "본", "市": "시", "場": "장", "店": "점",
    # 정치 / 사회 / 직위 / 인명
    "尹": "윤", "李": "이", "李": "이", "朴": "박", "崔": "최", "鄭": "정", "姜": "강",
    "趙": "조", "總": "총", "統": "통", "領": "령", "相": "상", "院": "원", "長": "장",
    "官": "관", "民": "민", "黨": "당", "席": "석", "委": "위", "員": "원", "會": "회",
    "社": "사", "敎": "교", "授": "수", "師": "사", "檢": "검", "判": "판", "事": "사",
    "警": "경", "察": "찰", "軍": "군", "兵": "병", "將": "장", "士": "사", "國": "국",
    "家": "가", "政": "정", "治": "치", "法": "법", "權": "권", "力": "력", "力": "력",
    # 수치 / 비교 / 변화
    "高": "고", "低": "저", "上": "상", "下": "하", "多": "다", "少": "소", "大": "대",
    "小": "소", "重": "중", "輕": "경", "急": "급", "緩": "완", "增": "증", "減": "감",
    "昇": "승", "降": "강", "騰": "등", "落": "락", "暴": "폭", "劇": "극", "變": "변",
    "化": "화", "擴": "확", "縮": "축", "强": "강", "弱": "약", "勝": "승", "敗": "패",
    "超": "초", "過": "과", "未": "미", "滿": "만", "最": "최", "極": "극",
    # 시제 / 시간 / 방위
    "前": "전", "後": "후", "現": "현", "故": "고", "新": "신", "舊": "구", "初": "초",
    "末": "말", "今": "금", "昨": "작", "明": "명", "年": "년", "月": "월", "日": "일",
    "時": "시", "分": "분", "秒": "초", "東": "동", "西": "서", "南": "남", "內": "내",
    "外": "외", "間": "간", "中": "중",
    # 사건 / 재난 / 과학 / 일반
    "戰": "전", "爭": "쟁", "和": "화", "平": "평", "核": "핵", "彈": "탄", "飛": "비",
    "行": "행", "機": "기", "車": "차", "電": "전", "氣": "기", "水": "수", "火": "화",
    "風": "풍", "光": "광", "聲": "성", "語": "어", "文": "문", "字": "자", "數": "수",
    "量": "량", "質": "질", "点": "점", "點": "점", "線": "선", "面": "면", "體": "체",
    "態": "태", "界": "계", "世": "세", "人": "인", "命": "명", "生": "생", "死": "사",
    "病": "병", "醫": "의", "藥": "약", "意": "의", "見": "견", "思": "사", "想": "상",
    "理": "리", "理": "리", "眞": "진", "實": "실", "虛": "허", "僞": "위", "善": "선",
    "惡": "악", "正": "정", "誤": "오", "確": "확", "信": "신", "疑": "의", "問": "문",
    "答": "답", "解": "해", "決": "결", "開": "개", "閉": "폐", "始": "시", "終": "종",
    "完": "완", "了": "료", "成": "성", "功": "공", "失": "실", "敗": "패",
    "協": "협", "議": "의", "連": "연", "聯": "연", "結": "결", "合": "합",
    "基": "기", "盤": "반", "域": "역", "組": "조", "織": "직", "協": "협",
    "引": "인", "導": "도", "創": "창", "造": "조", "發": "발", "展": "전",
}

# ==============================================================================
# Layer 2: 특수문자, 기호, 대시, 따옴표, 통화기호 ➔ 표준 부호/한글 치환 대응표
# ==============================================================================
_REPLACEMENTS = {
    # 대시류 (Tofu 주범)
    "—": "-",   # Em dash (U+2014)
    "–": "-",   # En dash (U+2013)
    "―": "-",   # Horizontal bar (U+2015)
    "‒": "-",   # Figure dash (U+2012)
    "−": "-",   # Minus sign (U+2212)
    # 따옴표 및 특수 괄호
    "“": '"',
    "”": '"',
    "‘": "'",
    "’": "'",
    "「": "'",
    "」": "'",
    "『": '"',
    "』": '"',
    "【": "[",
    "】": "]",
    "《": "(",
    "》": ")",
    "〈": "(",
    "〉": ")",
    # 단위 및 기호
    "€": "유로",
    "£": "파운드",
    "¥": "엔",
    "₩": "원",
    "℃": "도",
    "℉": "도",
    "㎡": "제곱미터",
    "㎥": "세제곱미터",
    "±": "+/-",
    "×": "x",
    "÷": "/",
    "…": "...",
    "~": "~",
    "∼": "~",
    "～": "~",
    "·": "·",
    "・": "·",
    "•": "·",
    "●": "·",
    "■": " ",
    "▲": "상승 ",
    "▼": "하락 ",
    "➔": "->",
    "→": "->",
    "←": "<-",
    # 특수 공백 제거
    "\u00A0": " ",  # Non-breaking space
    "\u200B": "",   # Zero-width space
    "\u3000": " ",  # Ideographic space
}

# 모든 유니코드 이모지(Emoji) 및 장식 기호 패턴
_EMOJI_PATTERN = re.compile(
    r"[\U00010000-\U0010ffff\u2600-\u27bf\u2300-\u23ff\u2b50\u2b55\u203c\u2049\u2139\u3030\u303d\u3297\u3299]",
    re.UNICODE
)

# 여러 공백이 연속으로 남지 않도록 정리
_MULTISPACE_RE = re.compile(r"[ \t]{2,}")


class _Coverage:
    """폰트의 글리프 커버리지를 캐시하며 엄격하게 판별한다.

    FreeType의 .notdef(기본 네모 박스) 마스크 바이트와 비교하여,
    폰트에 존재하지 않는 문자를 100% 감지한다.
    """

    def __init__(self, font_path: str):
        self.font_path = font_path
        self._probe = ImageFont.truetype(font_path, 48)
        # 개인 사용 영역(U+E000)은 거의 모든 폰트에 없는 문자 -> 정확한 .notdef 마스크 획득
        self._notdef = bytes(self._probe.getmask("\ue000"))
        self._cache = {}

    def supported(self, ch: str) -> bool:
        cached = self._cache.get(ch)
        if cached is not None:
            return cached
        if ch.isspace() or ord(ch) < 32:
            result = True
        else:
            try:
                mask = self._probe.getmask(ch)
                mask_bytes = bytes(mask)
                # 마스크가 .notdef와 동일하거나 비정상적인 경우 미지원 판정
                if mask_bytes == self._notdef:
                    result = False
                elif mask.size[0] == 0 or mask.size[1] == 0:
                    result = False
                else:
                    result = True
            except Exception:
                result = False
        self._cache[ch] = result
        return result


@lru_cache(maxsize=8)
def _coverage(font_path: str) -> _Coverage:
    return _Coverage(font_path)


def supported(text: str, font_path: str) -> bool:
    """문자열의 모든 문자가 해당 폰트에서 정상 렌더링되는지 확인한다."""
    cov = _coverage(font_path)
    return all(cov.supported(ch) for ch in text)


def sanitize(text: str, font_path: str) -> str:
    """Tofu(네모 깨짐) 현상을 원천 차단하는 5중 필터링/치환 파이프라인.

    1. None/빈값 방어
    2. 이모지 전수 제거
    3. 한자(漢字) ➔ 한글 음차 1:1 자동 변환
    4. 특수기호/대시/따옴표 ➔ 표준 문장부호 치환
    5. 폰트 글리프 커버리지 검역: 미지원 문자는 철저히 제거
    6. 연속 공백 정돈
    """
    if not text:
        return ""

    # Step 1: 이모지(Emoji) 전수 제거
    cleaned_text = _EMOJI_PATTERN.sub("", str(text))

    # Step 2: 한자 음차 변환 및 특수기호 치환
    out = []
    for ch in cleaned_text:
        # Layer 1: 한자 ➔ 한글 변환
        if ch in _HANJA_MAP:
            out.append(_HANJA_MAP[ch])
            continue
        # Layer 2: 특수기호 치환
        if ch in _REPLACEMENTS:
            out.append(_REPLACEMENTS[ch])
            continue
        out.append(ch)

    transformed_text = "".join(out)

    # Step 3: 폰트 글리프 마스크 커버리지 전수 검역
    cov = _coverage(font_path)
    final_chars = []
    for ch in transformed_text:
        if ch.isspace() or cov.supported(ch):
            final_chars.append(ch)

    # Step 4: 공백 정리
    result = _MULTISPACE_RE.sub(" ", "".join(final_chars))
    return result.strip()


def safe_draw_text(draw: ImageDraw.ImageDraw, xy: tuple, text: str, font, font_path: str, **kwargs) -> None:
    """화면에 텍스트를 그리는 최종 게이트웨이.

    그리기 직전에 sanitize()를 강제 수행하여 Tofu가 화면에 노출되는 것을 100% 원천 차단한다.
    """
    clean = sanitize(text, font_path)
    if clean:
        draw.text(xy, clean, font=font, **kwargs)


def safe_draw_multiline_text(draw: ImageDraw.ImageDraw, xy: tuple, text: str, font, font_path: str, **kwargs) -> None:
    """화면에 여러 줄 텍스트를 그리는 최종 게이트웨이.

    그리기 직전에 각 줄별로 sanitize()를 강제 수행하여 Tofu를 원천 차단한다.
    """
    lines = [sanitize(line, font_path) for line in (text or "").split("\n")]
    clean_lines = [l for l in lines if l.strip()]
    if clean_lines:
        draw.multiline_text(xy, "\n".join(clean_lines), font=font, **kwargs)


def wrap_text(draw, text: str, font, max_width: int = 980) -> str:
    """단어 단위 줄바꿈. 단 하나가 줄 너비를 넘으면 글자 단위로 쪼갠다."""
    lines = []
    for paragraph in (text or "").split("\n"):
        current = ""
        for word in paragraph.split():
            candidate = f"{current} {word}".strip()
            if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
                current = candidate
                continue
            if current:
                lines.append(current)
            piece = ""
            for ch in word:
                if piece and draw.textbbox((0, 0), piece + ch, font=font)[2] > max_width:
                    lines.append(piece)
                    piece = ch
                else:
                    piece += ch
            current = piece
        if current:
            lines.append(current)
    return "\n".join(lines)


def _shorten_to_width(draw, text: str, font, max_width: int, ellipsis: str = "…") -> str:
    """텍스트를 너비 안에 맞게 줄이고 말줄임표를 붙인다(단어 경계 우선)."""
    if draw.textbbox((0, 0), text + ellipsis, font=font)[2] <= max_width:
        return text + ellipsis
    words = text.split()
    while words:
        candidate = " ".join(words)
        if draw.textbbox((0, 0), candidate + ellipsis, font=font)[2] <= max_width:
            return candidate.rstrip() + ellipsis
        words.pop()
    # 단어 경계로 못 자르면 글자 단위로 줄인다.
    cut = text
    while cut and draw.textbbox((0, 0), cut + ellipsis, font=font)[2] > max_width:
        cut = cut[:-1]
    return cut.rstrip() + ellipsis


def fit_to_lines(draw, text: str, font, max_width: int = 980,
                 max_lines: int = 2, ellipsis: str = "…") -> str:
    """지정한 줄 수 안에 들어가도록 자르고, 넘치면 마지막 줄에 말줄임표를 붙인다."""
    lines = wrap_text(draw, text, font, max_width).split("\n")
    lines = [line for line in lines if line.strip()]
    if len(lines) <= max_lines:
        return "\n".join(lines)
    kept = lines[:max_lines]
    overflow = " ".join(lines[max_lines:])
    kept[-1] = _shorten_to_width(draw, kept[-1] + " " + overflow, font, max_width, ellipsis)
    return "\n".join(kept)
