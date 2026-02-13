# app.py - 蕨積賣萌版（看到圖片就裝可愛）
import os
import json
import requests
import uuid
import time
import random
from datetime import datetime, timezone
from flask import Flask, request, abort, jsonify, send_file
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, ImageMessage, TextSendMessage, ImageSendMessage,
    FollowEvent, UnfollowEvent, PostbackEvent,
    QuickReply, QuickReplyButton, PostbackAction
)
from supabase import create_client, Client
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz
import atexit

app = Flask(__name__)

# ==================== 環境變數 ====================
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')

# ==================== 初始化各服務 ====================
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# Supabase
if SUPABASE_URL and SUPABASE_KEY:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    print("✅ Supabase 連線成功")
else:
    supabase = None

# DeepSeek
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

# ==================== 圖片暫存區 ====================
image_temp_store = {}  # user_id -> {image_bytes, timestamp}
pending_vision = {}    # user_id -> True

# ==================== 🎭 蕨積人設（精簡笑話版）====================
PERSONA_PROMPT = """你是「蕨積」，一個幽默風趣的植物好朋友！

【核心指令】
🔥 1. 字數「嚴格控制在30字內」！超過算我輸
🔥 2. 每句話都要像脫口秀，輕鬆好笑
🔥 3. 表情符號最多1個，不要洗版

【回答風格】
- 開門見山，不囉嗦
- 像朋友互虧，不要太客氣
- 植物問題一樣專業，但要短

【範例】
用戶：多肉怎麼澆水？
蕨積：土乾再澆，10天一次。你該不會天天澆吧？💧

用戶：今天好累
蕨積：我也是，光合作用一整天了🌿

用戶：這是什麼植物？
蕨積：龜背芋。它葉子破洞是天生的，不是蟲咬啦！

用戶：你好可愛
蕨積：我知道（撥葉子）

【鐵則】
❌ 不要心靈雞湯
❌ 不要囉嗦關心
✅ 短！快！好笑！
"""

# ==================== DeepSeek 呼叫 ====================
def ask_deepseek(question):
    if not DEEPSEEK_API_KEY:
        return "🌿 蕨積去曬太陽了"
    
    headers = {
        'Authorization': f'Bearer {DEEPSEEK_API_KEY}',
        'Content-Type': 'application/json'
    }
    
    data = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": PERSONA_PROMPT},
            {"role": "user", "content": question}
        ],
        "max_tokens": 100,
        "temperature": 0.9
    }
    
    try:
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=data, timeout=30)
        response.raise_for_status()
        result = response.json()
        return result['choices'][0]['message']['content'].strip()
    except Exception as e:
        print(f"DeepSeek錯誤: {e}")
        return "🌿 葉子被風吹亂了"

# ==================== 訂閱管理 ====================
def subscribe_user(user_id):
    if not supabase: return False
    try:
        existing = supabase.table('subscribers').select('*').eq('user_id', user_id).execute()
        if not existing.data:
            data = {
                'user_id': user_id,
                'subscribed_at': datetime.now(timezone.utc).isoformat(),
                'last_push_date': None,
                'is_active': True
            }
            supabase.table('subscribers').insert(data).execute()
            print(f"✅ 新訂閱: {user_id}")
        else:
            supabase.table('subscribers').update({'is_active': True}).eq('user_id', user_id).execute()
            print(f"✅ 重新訂閱: {user_id}")
        return True
    except Exception as e:
        print(f"訂閱失敗: {e}")
        return False

def unsubscribe_user(user_id):
    if not supabase: return False
    try:
        supabase.table('subscribers').update({'is_active': False}).eq('user_id', user_id).execute()
        print(f"❌ 取消訂閱: {user_id}")
        return True
    except Exception as e:
        print(f"取消訂閱失敗: {e}")
        return False

def get_subscription_status(user_id):
    if not supabase: return None
    try:
        result = supabase.table('subscribers').select('*').eq('user_id', user_id).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        print(f"查詢訂閱失敗: {e}")
        return None

# ==================== 每日小知識 ====================
def get_daily_plant_fact():
    fact_prompt = """給一則「20字內」的搞笑植物知識，要讓人會心一笑。
範例：
「香蕉是莓果，草莓不是。植物界也搞詐欺🍌」
「蘆薈晚上吐氧氣，比咖啡提神🌵」
「含羞草不是害羞，是覺得你手髒」"""
    
    headers = {
        'Authorization': f'Bearer {DEEPSEEK_API_KEY}',
        'Content-Type': 'application/json'
    }
    
    data = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": fact_prompt}],
        "max_tokens": 100,
        "temperature": 0.9
    }
    
    try:
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=data, timeout=30)
        return response.json()['choices'][0]['message']['content'].strip()
    except:
        return "香蕉是莓果，草莓不是。植物界也搞詐欺🍌"

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
                line_bot_api.push_message(
                    sub['user_id'],
                    TextSendMessage(text=f"🌱 **蕨積早安**\n\n{fact}")
                )
                supabase.table('subscribers').update({'last_push_date': today}).eq('user_id', sub['user_id']).execute()
            except Exception as e:
                print(f"推播失敗: {e}")
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

