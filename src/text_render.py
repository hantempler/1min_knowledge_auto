# -*- coding: utf-8 -*-
"""폰트가 그릴 수 없는 문자(글자 깨짐) 방지와 안전한 줄바꿈을 담당하는 헬퍼 모듈.

GmarketSansTTFBold.ttf처럼 한글 폰트는 라틴/기호 글리프만 포함하는 경우가 많아,
제목이나 대본에 이모지나 드문 기호가 섞이면 화면에 네모(tofu) 자리가 뜬다.
이 모듈은 다음을 담당한다.

- supported(): 해당 폰트가 실제로 그릴 수 있는 문자 판별
- sanitize(): 그릴 수 없는 문자를 제거/치환하고 남은 공백을 정리
- wrap_text(): 한 단어가 줄 너비를 넘으면 글자 단위로 쪼개는 안전한 줄바꿈
- fit_to_lines(): 지정한 줄 수에 맞게 잘라 말줄임표를 붙임
"""

import re
from functools import lru_cache

from PIL import ImageFont

# 폰트에 없을 때 의미가 가까운 문자로 바꾸는 대응표.
_REPLACEMENTS = {
    "€": "유로",   # €
    "℃": "도",     # ℃
    "℉": "도",     # ℉
    "㎡": "제곱미터",
    "㎥": "세제곱미터",
    "±": "+/-",
    "×": "x",
    "÷": "/",
    "−": "-",      # − (마이너스 부호)
    "…": "...",
    " ": " ",
}

# 여러 공백이 연속으로 남지 않도록 정리
_MULTISPACE_RE = re.compile(r"[ \t]{2,}")


class _Coverage:
    """폰트의 글리프 커버리지를 캐시하며 판별한다.

    fontTools 없이도 동작하도록, 누락 글자가 그려질 때 나타나는 .notdef(네모)
    모양을 직접 렌더링해 비교한다. 어떤 문자가 폰트에 없으면 FreeType이
    .notdef로 대체하므로, 마스크 바이트가 .notdef와 같으면 '그릴 수 없음'이다.
    """

    def __init__(self, font_path: str):
        self.font_path = font_path
        self._probe = ImageFont.truetype(font_path, 48)
        # 개인 사용 영역(U+E000)은 거의 모든 폰트에 없는 문자다.
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
                result = bytes(self._probe.getmask(ch)) != self._notdef
            except Exception:
                result = False
        self._cache[ch] = result
        return result


@lru_cache(maxsize=8)
def _coverage(font_path: str) -> _Coverage:
    return _Coverage(font_path)


def supported(text: str, font_path: str) -> bool:
    """문자열의 모든 문자가 해당 폰트에서 그려지는지 확인한다."""
    cov = _coverage(font_path)
    return all(cov.supported(ch) for ch in text)


def sanitize(text: str, font_path: str) -> str:
    """그릴 수 없는 문자를 제거(또는 대응 문자로 치환)해 깨짐을 막는다."""
    if not text:
        return ""
    cov = _coverage(font_path)
    out = []
    for ch in text:
        if ch in _REPLACEMENTS:
            out.append(_REPLACEMENTS[ch])
            continue
        if cov.supported(ch):
            out.append(ch)
    cleaned = _MULTISPACE_RE.sub(" ", "".join(out))
    return cleaned.strip()


def wrap_text(draw, text: str, font, max_width: int = 980) -> str:
    """단어 단위 줄바꿈. 단 하나가 줄 너비를 넘으면 글자 단위로 쪼갠다.

    기존 구현은 긴 단어를 그대로 흘려보내 화면 밖으로 잘리게 했다.
    """
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
    """지정한 줄 수 안에 들어가도록 자르고, 넘치면 마지막 줄에 말줄임표를 붙인다.

    예전에는 lines[:2]로 자르기만 해서 뒤쪽 내용이 조용히 사라졌다.
    """
    lines = wrap_text(draw, text, font, max_width).split("\n")
    lines = [line for line in lines if line.strip()]
    if len(lines) <= max_lines:
        return "\n".join(lines)
    kept = lines[:max_lines]
    overflow = " ".join(lines[max_lines:])
    kept[-1] = _shorten_to_width(draw, kept[-1] + " " + overflow, font, max_width, ellipsis)
    return "\n".join(kept)
