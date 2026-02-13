# app.py - 蕨積3.0 會看圖片的植物醫生（Gemini Vision + DeepSeek）
import os
import json
import requests
import uuid
import time
from datetime import datetime, timezone
from flask import Flask, request, abort, jsonify, send_file
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, ImageMessage, TextSendMessage, ImageSendMessage,
    FollowEvent, PostbackEvent,  UnfollowEvent, QuickReply, QuickReplyButton, PostbackAction
)
from supabase import create_client, Client
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz
import atexit
import google.generativeai as genai
from io import BytesIO

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
    gemini_vision_model = genai.GenerativeModel('gemini-1.5-flash')  # 便宜又快，適合植物辨識
    print("✅ Gemini Vision 初始化成功")
else:
    gemini_vision_model = None
    print("⚠️ 未設定 Gemini API Key，圖片辨識功能無法使用")

# DeepSeek
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

# ==================== 圖片暫存區（給LINE非同步機制用）====================
image_temp_store = {}  # user_id -> {image_bytes, timestamp}
pending_vision = {}    # user_id -> True（等待使用者選擇模式）

# 標註圖片暫存區（給Agentic Vision回傳用）
annotated_image_store = {}  # image_id -> {data: bytes, created_at: timestamp}
app_base_url = None  # 會在webhook時自動偵測

# ==================== 🎭 蕨積人設（精簡笑話版）====================
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

用戶：這是什麼植物？（附圖）
蕨積：龜背芋。它葉子破洞是天生的，不是蟲咬啦！

用戶：你好可愛
蕨積：我知道（撥葉子）

