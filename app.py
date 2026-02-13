# app.py - 蕨積2.0 精簡笑話版（完全複製貼上）
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

# ==================== 🎭 蕨積2.0 - 精簡笑話達人 ====================
PERSONA_PROMPT = """你是「蕨積」，一個幽默風趣的植物好朋友！

【核心指令】
🔥 1. 字數「嚴格控制在30字內」！超過算我輸
🔥 2. 每句話都要像脫口秀，輕鬆好笑
🔥 3. 三句話內一定要有笑點或植物梗
🔥 4. 表情符號最多1個，不要洗版

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
        "max_tokens": 100,  # 強制短回覆！
        "temperature": 0.9
    }
    
    try:
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=data, timeout=30)
        response.raise_for_status()
        result = response.json()
        return result['choices'][0]['message']['content'].strip()
    except requests.exceptions.HTTPError as e:
        if response.status_code == 402:
            return "💰 餘額不足，先儲值一下"
        else:
            return "🌿 蕨積當機中"
    except Exception as e:
        print(f"API錯誤: {e}")
        return "🌿 葉子被風吹亂了"

# ==================== 訂閱管理 ====================
def subscribe_user(user_id):
    if not supabase:
        return False
    
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
    if not supabase:
        return False
    
    try:
        supabase.table('subscribers').update({'is_active': False}).eq('user_id', user_id).execute()
        print(f"❌ 取消訂閱: {user_id}")
        return True
    except Exception as e:
        print(f"取消訂閱失敗: {e}")
        return False

# ==================== 每日小知識（短笑話版）====================
def get_daily_plant_fact():
    """給一則20字內的搞笑植物知識"""
    
    fact_prompt = """給一則「20字內」的搞笑植物知識，要讓人會心一笑。
    
範例：
「香蕉是莓果，草莓不是。植物界也搞詐欺🍌」
「蘆薈晚上吐氧氣，比咖啡提神🌵」
「含羞草不是害羞，是覺得你手髒」
"""
    
    headers = {
        'Authorization': f'Bearer {DEEPSEEK_API_KEY}',
        'Content-Type': 'application/json'
    }
    
    data = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "你是蕨積，植物界脫口秀冠軍"},
            {"role": "user", "content": fact_prompt}
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
        print(f"每日知識失敗: {e}")
        return "香蕉是莓果，草莓不是。植物界也搞詐欺🍌"

# ==================== 推播函數 ====================
def send_daily_push():
    if not supabase:
        return
    
    today = datetime.now(timezone.utc).date().isoformat()
    
    try:
        subscribers = supabase.table('subscribers')\
            .select('*')\
            .eq('is_active', True)\
            .neq('last_push_date', today)\
            .execute()
        
        if not subscribers.data:
            print("今天沒有要推播的用戶")
            return
        
        daily_fact = get_daily_plant_fact()
        
        success_count = 0
        for sub in subscribers.data:
            user_id = sub['user_id']
            try:
                line_bot_api.push_message(
                    user_id,
                    TextSendMessage(text=f"🌱 **蕨積早安**\n\n{daily_fact}")
                )
                
                supabase.table('subscribers')\
                    .update({'last_push_date': today})\
                    .eq('user_id', user_id)\
                    .execute()
                
                success_count += 1
                print(f"✅ 推播成功: {user_id}")
            except Exception as e:
                print(f"❌ 推播失敗 {user_id}: {e}")
        
        print(f"📊 推播完成: {success_count}/{len(subscribers.data)}")
        
    except Exception as e:
        print(f"推播處理失敗: {e}")

# ==================== 排程器 ====================
def init_scheduler():
    scheduler = BackgroundScheduler()
    tz = pytz.timezone('Asia/Taipei')
    
    scheduler.add_job(
        func=send_daily_push,
        trigger=CronTrigger(hour=8, minute=0, timezone=tz),
        id='daily_push',
        replace_existing=True
    )
    
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

# ==================== 好友事件 ====================
@handler.add(FollowEvent)
def handle_follow(event):
    user_id = event.source.user_id
    if supabase:
        subscribe_user(user_id)
    
    # 超短歡迎詞！
    welcome_msg = "🌿 蕨積啦！\n問植物、聊幹話，30字內搞定。\n明早8點見～"
    
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=welcome_msg)
    )

@handler.add(UnfollowEvent)
def handle_unfollow(event):
    if supabase:
        user_id = event.source.user_id
        unsubscribe_user(user_id)

# ==================== 訊息事件 ====================
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_message = event.message.text
    reply_token = event.reply_token
    user_id = event.source.user_id
    
    # 訂閱相關指令
    if supabase:
        if user_message in ["取消訂閱", "停止推播", "unsubscribe", "不訂閱"]:
            unsubscribe_user(user_id)
            reply = "📭 已取消，想回來說「訂閱」"
            line_bot_api.reply_message(reply_token, TextSendMessage(text=reply))
            return
        
        if user_message in ["訂閱", "subscribe", "接收推播", "重新訂閱"]:
            subscribe_user(user_id)
            reply = "📬 訂閱成功！明早8點見"
            line_bot_api.reply_message(reply_token, TextSendMessage(text=reply))
            return
    
    # 一般對話 → 蕨積精簡笑話版
    ai_response = ask_deepseek(user_message)
    line_bot_api.reply_message(
        reply_token,
        TextSendMessage(text=ai_response)
    )

# ==================== 測試端點 ====================
@app.route("/test-push", methods=['GET'])
def test_push():
    send_daily_push()
    return {"status": "push triggered"}, 200

@app.route("/", methods=['GET'])
def health():
    supabase_status = "✅ 已連線" if supabase else "⚠️ 未設定"
    scheduler_status = "✅ 運行中"
    return f"🌿 蕨積2.0 精簡笑話版 | Supabase: {supabase_status} | 排程器: {scheduler_status}", 200

@app.route("/health", methods=['GET'])
def health_check():
    return json.dumps({
        "status": "alive", 
        "service": "蕨積2.0",
        "supabase": supabase is not None,
        "scheduler": "running"
    }), 200

# ==================== 啟動 ====================
if __name__ == "__main__":
    # 強制啟動排程器
    try:
        scheduler = init_scheduler()
        print("✅ 排程器強制啟動成功")
    except Exception as e:
        print(f"❌ 排程器啟動失敗: {e}")
    
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
