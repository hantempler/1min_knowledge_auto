import os
import sys
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

SCOPES = ['https://www.googleapis.com/auth/youtube.upload']

def get_youtube_service():
    creds = None
    token_path = os.path.join(config.CONFIG_DIR, 'youtube_token.json')
    client_secrets_path = os.path.join(config.CONFIG_DIR, 'client_secret_1.json')
    
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(client_secrets_path):
                print(f"Error: {client_secrets_path} 파일이 없습니다.")
                return None
            flow = InstalledAppFlow.from_client_secrets_file(client_secrets_path, SCOPES)
            creds = flow.run_local_server(port=0)
            
        with open(token_path, 'w') as token:
            token.write(creds.to_json())
            
    return build('youtube', 'v3', credentials=creds)

def upload_video(
    video_path: str,
    title: str,
    description: str,
    tags: list = None,
    privacy_status: str = "private",
    publish_at: str = None
) -> str:
    if not os.path.exists(video_path):
        print(f"Error: 업로드할 영상이 없습니다. ({video_path})")
        return None
        
    youtube = get_youtube_service()
    if not youtube:
        return None
        
    print(f"[YouTube] '{title}' 업로드 중...")
    
    upload_tags = tags if (tags and isinstance(tags, list)) else ['1분상식', '상식', '쇼츠', '이슈', '지식']
    
    # 예약 발행(publishAt) 시 유튜브 정책상 privacyStatus는 무조건 'private'이어야 함
    actual_privacy = "private" if publish_at else privacy_status
    status_dict = {
        'privacyStatus': actual_privacy,
        'selfDeclaredMadeForKids': False
    }
    if publish_at:
        status_dict['publishAt'] = publish_at
        print(f"  ⏰ [YouTube 예약 발행 설정] UTC: {publish_at} (KST 19:00 공개 예정)")

    body = {
        'snippet': {
            'title': title,
            'description': description,
            'tags': upload_tags,
            'categoryId': '27' # Education
        },
        'status': status_dict
    }
    
    media = MediaFileUpload(video_path, mimetype='video/mp4', resumable=True)
    
    try:
        request = youtube.videos().insert(
            part='snippet,status',
            body=body,
            media_body=media
        )
        response = request.execute()
        url = f"https://youtu.be/{response['id']}"
        print(f"[YouTube] 업로드 완료! {url}")
        return url
    except Exception as e:
        print(f"[YouTube] 업로드 실패: {e}")
        return None

if __name__ == "__main__":
    import argparse
    import json
    import datetime
    from zoneinfo import ZoneInfo
    from script_gen import generate_youtube_metadata

    parser = argparse.ArgumentParser(description="Step 6: 유튜브 쇼츠 업로더")
    parser.add_argument("--date", type=str, default=datetime.datetime.now().strftime("%Y-%m-%d"), help="대상 일자 (YYYY-MM-DD)")
    parser.add_argument("--mode", type=str, default="auto", choices=["auto", "public", "private"], help="발행 모드 (auto: 19시 이전 당일 19시 예약, 이후 즉시공개)")
    parser.add_argument("--schedule-hour", type=int, default=19, help="예약 공개 시간 (KST 기준 시)")
    args = parser.parse_args()

    clean_d = args.date.replace("-", "")
    script_file = os.path.join(config.DATA_DIR, f"script_{clean_d}.json")
    topic_file = os.path.join(config.DATA_DIR, f"topic_selection_{clean_d}.json")
    video_file = os.path.join(config.DATA_DIR, args.date, f"{args.date}.mp4")

    if not os.path.exists(video_file):
        video_file = os.path.join(config.DATA_DIR, args.date, "final_shorts.mp4")

    if not os.path.exists(video_file):
        print(f"Error: 렌더링된 비디오 파일이 없습니다 ({video_file})")
        sys.exit(1)

    t_info = json.load(open(topic_file, "r", encoding="utf-8")) if os.path.exists(topic_file) else {}
    s_data = json.load(open(script_file, "r", encoding="utf-8")) if os.path.exists(script_file) else {}

    yt_meta = generate_youtube_metadata(s_data, t_info, bgm_name="Beyond - Patrick Patrikios.mp3")
    yt_title = yt_meta.get("title") or yt_meta.get("youtube_title") or f"{t_info.get('shorts_title', '1분 상식')} #shorts"
    yt_desc = yt_meta.get("description") or yt_meta.get("youtube_description") or ""
    yt_tags = yt_meta.get("tags") or yt_meta.get("youtube_tags") or ["1분상식", "쇼츠"]

    now_kst = datetime.datetime.now(ZoneInfo("Asia/Seoul"))
    target_kst = now_kst.replace(hour=args.schedule_hour, minute=0, second=0, microsecond=0)

    if args.mode == "public":
        privacy_status = "public"
        publish_at_utc = None
        scheduled_str = None
        print("  📢 [발행 모드] 즉시 전체 공개 (public)")
    elif args.mode == "private":
        privacy_status = "private"
        publish_at_utc = None
        scheduled_str = None
        print("  🔒 [발행 모드] 비공개 (private)")
    else:
        # auto 모드
        if now_kst < target_kst:
            privacy_status = "private"
            target_utc = target_kst.astimezone(ZoneInfo("UTC"))
            publish_at_utc = target_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")
            scheduled_str = target_kst.strftime("%Y-%m-%d %H:%M:%S")
            print(f"  ⏰ [발행 모드] 골든타임 예약: {scheduled_str} KST")
        else:
            privacy_status = "public"
            publish_at_utc = None
            scheduled_str = None
            print("  📢 [발행 모드] 19시 경과 -> 즉시 전체 공개 (public)")

    res_url = upload_video(
        video_path=video_file,
        title=yt_title,
        description=yt_desc,
        tags=yt_tags,
        privacy_status=privacy_status,
        publish_at=publish_at_utc
    )

    if res_url:
        print(f"\n🎉 [성공] 유튜브 업로드 완료: {res_url}")
        if scheduled_str:
            print(f"   공개 예정 시간: {scheduled_str} KST")
    else:
        print("\n❌ [실패] 유튜브 업로드 실패")
        sys.exit(1)
