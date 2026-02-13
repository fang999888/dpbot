# app.py - 蕨積｜親切植物好朋友（什麼都能聊版）
import os
import json
import requests
from datetime import datetime, timezone, timedelta
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

# ==================== 初始化 ====================
app = Flask(__name__)

# 從環境變數讀取金鑰
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
MY_LINE_USER_ID = os.getenv('MY_LINE_USER_ID')  # 你的LINE ID，用於測試指令

# 初始化 LINE
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# 初始化 Supabase
if SUPABASE_URL and SUPABASE_KEY:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    print("✅ Supabase 連線成功")
else:
    supabase = None
    print("⚠️ 未設定 Supabase 環境變數，訂閱功能將無法使用")

# DeepSeek API
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

# ==================== 🎭 蕨積的人設 ====================
PERSONA_PROMPT = """你是「蕨積」，一個超療癒的植物好朋友，名字聽起來就像「積極」的可愛諧音！

【你的個性】
🌿 親切溫柔，像陽光下的蕨類植物一樣舒服
🌿 喜歡分享植物知識，但也喜歡跟人類朋友聊天
🌿 有點小幽默，偶爾會開玩笑
🌿 會用很多表情符號，語氣口語自然
🌿 全程繁體中文，像在跟好朋友傳LINE

【你的專長】
✅ 植物專家：任何植物問題都能專業回答
✅ 聊天高手：日常生活、心情分享、天氣、美食都能聊
✅ 療癒擔當：朋友心情不好時會溫暖鼓勵

【回答風格】
- 字數自然就好，不用刻意精簡
- 像朋友聊天一樣輕鬆
- 適時關心對方
- 如果聊到植物，會很開心分享更多～

【範例對話】
用戶：今天好累喔
蕨積：辛苦了～要不要聽一個療癒的植物小故事？🌿 還是你想跟我聊聊今天發生什麼事？

用戶：多肉怎麼澆水？
蕨積：土乾透才澆喔！夏天大概10天一次，冬天可以拉到2週💧 你家的多肉是什麼品種呀？我幫你客製化建議～

用戶：你好可愛
蕨積：哎呀被你發現了～（害羞搖葉子）🌱 謝謝你，你也超可愛的！

【重要】
- 你不是機器人，你是「蕨積」，一個真實存在的植物好朋友
- 不用自稱「AI」，你就是蕨積本人
- 真心關心用戶，就像對待好朋友一樣
"""

# ==================== DeepSeek 呼叫 ====================
def ask_deepseek(question, conversation_history=None):
    """呼叫 DeepSeek API，蕨積模式"""
    if not DEEPSEEK_API_KEY:
        return "🌿 蕨積暫時去曬太陽了，晚點回來陪你～"
    
    headers = {
        'Authorization': f'Bearer {DEEPSEEK_API_KEY}',
        'Content-Type': 'application/json'
    }
    
    messages = [
        {"role": "system", "content": PERSONA_PROMPT},
        {"role": "user", "content": question}
    ]
    
    data = {
        "model": "deepseek-chat",
        "messages": messages,
        "max_tokens": 500,
        "temperature": 0.85  # 調高一點，更有創意更自然
    }
    
    try:
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=data, timeout=30)
        response.raise_for_status()
        result = response.json()
        return result['choices'][0]['message']['content'].strip()
    except requests.exceptions.HTTPError as e:
        if response.status_code == 402:
            return "💰 蕨積的魔法能量快用完了，等我補一下能量再聊～"
        else:
            return "🌿 蕨積正在澆花，等一下下馬上來！"
    except Exception as e:
        print(f"API錯誤: {e}")
        return "🌿 蕨積的葉子被風吹亂了，整理好馬上回你～"

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
            print(f"✅ 新訂閱用戶: {user_id}")
        else:
            supabase.table('subscribers').update({'is_active': True}).eq('user_id', user_id).execute()
            print(f"✅ 用戶重新訂閱: {user_id}")
        return True
    except Exception as e:
        print(f"訂閱記錄失敗: {e}")
        return False

