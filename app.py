# app.py - 植物機器人 每日推播＋精簡互動版（完整可執行）
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

# ==================== 初始化 ====================
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
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# DeepSeek API
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

# ==================== 提示詞（精簡互動版）====================
PLANT_EXPERT_PROMPT = """你是一位風趣的植物達人，綽號「小植」。

**回答風格**：
- ✅ 字數**控制在50~100字以內**
- ✅ 開頭直接講重點，不用客套
- ✅ 結尾加一個**反問**，像朋友聊天
- ✅ 偶爾用 🌱🌿🌸🪴 表情符號

**範例**：
用戶：多肉怎麼澆水？
你：土乾透才澆！夏天大概10天1次，冬天2週1次💧
你家的多肉現在多久澆一次呀？

用戶：這是什麼植物？
你：看葉子應該是**龜背芋**，那種大洞洞是它的招牌喔！
你家也有養龜背芋嗎？🌿

**嚴格規則**：
- 非植物問題 → 「我只懂植物啦～問我花草樹木都可以唷🪴」
- 全程繁體中文
"""

# ==================== DeepSeek 呼叫 ====================
def ask_deepseek(question):
    if not DEEPSEEK_API_KEY:
        return "🌱 小植暫時休息中，請稍後再試～"
    
    headers = {
        'Authorization': f'Bearer {DEEPSEEK_API_KEY}',
        'Content-Type': 'application/json'
    }
    
    data = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "你是「小植」，風趣的植物達人。回答精簡、有互動感，全程繁體中文。"},
            {"role": "user", "content": f"{PLANT_EXPERT_PROMPT}\n\n用戶問題：{question}"}
        ],
        "max_tokens": 300,
        "temperature": 0.8
    }
    
    try:
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=data, timeout=30)
        response.raise_for_status()
        result = response.json()
        return result['choices'][0]['message']['content'].strip()
    except Exception as e:
        print(f"API錯誤: {e}")
        return "🌿 小植正在澆花，晚點回你喔～"

# ==================== 訂閱管理 ====================
def subscribe_user(user_id):
    """用戶加入好友或輸入「訂閱」時，記錄訂閱"""
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
            # 如果已存在但被取消訂閱，重新啟用
            supabase.table('subscribers').update({'is_active': True}).eq('user_id', user_id).execute()
            print(f"✅ 用戶重新訂閱: {user_id}")
    except Exception as e:
        print(f"訂閱記錄失敗: {e}")

def unsubscribe_user(user_id):
    """用戶輸入「取消訂閱」時，取消訂閱"""
    try:
        supabase.table('subscribers').update({'is_active': False}).eq('user_id', user_id).execute()
        print(f"❌ 用戶取消訂閱: {user_id}")
    except Exception as e:
        print(f"取消訂閱失敗: {e}")

# ==================== 每日植物小知識 ====================
def get_daily_plant_fact():
    """呼叫 DeepSeek 產生今日植物小知識（30~50字超精簡）"""
    
    fact_prompt = """請給一則**植物小知識**，要符合以下要求：
1. 字數**30~50字**，超精簡
2. 要有趣、冷門、讓人想分享
3. 結尾加一個反問或互動
4. 用繁體中文

範例：
「香蕉其實是莓果！草莓反而不是喔～你猜到了嗎？🍌」
「仙人掌晚上會釋放氧氣，很適合放臥室，你有養嗎？🌵」
"""
    
    headers = {
        'Authorization': f'Bearer {DEEPSEEK_API_KEY}',
        'Content-Type': 'application/json'
    }
    
    data = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "你是植物小學堂老師，給超簡短有趣的知識。"},
            {"role": "user", "content": fact_prompt}
        ],
        "max_tokens": 150,
        "temperature": 0.9
    }
    
    try:
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=data, timeout=30)
        response.raise_for_status()
        result = response.json()
        return result['choices'][0]['message']['content'].strip()
    except Exception as e:
        print(f"產生每日知識失敗: {e}")
        return "🌿 蘆薈晚上會釋放氧氣，很適合放臥室喔！你也有養蘆薈嗎？"