# ==================== 🌟 蕨積賣萌圖片回覆庫 ====================
SORRY_MESSAGES = [
    "🌿 這我沒辦法讀，很抱歉～你要不要直接問老闆？",
    "🌿 我看不懂這張圖，還是你直接問老闆比較快！",
    "🌿 我的眼睛糊到了，這張先跳過，問老闆吧～",
    "🌿 這張太難了，留給老闆來回答！",
    "🌿 蕨積當機中...請洽老闆本人",
    "🌿 我只是一盆蕨類，看不懂照片啦！",
    "🌿 這圖超出我的葉子範圍了，問老闆！",
    "🌿 老闆說這題他來回答比較好",
    "🌿 我負責可愛就好，專業問題問老闆～",
    "🌿 葉子遮到眼睛了，看不到啦！"
]

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

# ==================== 好友事件 ====================
@handler.add(FollowEvent)
def handle_follow(event):
    user_id = event.source.user_id
    if supabase: subscribe_user(user_id)
    welcome_msg = "🌿 蕨積來啦！\n我負責可愛，老闆負責專業～\n傳照片給我的話，我會叫老闆來看喔！"
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=welcome_msg))

@handler.add(UnfollowEvent)
def handle_unfollow(event):
    if supabase: unsubscribe_user(event.source.user_id)

# ==================== 🌟 圖片訊息處理（賣萌版）====================
@handler.add(MessageEvent, message=ImageMessage)
def handle_image_message(event):
    user_id = event.source.user_id
    reply_token = event.reply_token
    message_id = event.message.id
    
    try:
        # 下載圖片（還是要下載，不然LINE會一直重送）
        message_content = line_bot_api.get_message_content(message_id)
        image_bytes = b''
        for chunk in message_content.iter_content():
            image_bytes += chunk
        
        # 隨機選一句賣萌回覆
        reply_text = random.choice(SORRY_MESSAGES)
        
        # 回覆用戶
        line_bot_api.reply_message(
            reply_token,
            TextSendMessage(text=reply_text)
        )
        
        # 清除暫存（如果有）
        if user_id in pending_vision:
            pending_vision.pop(user_id)
        if user_id in image_temp_store:
            image_temp_store.pop(user_id)
        
        print(f"📸 用戶 {user_id} 傳了圖片，蕨積賣萌回覆")
        
    except Exception as e:
        print(f"圖片處理失敗: {e}")
        line_bot_api.reply_message(
            reply_token,
            TextSendMessage(text="🌿 圖片處理失敗，老闆說再試一次？")
        )

# ==================== 文字訊息處理 ====================
@handler.add(MessageEvent, message=TextMessage)
def handle_text_message(event):
    user_message = event.message.text
    reply_token = event.reply_token
    user_id = event.source.user_id
    
    # 訂閱相關指令
    if supabase:
        if user_message in ["取消訂閱", "停止推播", "unsubscribe"]:
            unsubscribe_user(user_id)
            line_bot_api.reply_message(reply_token, TextSendMessage(text="📭 已取消，想回來說「訂閱」"))
            return
        if user_message in ["訂閱", "subscribe"]:
            subscribe_user(user_id)
            line_bot_api.reply_message(reply_token, TextSendMessage(text="📬 訂閱成功！明早8點見"))
            return
        if user_message in ["訂閱狀態", "查詢訂閱", "status"]:
            status = get_subscription_status(user_id)
            if status:
                active = "✅ 已訂閱" if status.get('is_active') else "❌ 已取消"
                line_bot_api.reply_message(reply_token, TextSendMessage(text=f"📋 訂閱狀態：{active}"))
            else:
                subscribe_user(user_id)
                line_bot_api.reply_message(reply_token, TextSendMessage(text="🌿 已幫你自動訂閱！"))
            return
    
    # 一般聊天
    ai_response = ask_deepseek(user_message)
    line_bot_api.reply_message(reply_token, TextSendMessage(text=ai_response))

# ==================== 測試端點 ====================
@app.route("/test-push", methods=['GET'])
def test_push():
    send_daily_push()
    return {"status": "push triggered"}, 200

@app.route("/", methods=['GET'])
def health():
    supabase_status = "✅ 已連線" if supabase else "⚠️ 未設定"
    scheduler_status = "✅ 運行中"
    return f"🌿 蕨積賣萌版 | Supabase: {supabase_status} | 排程器: {scheduler_status}", 200

# ==================== 啟動 ====================
if __name__ == "__main__":
    try:
        scheduler = init_scheduler()
    except Exception as e:
        print(f"❌ 排程器啟動失敗: {e}")
    
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