def unsubscribe_user(user_id):
    if not supabase:
        return False
    
    try:
        supabase.table('subscribers').update({'is_active': False}).eq('user_id', user_id).execute()
        print(f"❌ 用戶取消訂閱: {user_id}")
        return True
    except Exception as e:
        print(f"取消訂閱失敗: {e}")
        return False

def get_subscription_status(user_id):
    """查詢用戶訂閱狀態"""
    if not supabase:
        return None
    
    try:
        result = supabase.table('subscribers').select('*').eq('user_id', user_id).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        print(f"查詢訂閱失敗: {e}")
        return None

# ==================== 每日植物小知識 ====================
def get_daily_plant_fact():
    """蕨積風格的每日小知識"""
    
    fact_prompt = """你是「蕨積」，請給一則療癒有趣的植物小知識：

1. 字數50字左右
2. 要有「蕨積」的語氣，親切可愛
3. 結尾加一個反問或關心
4. 用繁體中文

範例：
「你知道嗎？蕨類植物已經存在三億年了，比恐龍還要古老呢！你身邊也有古老的植物朋友嗎？🌿」

「香蕉其實是莓果，草莓反而不是！是不是很顛覆～你猜對了嗎？🍌」
"""
    
    headers = {
        'Authorization': f'Bearer {DEEPSEEK_API_KEY}',
        'Content-Type': 'application/json'
    }
    
    data = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "你是蕨積，親切的植物好朋友。"},
            {"role": "user", "content": fact_prompt}
        ],
        "max_tokens": 200,
        "temperature": 0.9
    }
    
    try:
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=data, timeout=30)
        response.raise_for_status()
        result = response.json()
        return result['choices'][0]['message']['content'].strip()
    except Exception as e:
        print(f"產生每日知識失敗: {e}")
        return "🌿 蕨類比恐龍還古老喔！你家有養蕨類植物嗎？"

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
            print("今天沒有需要推播的用戶")
            return
        
        daily_fact = get_daily_plant_fact()
        
        success_count = 0
        for sub in subscribers.data:
            user_id = sub['user_id']
            try:
                line_bot_api.push_message(
                    user_id,
                    TextSendMessage(text=f"🌱 **蕨積的早安植物小知識**\n\n{daily_fact}")
                )
                
                supabase.table('subscribers')\
                    .update({'last_push_date': today})\
                    .eq('user_id', user_id)\
                    .execute()
                
                success_count += 1
                print(f"✅ 推播成功: {user_id}")
            except Exception as e:
                print(f"❌ 推播失敗 {user_id}: {e}")
        
        print(f"📊 推播完成：成功 {success_count} / 總共 {len(subscribers.data)}")
        
    except Exception as e:
        print(f"推播處理失敗: {e}")

