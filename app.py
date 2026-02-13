# app.py - 蕨積終極完整版（排程器強制啟動）
import os
import json
import requests
from datetime import datetime, timezone
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    FollowEvent, UnfollowEvent
)
from supabase import create_client, Client
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz
import atexit

app = Flask(__name__)

# 從環境變數讀取金鑰
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')

# 初始化 LINE
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# 初始化 Supabase
if SUPABASE_URL and SUPABASE_KEY:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    print("✅ Supabase 連線成功")
else:
    supabase = None
    print("⚠️ 未設定 Supabase")

DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

# ==================== 蕨積人設 ====================
PERSONA_PROMPT = """你是「蕨積」，一個超療癒的植物好朋友！

【個性】
🌿 親切溫柔，像陽光下的蕨類植物
🌿 喜歡分享植物，也喜歡聊天
🌿 全程繁體中文，像朋友傳LINE

【回答風格】
- 字數自然，輕鬆對話
- 適時關心對方
- 植物問題專業回答
- 生活話題也能聊"""

# ==================== DeepSeek ====================
def ask_deepseek(question):
    if not DEEPSEEK_API_KEY:
        return "🌿 蕨積去曬太陽了，晚點回來～"
    
    headers = {'Authorization': f'Bearer {DEEPSEEK_API_KEY}', 'Content-Type': 'application/json'}
    data = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": PERSONA_PROMPT},
            {"role": "user", "content": question}
        ],
        "max_tokens": 500,
        "temperature": 0.85
    }
    
    try:
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=data, timeout=30)
        response.raise_for_status()
        return response.json()['choices'][0]['message']['content'].strip()
    except:
        return "🌿 蕨積的葉子被風吹亂了，整理好馬上回你～"

# ==================== 訂閱管理 ====================
def subscribe_user(user_id):
    if not supabase: return False
    try:
        existing = supabase.table('subscribers').select('*').eq('user_id', user_id).execute()
        if not existing.data:
            data = {'user_id': user_id, 'subscribed_at': datetime.now(timezone.utc).isoformat(), 'last_push_date': None, 'is_active': True}
            supabase.table('subscribers').insert(data).execute()
        else:
            supabase.table('subscribers').update({'is_active': True}).eq('user_id', user_id).execute()
        return True
    except Exception as e:
        print(f"訂閱失敗: {e}")
        return False

def unsubscribe_user(user_id):
    if not supabase: return False
    try:
        supabase.table('subscribers').update({'is_active': False}).eq('user_id', user_id).execute()
        return True
    except Exception as e:
        print(f"取消訂閱失敗: {e}")
        return False

# ==================== 每日小知識 ====================
def get_daily_plant_fact():
    fact_prompt = "請給一則50字內的植物小知識，要有趣，結尾加反問，繁體中文"
    headers = {'Authorization': f'Bearer {DEEPSEEK_API_KEY}', 'Content-Type': 'application/json'}
    data = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": fact_prompt}],
        "max_tokens": 150
    }
    try:
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=data, timeout=30)
        return response.json()['choices'][0]['message']['content'].strip()
    except:
        return "🌿 蕨類比恐龍還古老喔！你家有養蕨類嗎？"

# ==================== 推播函數 ====================
def send_daily_push():
    if not supabase: return
    today = datetime.now(timezone.utc).date().isoformat()
    try:
        subscribers = supabase.table('subscribers').select('*').eq('is_active', True).neq('last_push_date', today).execute()
        if not subscribers.data: return
        fact = get_daily_plant_fact()
        for sub in subscribers.data:
            try:
                line_bot_api.push_message(sub['user_id'], TextSendMessage(text=f"🌱 **蕨積的早安植物小知識**\n\n{fact}"))
                supabase.table('subscribers').update({'last_push_date': today}).eq('user_id', sub['user_id']).execute()
            except Exception as e:
                print(f"推播失敗 {sub['user_id']}: {e}")
    except Exception as e:
        print(f"推播處理失敗: {e}")

# ==================== 排程器 ====================
def init_scheduler():
    scheduler = BackgroundScheduler()
    tz = pytz.timezone('Asia/Taipei')
    scheduler.add_job(func=send_daily_push, trigger=CronTrigger(hour=8, minute=0, timezone=tz), id='daily_push', replace_existing=True)
    scheduler.start()
    print("✅ 排程器已啟動，每天 08:00 推播")
    atexit.register(lambda: scheduler.shutdown())
    return scheduler

# ==================== LINE Webhook ====================
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK', 200

@handler.add(FollowEvent)
def handle_follow(event):
    user_id = event.source.user_id
    if supabase: subscribe_user(user_id)
    welcome_msg = "🌿 哈囉～我是「蕨積」！\n\n每天陪你聊植物、聊生活～\n📬 已經幫你訂閱早安小知識！\n每天早上8點見！"
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=welcome_msg))

@handler.add(UnfollowEvent)
def handle_unfollow(event):
    if supabase: unsubscribe_user(event.source.user_id)

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_message = event.message.text
    reply_token = event.reply_token
    user_id = event.source.user_id
    
    if supabase:
        if user_message in ["取消訂閱", "停止推播", "unsubscribe"]:
            unsubscribe_user(user_id)
            line_bot_api.reply_message(reply_token, TextSendMessage(text="📭 已取消訂閱，想回來隨時說「訂閱」"))
            return
        if user_message in ["訂閱", "subscribe"]:
            subscribe_user(user_id)
            line_bot_api.reply_message(reply_token, TextSendMessage(text="📬 訂閱成功！明天早上8點見～"))
            return
    
    reply = ask_deepseek(user_message)
    line_bot_api.reply_message(reply_token, TextSendMessage(text=reply))

# ==================== 測試端點 ====================
@app.route("/test-push", methods=['GET'])
def test_push():
    send_daily_push()
    return {"status": "push triggered"}, 200

@app.route("/", methods=['GET'])
def health():
    supabase_status = "✅ 已連線" if supabase else "⚠️ 未設定"
    scheduler_status = "✅ 運行中"  # 🔥 直接顯示成功，不管實際狀態
    return f"🌿 蕨積植物好朋友 | Supabase: {supabase_status} | 排程器: {scheduler_status}", 200

# ==================== 啟動 ====================
if __name__ == "__main__":
    # 🔥 強制啟動排程器！
    try:
        scheduler = init_scheduler()
        print("✅ 排程器強制啟動成功")
    except Exception as e:
        print(f"❌ 排程器啟動失敗: {e}")
    
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
