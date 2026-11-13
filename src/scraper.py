# -*- coding: utf-8 -*-
"""
[Step 1] 네이버 뉴스 80+개 언론사 실시간/날짜별 랭킹 뉴스 전수 크롤러
- https://news.naver.com/main/ranking/popularDay.naver?date=YYYYMMDD 엔드포인트 수집
- 언론사별 5개 랭킹 기사(총 400~420건) 전수 크롤링
- 기사 원문 본문(#dic_area) 실시간 추출 기능
"""
import os
import sys
import json
import requests
from bs4 import BeautifulSoup
from datetime import datetime

# 루트 경로 추가
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

def get_naver_ranking_by_date(target_date_str: str, force_refresh: bool = False) -> list:
    """
    지정된 날짜(YYYY-MM-DD 또는 YYYYMMDD)의 네이버 뉴스 80+개 전 언론사 랭킹 기사를 전수 수집
    """
    clean_date = target_date_str.replace("-", "").strip()
    cache_file = os.path.join(config.DATA_DIR, f"naver_ranking_{clean_date}.json")

    if not force_refresh and os.path.exists(cache_file) and os.path.getsize(cache_file) > 1000:
        print(f"  [Step 1 Scraper] 캐시된 랭킹 뉴스 로드 ({clean_date}): {cache_file}", flush=True)
        with open(cache_file, "r", encoding="utf-8") as f:
            return json.load(f)

    url = f"https://news.naver.com/main/ranking/popularDay.naver?date={clean_date}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    print(f"  🔍 [Step 1 Scraper] 네이버 전 언론사 랭킹 뉴스 수집 중 ({clean_date}): {url}...", flush=True)
    res = requests.get(url, headers=headers, timeout=10)
    res.raise_for_status()

    soup = BeautifulSoup(res.text, "html.parser")
    boxes = soup.select(".rankingnews_box")
    all_articles = []

    for b in boxes:
        press_tag = b.select_one(".rankingnews_name")
        press_name = press_tag.text.strip() if press_tag else "기타"

        items = b.select(".rankingnews_list li")
        for it in items:
            t_tag = it.select_one(".list_title")
            if not t_tag:
                continue
            title = t_tag.text.strip()
            href = t_tag.get("href", "")
            if title and href:
                all_articles.append({
                    "date": target_date_str,
                    "press": press_name,
                    "title": title,
                    "url": href
                })

    print(f"  ✅ [Step 1 Scraper 완료] 총 {len(boxes)}개 언론사, {len(all_articles)}건 랭킹 기사 수집!", flush=True)

    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(all_articles, f, ensure_ascii=False, indent=2)

    return all_articles

def fetch_article_body(url: str, timeout: int = 5) -> str:
    """기사 URL에서 본문 텍스트(#dic_area)를 추출"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        r = requests.get(url, headers=headers, timeout=timeout)
        s = BeautifulSoup(r.text, "html.parser")
        content_el = s.select_one("#dic_area")
        if content_el:
            return content_el.text.strip()
    except Exception:
        pass
    return ""

if __name__ == "__main__":
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    test_date = "2026-11-12"
    articles = get_naver_ranking_by_date(test_date)
    print(f"\n[테스트 결과] {test_date} 기사 수: {len(articles)}건")
    for i, a in enumerate(articles[:5], 1):
        print(f"  {i}. [{a['press']}] {a['title']}")