【鐵則】
❌ 不要心靈雞湯
❌ 不要囉嗦關心
✅ 短！快！好笑！
"""

# ==================== DeepSeek 呼叫（純文字聊天）====================
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

# ==================== Gemini Vision 圖片辨識 ====================
def analyze_image_with_gemini(image_bytes, prompt="這是什麼植物？請用20字內簡短回答，繁體中文"):
    """使用 Gemini Vision 分析圖片內容"""
    if not gemini_vision_model:
        return "🌿 蕨積的近視還沒治好，暫時不能看圖～"
    
    try:
        # 將圖片bytes轉換為Gemini可讀格式
        img = genai.upload_file(io.BytesIO(image_bytes))
        
        # 產生回應
        response = gemini_vision_model.generate_content(
            [prompt, img],
            generation_config={
                "temperature": 0.4,
                "max_output_tokens": 100,
            }
        )
        
        return response.text.strip()
    except Exception as e:
        print(f"Gemini Vision 錯誤: {e}")
        return "🌿 這張圖太難了，換一張試試？"

# ==================== 訂閱管理（維持原樣）====================
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

# ==================== 圖片暫存服務 ====================
@app.route("/images/<image_id>")
def serve_annotated_image(image_id):
    """提供暫存的標註圖片給LINE下載"""
    entry = annotated_image_store.get(image_id)
    if not entry:
        return abort(404)
    if time.time() - entry["created_at"] > 300:  # 5分鐘過期
        annotated_image_store.pop(image_id, None)
        return abort(404)
    return send_file(
        BytesIO(entry["data"]),
        mimetype="image/png",
        download_name=f"{image_id}.png"
    )

def store_annotated_image(image_bytes):
    """儲存標註圖片並回傳ID"""
    image_id = str(uuid.uuid4())
    annotated_image_store[image_id] = {
        "data": image_bytes,
        "created_at": time.time()
    }
    return image_id

# ==================== LINE Webhook ====================
@app.route("/callback", methods=['POST'])
def callback():
    global app_base_url
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    
    # 自動偵測應用程式的Base URL
    if not app_base_url:
        forwarded_proto = request.headers.get('x-forwarded-proto', 'https')
        host = request.headers.get('x-forwarded-host') or request.headers.get('host', '')
        if host:
            app_base_url = f"{forwarded_proto}://{host}"
            print(f"✅ 自動偵測 Base URL: {app_base_url}")
    
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
    welcome_msg = "🌿 蕨積啦！\n現在我會看圖了喔～\n傳植物照片給我，幫你認品種！\n明早8點見～"
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=welcome_msg))

@handler.add(UnfollowEvent)
def handle_unfollow(event):
    if supabase: unsubscribe_user(event.source.user_id)

# ==================== 🆕 圖片訊息處理 ====================
@handler.add(MessageEvent, message=ImageMessage)
def handle_image_message(event):
    user_id = event.source.user_id
    reply_token = event.reply_token
    message_id = event.message.id
    
    # 1. 從LINE下載圖片
    message_content = line_bot_api.get_message_content(message_id)
    image_bytes = b''
    for chunk in message_content.iter_content():
        image_bytes += chunk
    
    # 2. 暫存圖片（給後續分析用）
    image_temp_store[user_id] = {
        'data': image_bytes,
        'timestamp': time.time()
    }
    pending_vision[user_id] = True
    
    # 3. 提供快速選單
    quick_reply = QuickReply(
        items=[
            QuickReplyButton(
                action=PostbackAction(
                    label="🌿 這是什麼植物？",
                    data=json.dumps({"action": "vision", "type": "identify"}),
                    display_text="這是什麼植物？"
                )
            ),
            QuickReplyButton(
                action=PostbackAction(
                    label="🔍 檢查病害",
                    data=json.dumps({"action": "vision", "type": "disease"}),
                    display_text="這盆植物生病了嗎？"
                )
            ),
            QuickReplyButton(
                action=PostbackAction(
                    label="💚 健康狀況",
                    data=json.dumps({"action": "vision", "type": "health"}),
                    display_text="這棵植物健康嗎？"
                )
            ),
            QuickReplyButton(
                action=PostbackAction(
                    label="✂️ 標記葉子",
                    data=json.dumps({"action": "vision", "type": "annotate"}),
                    display_text="幫我標記葉子的位置"
                )
            )
        ]
    )
    
    reply_msg = TextSendMessage(
        text="🌿 收到圖片囉！你想問蕨積什麼？",
        quick_reply=quick_reply
    )
    
    line_bot_api.reply_message(reply_token, reply_msg)

# ==================== 🆕 Postback 處理 ====================
@handler.add(MessageEvent, message=TextMessage)
def handle_text_message(event):
    user_message = event.message.text
    reply_token = event.reply_token
    user_id = event.source.user_id
    
    # ===== 訂閱相關指令 =====
    if supabase:
        if user_message in ["取消訂閱", "停止推播", "unsubscribe"]:
            unsubscribe_user(user_id)
            line_bot_api.reply_message(reply_token, TextSendMessage(text="📭 已取消，想回來說「訂閱」"))
            return
        if user_message in ["訂閱", "subscribe"]:
            subscribe_user(user_id)
            line_bot_api.reply_message(reply_token, TextSendMessage(text="📬 訂閱成功！明早8點見"))
            return
    
    # ===== 檢查是否在等待圖片分析 =====
    if user_id in pending_vision and pending_vision[user_id]:
        # 這是一般文字，不是Postback，可能是使用者自己輸入的問題
        # 我們還是可以分析圖片
        if user_id in image_temp_store:
            image_data = image_temp_store[user_id]['data']
            
            # 用Gemini分析圖片 + 使用者的問題
            analysis = analyze_image_with_gemini(
                image_data, 
                prompt=f"{user_message} 請用30字內簡短回答，繁體中文"
            )
            
            # 清除暫存狀態
            pending_vision.pop(user_id, None)
            image_temp_store.pop(user_id, None)
            
            line_bot_api.reply_message(reply_token, TextSendMessage(text=analysis))
            return
    
    # ===== 一般聊天 =====
    ai_response = ask_deepseek(user_message)
    line_bot_api.reply_message(reply_token, TextSendMessage(text=ai_response))

@handler.add(PostbackEvent)
def handle_postback(event):
    user_id = event.source.user_id
    reply_token = event.reply_token
    postback_data = json.loads(event.postback.data)
    
    if postback_data.get('action') == 'vision':
        vision_type = postback_data.get('type')
        
        # 檢查是否有暫存的圖片
        if user_id not in image_temp_store:
            line_bot_api.reply_message(
                reply_token,
                TextSendMessage(text="🌿 找不到圖片耶，請重新傳一張給我看")
            )
            return
        
        image_data = image_temp_store[user_id]['data']
        
        # 根據不同模式設定提示詞
        prompts = {
            'identify': '這是什麼植物？請用20字內簡短回答，繁體中文',
            'disease': '這盆植物生病了嗎？如果有病害請說名稱，沒病就說健康。20字內',
            'health': '這棵植物健康嗎？簡短評分：良好/普通/不佳，20字內',
            'annotate': '請標記圖片中的葉子位置，並回傳標註後的圖片'  # 進階功能需用Agentic Vision
        }
        
        prompt = prompts.get(vision_type, prompts['identify'])
        
        # 一般辨識（不回傳圖片）
        if vision_type != 'annotate':
            analysis = analyze_image_with_gemini(image_data, prompt)
            line_bot_api.reply_message(reply_token, TextSendMessage(text=analysis))
            
            # 清除暫存
            pending_vision.pop(user_id, None)
            image_temp_store.pop(user_id, None)
        
        # 標記功能需要回傳圖片（進階功能）
        else:
            # 這裡可以擴充Agentic Vision，先回傳簡單訊息
            analysis = analyze_image_with_gemini(image_data, "請描述這張圖片中葉子的位置和形狀")
            line_bot_api.reply_message(reply_token, TextSendMessage(text=f"🌿 葉子位置：{analysis}\n\n（標記圖片功能開發中，先給你文字描述）"))
            
            pending_vision.pop(user_id, None)
            image_temp_store.pop(user_id, None)

# ==================== 測試端點 ====================
@app.route("/test-push", methods=['GET'])
def test_push():
    send_daily_push()
    return {"status": "push triggered"}, 200

@app.route("/", methods=['GET'])
def health():
    supabase_status = "✅ 已連線" if supabase else "⚠️ 未設定"
    gemini_status = "✅ 已連線" if gemini_vision_model else "⚠️ 未設定"
    scheduler_status = "✅ 運行中"
    return f"🌿 蕨積3.0 會看圖版 | Supabase: {supabase_status} | Gemini: {gemini_status} | 排程器: {scheduler_status}", 200

# ==================== 啟動 ====================
if __name__ == "__main__":
    try:
        scheduler = init_scheduler()
    except Exception as e:
        print(f"❌ 排程器啟動失敗: {e}")
    
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
