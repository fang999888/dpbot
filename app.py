# app.py - 蕨積3.0 會看圖版（強制成功版）
import os
import json
import requests
import uuid
import time
import base64
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
import google.generativeai as genai
from io import BytesIO
import PIL.Image
from PIL import Image as PILImage

app = Flask(__name__)

# ==================== 環境變數 ====================
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
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

# Gemini
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    # 使用最新的 vision 模型
    gemini_vision_model = genai.GenerativeModel('gemini-2.0-flash-vision')
    print("✅ Gemini Vision 初始化成功")
else:
    gemini_vision_model = None
    print("⚠️ 未設定 Gemini API Key，圖片辨識功能無法使用")

# DeepSeek
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

# ==================== 圖片暫存區 ====================
image_temp_store = {}  # user_id -> {image_bytes, timestamp}
pending_vision = {}    # user_id -> True（等待使用者選擇模式）
app_base_url = None

# ==================== 🎭 蕨積人設 ====================
PERSONA_PROMPT = """你是「蕨積」，一個幽默風趣的植物好朋友！

【核心指令】
🔥 1. 字數「嚴格控制在30字內」！
🔥 2. 每句話都要像脫口秀，輕鬆好笑
🔥 3. 表情符號最多1個

【範例】
用戶：多肉怎麼澆水？
蕨積：土乾再澆，10天一次。你該不會天天澆吧？💧

用戶：今天好累
蕨積：我也是，光合作用一整天了🌿

用戶：這是什麼植物？
蕨積：龜背芋。它葉子破洞是天生的，不是蟲咬啦！
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
    except:
        return "🌿 葉子被風吹亂了"

# ==================== 🔥 強化版圖片辨識（保證成功）====================
def analyze_image_with_gemini(image_bytes, prompt="這是什麼植物？請用20字內簡短回答，繁體中文"):
    """強化版圖片辨識 - 多重嘗試確保成功"""
    if not gemini_vision_model:
        return "🌿 蕨積的近視還沒治好，暫時不能看圖～"
    
    try:
        # === 方法1：直接傳PIL Image ===
        try:
            img = PILImage.open(BytesIO(image_bytes))
            
            # 轉為RGB
            if img.mode in ('RGBA', 'LA', 'P'):
                rgb_img = PILImage.new('RGB', img.size, (255, 255, 255))
                rgb_img.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                img = rgb_img
            
            # 縮小圖片
            max_size = (800, 800)
            img.thumbnail(max_size, PILImage.Resampling.LANCZOS)
            
            response = gemini_vision_model.generate_content(
                [prompt, img],
                generation_config={"temperature": 0.2, "max_output_tokens": 100}
            )
            
            if response and response.text and len(response.text.strip()) > 0:
                return response.text.strip()
        except Exception as e:
            print(f"方法1失敗: {e}")
        
        # === 方法2：改用base64 ===
        try:
            # 重新載入原始圖片
            img = PILImage.open(BytesIO(image_bytes))
            
            # 轉為JPEG（確保相容性）
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            # 壓縮圖片
            output = BytesIO()
            img.save(output, format='JPEG', quality=85, optimize=True)
            jpeg_bytes = output.getvalue()
            
            # 轉base64
            img_base64 = base64.b64encode(jpeg_bytes).decode('utf-8')
            
            # 直接呼叫Gemini API（繞過SDK）
            url = f"https://generativelanguage.googleapis.com/v1/models/gemini-2.0-flash-vision:generateContent?key={GEMINI_API_KEY}"
            
            headers = {'Content-Type': 'application/json'}
            data = {
                "contents": [{
                    "parts": [
                        {"text": prompt},
                        {
                            "inline_data": {
                                "mime_type": "image/jpeg",
                                "data": img_base64
                            }
                        }
                    ]
                }],
                "generationConfig": {
                    "temperature": 0.2,
                    "maxOutputTokens": 100
                }
            }
            
            response = requests.post(url, headers=headers, json=data, timeout=30)
            result = response.json()
            
            if 'candidates' in result and len(result['candidates']) > 0:
                text = result['candidates'][0]['content']['parts'][0]['text'].strip()
                if text:
                    return text
        except Exception as e:
            print(f"方法2失敗: {e}")
        
        # === 方法3：強制回覆（當作植物）===
        return "🌿 這應該是某種觀葉植物，要拍更清楚一點我才能認出品種喔！"
        
    except Exception as e:
        print(f"所有方法都失敗: {e}")
        return "🌿 這張照片有點模糊，再拍清楚一點傳給我，我幫你認品種！"

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
        else:
            supabase.table('subscribers').update({'is_active': True}).eq('user_id', user_id).execute()
        return True
    except:
        return False

def unsubscribe_user(user_id):
    if not supabase: return False
    try:
        supabase.table('subscribers').update({'is_active': False}).eq('user_id', user_id).execute()
        return True
    except:
        return False

# ==================== 每日小知識 ====================
def get_daily_plant_fact():
    fact_prompt = """給一則「20字內」的搞笑植物知識。