# ==================== 推播端點 ====================
@app.route("/cron/daily-push", methods=['GET'])
def cron_daily_push():
    """給 Render Cron Job 呼叫的端點（台灣早上8點 = UTC 0點）"""
    
    today = datetime.now(timezone.utc).date().isoformat()
    
    # 取得所有啟用訂閱且今天還沒推播的用戶
    subscribers = supabase.table('subscribers')\
        .select('*')\
        .eq('is_active', True)\
        .neq('last_push_date', today)\
        .execute()
    
    if not subscribers.data:
        print("今天沒有需要推播的用戶")
        return json.dumps({"status": "no_subscribers"}), 200
    
    # 產生今日小知識
    daily_fact = get_daily_plant_fact()
    
    success_count = 0
    for sub in subscribers.data:
        user_id = sub['user_id']
        try:
            line_bot_api.push_message(
                user_id,
                TextSendMessage(text=f"🌱 **今日植物小知識**\n\n{daily_fact}")
            )
            
            # 更新推播時間
            supabase.table('subscribers')\
                .update({'last_push_date': today})\
                .eq('user_id', user_id)\
                .execute()
            
            success_count += 1
            print(f"✅ 推播成功: {user_id}")
        except Exception as e:
            print(f"❌ 推播失敗 {user_id}: {e}")
    
    return json.dumps({"status": "success", "sent": success_count}), 200

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
    """用戶加入好友→自動訂閱"""
    user_id = event.source.user_id
    subscribe_user(user_id)
    
    welcome_msg = (
        "🌱 你好呀～我是「小植」！\n\n"
        "問我任何植物問題，我會簡短回答，像朋友聊天一樣～\n\n"
        "例如：\n"
        "• 多肉怎麼澆水？\n"
        "• 這是什麼植物？\n"
        "• 葉子變黃怎麼辦？\n\n"
        "📬 你已經**自動訂閱**每日植物小知識！\n"
        "每天早上8點會送你一則有趣的小知識～\n"
        "如果想取消，隨時跟我說「取消訂閱」就可以囉！"
    )
    
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=welcome_msg)
    )

@handler.add(UnfollowEvent)
def handle_unfollow(event):
    """用戶封鎖機器人→自動取消訂閱"""
    user_id = event.source.user_id
    unsubscribe_user(user_id)

# ==================== 訊息事件 ====================
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_message = event.message.text
    reply_token = event.reply_token
    user_id = event.source.user_id
    
    # 檢查是否為訂閱相關指令
    if user_message in ["取消訂閱", "停止推播", "unsubscribe", "不訂閱"]:
        unsubscribe_user(user_id)
        reply = "📭 已取消每日植物小知識。如果想重新訂閱，說「訂閱」就可以囉！"
        line_bot_api.reply_message(reply_token, TextSendMessage(text=reply))
        return
    
    if user_message in ["訂閱", "subscribe", "接收推播", "重新訂閱"]:
        subscribe_user(user_id)
        reply = "📬 訂閱成功！每天早上8點會收到植物小知識喔～"
        line_bot_api.reply_message(reply_token, TextSendMessage(text=reply))
        return
    
    # 一般問題 → 呼叫 DeepSeek
    ai_response = ask_deepseek(user_message)
    line_bot_api.reply_message(
        reply_token,
        TextSendMessage(text=ai_response)
    )

# ==================== 健康檢查 ====================
@app.route("/", methods=['GET'])
def health_check():
    return "🌱 植物機器人（每日推播＋精簡互動版）運行中", 200

@app.route("/health", methods=['GET'])
def health():
    return json.dumps({"status": "alive", "service": "plant-bot"}), 200

# ==================== 啟動 ====================
if __name__ == "__main__":
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
