import sys
import json
import requests
from bs4 import BeautifulSoup

def get_naver_headlines():
    print("  -> 네이버 뉴스 분야별 헤드라인 수집 중...")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Safari/537.36"
    }
    
    sections = {
        "정치": "100",
        "경제": "101",
        "사회": "102",
        "세계": "104",
        "IT/과학": "105"
    }
    
    news_data = []
    
    for category, sid in sections.items():
        url = f"https://news.naver.com/section/{sid}"
        try:
            res = requests.get(url, headers=headers, timeout=8)
            res.raise_for_status()
            soup = BeautifulSoup(res.text, "html.parser")
            
            # 메인 헤드라인 기사 링크 추출
            headline_link = soup.select_one('.sa_text_title')
            if headline_link and headline_link.has_attr('href'):
                article_url = headline_link['href']
                title_text = headline_link.text.strip()
                content_text = ""
                image_url = ""
                
                # 본문 페이지 크롤링 (타임아웃 8초, 실패 시 헤드라인 제목으로 폴백)
                try:
                    art_res = requests.get(article_url, headers=headers, timeout=8)
                    art_res.raise_for_status()
                    art_soup = BeautifulSoup(art_res.text, "html.parser")
                    
                    title = art_soup.select_one('#title_area')
                    if title and title.text.strip():
                        title_text = title.text.strip()
                    
                    content = art_soup.select_one('#dic_area')
                    if content and content.text.strip():
                        content_text = content.text.strip()
                    
                    # 메인 이미지 (og:image)
                    og_image = art_soup.select_one('meta[property="og:image"]')
                    if og_image and og_image.get('content'):
                        image_url = og_image['content']
                except Exception as sub_e:
                    print(f"    [{category}] 상세 본문 수집 건너뜀(헤드라인 정보로 대체): {sub_e}")
                
                # 본문이 너무 길면 앞부분만 자르기 (LLM 입력용)
                if len(content_text) > 1000:
                    content_text = content_text[:1000] + "..."
                
                news_data.append({
                    "category": category,
                    "title": title_text,
                    "content": content_text or title_text,
                    "image_url": image_url,
                    "url": article_url
                })
                print(f"    [{category}] 성공: {title_text}")
            else:
                print(f"    [{category}] 헤드라인 링크를 찾을 수 없습니다.")
        except Exception as e:
            print(f"    [{category}] 스크래핑 실패: {e}")

    # 스포츠 및 연예 (Google News RSS - 최근 12시간 이내 뉴스만 수집)
    for cat, query in [("스포츠", "스포츠+뉴스+when:12h"), ("연예", "연예+뉴스+when:12h")]:
        try:
            rss_url = f"https://news.google.com/rss/search?q={query}&hl=ko&gl=KR&ceid=KR:ko"
            r_res = requests.get(rss_url, headers=headers, timeout=8)
            try:
                r_soup = BeautifulSoup(r_res.text, "xml")
            except Exception:
                r_soup = BeautifulSoup(r_res.text, "html.parser")
            item = r_soup.find("item")
            if item:
                title_text = item.title.text if item.title else ""
                link = item.link.text if item.link else ""
                
                # 이미지 추출 시도
                image_url = ""
                try:
                    art_res = requests.get(link, headers=headers, timeout=5)
                    art_soup = BeautifulSoup(art_res.text, "html.parser")
                    og_image = art_soup.select_one('meta[property="og:image"]')
                    if og_image and og_image.get('content'):
                        image_url = og_image['content']
                except:
                    pass
                
                news_data.append({
                    "category": cat,
                    "title": title_text,
                    "content": title_text,
                    "image_url": image_url,
                    "url": link
                })
                print(f"    [{cat}] 성공: {title_text}")
            else:
                print(f"    [{cat}] 결과 없음")
        except Exception as e:
            print(f"    [{cat}] 스크래핑 실패: {e}")

    # 날씨 데이터 추가
    try:
        weather_res = requests.get("https://search.naver.com/search.naver?query=전국+내일+날씨", headers=headers)
        w_soup = BeautifulSoup(weather_res.text, "html.parser")
        w_info = w_soup.select_one('.api_subject_bx')
        weather_text = w_info.text[:500] if w_info else "내일 전국은 맑고 일교차가 클 것으로 예상됩니다."
        
        news_data.append({
            "category": "날씨",
            "title": "내일의 날씨",
            "content": f"날씨 정보: {weather_text}",
            "image_url": "",
            "url": ""
        })
        print(f"    [날씨] 데이터 수집 완료")
    except Exception as e:
        print(f"    [날씨] 수집 실패: {e}")
        
    return news_data


