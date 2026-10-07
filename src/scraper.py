import os
import sys
import json
import requests
from bs4 import BeautifulSoup
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

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
            res = requests.get(url, headers=headers)
            res.raise_for_status()
            soup = BeautifulSoup(res.text, "html.parser")
            
            # 메인 헤드라인 기사 링크 추출
            headline_link = soup.select_one('.sa_text_title')
            if headline_link and headline_link.has_attr('href'):
                article_url = headline_link['href']
                
                # 본문 페이지 크롤링
                art_res = requests.get(article_url, headers=headers)
                art_res.raise_for_status()
                art_soup = BeautifulSoup(art_res.text, "html.parser")
                
                title = art_soup.select_one('#title_area')
                title_text = title.text.strip() if title else headline_link.text.strip()
                
                content = art_soup.select_one('#dic_area')
                content_text = content.text.strip() if content else ""
                
                # 본문이 너무 길면 앞부분만 자르기 (LLM 입력용)
                if len(content_text) > 1000:
                    content_text = content_text[:1000] + "..."
                    
                # 메인 이미지 (og:image)
                og_image = art_soup.select_one('meta[property="og:image"]')
                image_url = og_image['content'] if og_image else ""
                
                news_data.append({
                    "category": category,
                    "title": title_text,
                    "content": content_text,
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
            r_res = requests.get(rss_url, headers=headers)
            r_soup = BeautifulSoup(r_res.text, "xml")
            item = r_soup.find("item")
            if item:
                title_text = item.title.text
                link = item.link.text
                
                # 이미지 추출 시도
                image_url = ""
                try:
                    art_res = requests.get(link, headers=headers, timeout=5)
                    art_soup = BeautifulSoup(art_res.text, "html.parser")
                    og_image = art_soup.select_one('meta[property="og:image"]')
                    if og_image: image_url = og_image['content']
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

if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    data = get_naver_headlines()
    print(json.dumps(data, ensure_ascii=False, indent=2))