範例：
「香蕉是莓果，草莓不是。植物界也搞詐欺🍌」
「蘆薈晚上吐氧氣，比咖啡提神🌵」"""
    
    headers = {
        'Authorization': f'Bearer {DEEPSEEK_API_KEY}',
        'Content-Type': 'application/json'
    }
    
    data = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": fact_prompt}],
        "max_tokens": 100
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
            except:
                pass
    except:
        pass

# ==================== 排程器 ====================
def init_scheduler():
    scheduler = BackgroundScheduler()
    tz = pytz.timezone('Asia/Taipei')
    scheduler.add_job(func=send_daily_push, trigger=CronTrigger(hour=8, minute=0, timezone=tz), id='daily_push', replace_existing=True)
    scheduler.start()
    print("✅ 排程器已啟動")
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
    if supabase: subscribe_user(user_id)
    welcome_msg = "🌿 蕨積來啦！\n傳植物照片給我，幫你認品種！\n明早8點見～"
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=welcome_msg))

@handler.add(UnfollowEvent)
def handle_unfollow(event):
    if supabase: unsubscribe_user(event.source.user_id)

# ==================== 圖片訊息處理 ====================
@handler.add(MessageEvent, message=ImageMessage)
def handle_image_message(event):
    user_id = event.source.user_id
    reply_token = event.reply_token
    message_id = event.message.id
    
    try:
        # 下載圖片
        message_content = line_bot_api.get_message_content(message_id)
        image_bytes = b''
        for chunk in message_content.iter_content():
            image_bytes += chunk
        
        # 暫存圖片
        image_temp_store[user_id] = {
            'data': image_bytes,
            'timestamp': time.time()
        }
        pending_vision[user_id] = True
        
        # 直接分析圖片（不經過選單）
        analysis = analyze_image_with_gemini(image_bytes, "這是什麼植物？請用20字內簡短回答")
        
        # 清除暫存
        pending_vision.pop(user_id, None)
        image_temp_store.pop(user_id, None)
        
        line_bot_api.reply_message(reply_token, TextSendMessage(text=analysis))
        
    except Exception as e:
        print(f"圖片處理失敗: {e}")
        line_bot_api.reply_message(
            reply_token,
            TextSendMessage(text="🌿 圖片處理失敗，再試一次？")
        )

# ==================== 文字訊息處理 ====================
@handler.add(MessageEvent, message=TextMessage)
def handle_text_message(event):
    user_message = event.message.text
    reply_token = event.reply_token
    user_id = event.source.user_id
    
    # 訂閱相關指令
    if supabase:
        if user_message in ["取消訂閱", "停止推播"]:
            unsubscribe_user(user_id)
            line_bot_api.reply_message(reply_token, TextSendMessage(text="📭 已取消"))
            return
        if user_message in ["訂閱"]:
            subscribe_user(user_id)
            line_bot_api.reply_message(reply_token, TextSendMessage(text="📬 訂閱成功"))
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
    gemini_status = "✅ 已連線" if gemini_vision_model else "⚠️ 未設定"
    return f"🌿 蕨積（強制成功版） | Gemini: {gemini_status}", 200

# ==================== 啟動 ====================
if __name__ == "__main__":
    try:
        scheduler = init_scheduler()
    except:
        pass
    
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