def get_am_news_data():
    """오전(AM): 실생활·경제·시사 팩트 주제 발굴을 위해 경제/사회/IT 중심 뉴스 수집"""
    print("  -> [오전/AM] 실생활·경제·시사 뉴스 수집 중...")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Safari/537.36"
    }
    am_data = []
    
    # 1. 네이버 경제, 사회, IT 분야의 주요 기사 다수 수집
    sections = {
        "경제": "101",
        "사회": "102",
        "IT/과학": "105"
    }
    for category, sid in sections.items():
        url = f"https://news.naver.com/section/{sid}"
        try:
            res = requests.get(url, headers=headers, timeout=8)
            if res.status_code == 200:
                soup = BeautifulSoup(res.text, "html.parser")
                titles = soup.select('.sa_text_title')[:3]  # 상위 3개씩 수집
                for t in titles:
                    text = t.text.strip()
                    href = t.get('href', '')
                    if text:
                        am_data.append({
                            "category": category,
                            "title": text,
                            "content": text,
                            "url": href
                        })
        except Exception as e:
            print(f"    [{category}] AM 수집 오류: {e}")

    # 2. 구글 뉴스 경제/재테크/생활 트렌드 보강
    queries = [
        ("경제", "기준금리+환율+부동산+물가+when:1d"),
        ("생활", "지원금+제도+세금+건강보험+when:2d"),
        ("테크", "스마트폰+AI+신기술+when:2d")
    ]
    for cat, query in queries:
        try:
            rss_url = f"https://news.google.com/rss/search?q={query}&hl=ko&gl=KR&ceid=KR:ko"
            r_res = requests.get(rss_url, headers=headers, timeout=8)
            r_soup = BeautifulSoup(r_res.text, "xml" if "xml" in r_res.text[:100] else "html.parser")
            for item in r_soup.find_all("item")[:2]:
                t_elem = item.find("title")
                l_elem = item.find("link")
                if t_elem:
                    am_data.append({
                        "category": cat,
                        "title": t_elem.text.strip(),
                        "content": t_elem.text.strip(),
                        "url": l_elem.text.strip() if l_elem else ""
                    })
        except Exception:
            pass

    if not am_data:
        return get_naver_headlines()
    return am_data


def get_pm_viral_data():
    """오후(PM): 도파민 썰, 상식 파괴, 역사·과학 비하인드 토픽 수집"""
    print("  -> [오후/PM] 도파민 썰 & 기상천외 토픽 소스 수집 중...")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Safari/537.36"
    }
    pm_data = []

    # 1. 네이버 세계 토픽 및 이색 사건
    try:
        url = "https://news.naver.com/section/104"
        res = requests.get(url, headers=headers, timeout=8)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, "html.parser")
            for t in soup.select('.sa_text_title')[:4]:
                txt = t.text.strip()
                if txt:
                    pm_data.append({
                        "category": "세계이슈",
                        "title": txt,
                        "content": txt,
                        "url": t.get('href', '')
                    })
    except Exception as e:
        print(f"    네이버 세계 섹션 수집 오류: {e}")

    # 2. 구글 뉴스 기상천외 / 미스터리 / 역사 비하인드 검색
    pm_queries = [
        ("미스터리", "미스터리+발견+충격+when:7d"),
        ("역사/사건", "황당+사건+비하인드+when:7d"),
        ("과학/우주", "우주+블랙홀+신체+비밀+when:7d")
    ]
    for cat, query in pm_queries:
        try:
            rss_url = f"https://news.google.com/rss/search?q={query}&hl=ko&gl=KR&ceid=KR:ko"
            r_res = requests.get(rss_url, headers=headers, timeout=8)
            r_soup = BeautifulSoup(r_res.text, "xml" if "xml" in r_res.text[:100] else "html.parser")
            for item in r_soup.find_all("item")[:2]:
                t_elem = item.find("title")
                l_elem = item.find("link")
                if t_elem:
                    pm_data.append({
                        "category": cat,
                        "title": t_elem.text.strip(),
                        "content": t_elem.text.strip(),
                        "url": l_elem.text.strip() if l_elem else ""
                    })
        except Exception:
            pass

    # 3. 만약 실시간 소스가 부족할 경우 시청률 보장 에버그린 도파민 시드 풀 결합
    evergreen_pm_seeds = [
        {"category": "역사", "title": "쥐 잡으라고 포상금 줬더니 쥐를 사육해버린 하노이 쥐 덫 사건 (코브라 효과)", "content": "식민지 시절 프랑스가 쥐 꼬리를 가져오면 돈을 주자 사람들이 쥐 농장을 만들어 꼬리만 자르고 방생한 역사적 삽질"},
        {"category": "과학", "title": "만약 인간이 번개에 직격으로 맞으면 신체 내부 혈관에 생기는 일", "content": "리히텐베르크 형상과 적혈구 파괴 등 번개 피격 시 체내에서 벌어지는 기괴한 물리 화학적 현상"},
        {"category": "기업", "title": "코카콜라가 100년 만에 출시했다가 3개월 만에 폐기한 역대급 흑역사 뉴코크", "content": "블라인드 테스트 1위였지만 소비자들의 집단 분노로 철회된 마케팅 사상 최대의 역설"},
        {"category": "우주", "title": "만약 태양이 내일 아침 1초 만에 사라진다면 지구는 어떻게 될까", "content": "8분 20초간의 착각, 중력 탈출과 지구의 우주 방랑, 극한의 동결 시뮬레이션"},
        {"category": "인체", "title": "물에 빠졌을 때 몸 안의 후두 경련과 폐에서 벌어지는 1분의 진실", "content": "익사 직전 인체가 산소를 지키기 위해 자동으로 기도를 닫아버리는 무서운 생존 메커니즘"}
    ]
    pm_data.extend(evergreen_pm_seeds)

    return pm_data


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    print("=== AM DATA ===")
    print(json.dumps(get_am_news_data()[:3], ensure_ascii=False, indent=2))
    print("=== PM DATA ===")
    print(json.dumps(get_pm_viral_data()[:3], ensure_ascii=False, indent=2))