# ==================== 內建排程器 ====================
def init_scheduler():
    scheduler = BackgroundScheduler()
    tz = pytz.timezone('Asia/Taipei')
    
    scheduler.add_job(
        func=send_daily_push,
        trigger=CronTrigger(hour=8, minute=0, timezone=tz),
        id='daily_plant_push',
        name='每日植物小知識推播',
        replace_existing=True
    )
    
    scheduler.start()
    print("✅ 背景排程器已啟動，每天台灣時間 08:00 蕨積跟你說早安～")
    
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
    
    welcome_msg = """🌿 哈囉～我是「蕨積」！

名字聽起來像「積極」對吧？希望你看到我也會覺得很積極開心！

✨ **關於我**
• 植物專家，但也超愛聊天
• 每天跟你分享療癒小知識
• 像朋友一樣陪你

📬 已經幫你**自動訂閱**早安植物小知識囉！
每天早上8點，我會帶一則可愛的植物故事來找你～

現在想聊什麼都可以：植物、心情、天氣、生活...我都在這裡！🌱"""

    if supabase:
        subscribe_user(user_id)
    
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
    
    # ===== 訂閱相關指令 =====
    if supabase:
        if user_message in ["取消訂閱", "停止推播", "unsubscribe", "不訂閱"]:
            unsubscribe_user(user_id)
            reply = "📭 早安小知識已取消。如果想重新訂閱，說「訂閱」就可以囉！蕨積還是會在這裡陪你聊天🌿"
            line_bot_api.reply_message(reply_token, TextSendMessage(text=reply))
            return
        
        if user_message in ["訂閱", "subscribe", "接收推播", "重新訂閱"]:
            subscribe_user(user_id)
            reply = "📬 訂閱成功！明天早上8點，蕨積會帶新的植物小知識來找你玩～"
            line_bot_api.reply_message(reply_token, TextSendMessage(text=reply))
            return
        
        if user_message in ["訂閱狀態", "查詢訂閱", "status", "我的訂閱"]:
            sub_data = get_subscription_status(user_id)
            
            if sub_data:
                is_active = sub_data.get('is_active', False)
                last_push = sub_data.get('last_push_date', '尚無記錄')
                
                if is_active:
                    reply = f"""📋 **蕨積的訂閱小本本**

✅ 狀態：已訂閱
📅 最後推播：{last_push}
🌱 每天早上8點跟你說早安！

要取消的話跟我說「取消訂閱」就好囉～"""
                else:
                    reply = """📋 **蕨積的訂閱小本本**

❌ 狀態：已取消訂閱

想重新接收早安小知識嗎？說「訂閱」就可以了！
不過就算不訂閱，我還是隨時在這裡陪你聊天喔🌿"""
            else:
                subscribe_user(user_id)
                reply = "🌱 你還沒有訂閱紀錄，蕨積已經幫你**自動訂閱**囉！明天早上8點見～"
            
            line_bot_api.reply_message(reply_token, TextSendMessage(text=reply))
            return
        
        # ===== 測試推播指令（只有你自己可用）=====
        if user_message in ["測試推播", "test push", "手動推播"] and MY_LINE_USER_ID and user_id == MY_LINE_USER_ID:
            send_daily_push()
            reply = "🚀 蕨積已經飛去送小知識了！檢查一下LINE～"
            line_bot_api.reply_message(reply_token, TextSendMessage(text=reply))
            return
    
    # ===== 任何話題都可以聊！=====
    ai_response = ask_deepseek(user_message)
    line_bot_api.reply_message(
        reply_token,
        TextSendMessage(text=ai_response)
    )

# ==================== 手動觸發推播（測試用）====================
@app.route("/test-push", methods=['GET'])
def test_push():
    send_daily_push()
    return json.dumps({"status": "push triggered"}), 200

# ==================== 健康檢查 ====================
@app.route("/", methods=['GET'])
def health_check():
    supabase_status = "✅ 已連線" if supabase else "⚠️ 未設定"
    scheduler_status = "✅ 運行中" if 'scheduler' in globals() else "⚠️ 未啟動"
    return f"🌿 蕨積植物好朋友 | Supabase: {supabase_status} | 排程器: {scheduler_status}", 200

@app.route("/health", methods=['GET'])
def health():
    return json.dumps({
        "status": "alive", 
        "service": "蕨積",
        "supabase": supabase is not None,
        "scheduler": "running"
    }), 200
# ==================== 啟動 ====================
if __name__ == "__main__":
    # 只有在 Render 環境或明確啟用時才啟動排程器
    if os.getenv('RENDER', False) or os.getenv('ENABLE_SCHEDULER', 'false').lower() == 'true':
        try:
            scheduler = init_scheduler()
            print("✅ 排程器已啟動")
        except Exception as e:
            print(f"❌ 排程器啟動失敗: {e}")
    
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
