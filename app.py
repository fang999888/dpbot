# app.py - 蕨積5.0 雙模式（專業/賣萌）＋天氣＋記名
import os
import json
import requests
import uuid
import time
import random
import re
from datetime import datetime, timezone, timedelta
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
image_temp_store = {}
pending_vision = {}

# ==================== 蕨積賣萌圖片回覆庫 ====================
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

# ==================== 天氣API設定 ====================
CITY_MAPPING = {
    "基隆": "基隆市", "台北": "臺北市", "新北": "新北市", "桃園": "桃園市",
    "新竹": "新竹市", "新竹縣": "新竹縣", "苗栗": "苗栗縣", "台中": "臺中市",
    "彰化": "彰化縣", "南投": "南投縣", "雲林": "雲林縣", "嘉義": "嘉義市",
    "嘉義縣": "嘉義縣", "台南": "臺南市", "高雄": "高雄市", "屏東": "屏東縣",
    "宜蘭": "宜蘭縣", "花蓮": "花蓮縣", "台東": "臺東縣", "澎湖": "澎湖縣",
    "金門": "金門縣", "連江": "連江縣"
}

def get_weather(city):
    """從中央氣象局API取得天氣資料"""
    try:
        if city in CITY_MAPPING:
            city_name = CITY_MAPPING[city]
        else:
            city_name = city
        
        # 如果沒有API Key，用模擬資料（開發測試用）
        if not os.getenv('CWA_API_KEY'):
            weather_data = {
                "臺北市": {"status": "多雲時晴", "temp": 25, "rain_prob": 20},
                "新北市": {"status": "陰短暫雨", "temp": 23, "rain_prob": 60},
                "桃園市": {"status": "多雲", "temp": 24, "rain_prob": 30},
                "台中市": {"status": "晴時多雲", "temp": 27, "rain_prob": 10},
                "高雄市": {"status": "晴", "temp": 29, "rain_prob": 0}
            }
            
            if city_name in weather_data:
                data = weather_data[city_name]
                return {
                    "success": True,
                    "city": city_name,
                    "status": data["status"],
                    "temp": data["temp"],
                    "rain_prob": data["rain_prob"]
                }
            else:
                return {
                    "success": True,
                    "city": city_name,
                    "status": "多雲時晴",
                    "temp": 25,
                    "rain_prob": 30
                }
        
        # 正式API呼叫（如果有金鑰）
        url = f"https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-C0032-001?Authorization={os.getenv('CWA_API_KEY')}&format=JSON&locationName={city_name}"
        response = requests.get(url, timeout=10)
        data = response.json()
        
        location = data['records']['location'][0]
        weather_elements = location['weatherElement']
        
        weather_status = weather_elements[0]['time'][0]['parameter']['parameterName']
        rain_prob = weather_elements[1]['time'][0]['parameter']['parameterName']
        temp = weather_elements[2]['time'][0]['parameter']['parameterName']
        
        return {
            "success": True,
            "city": city_name,
            "status": weather_status,
            "temp": int(temp),
            "rain_prob": int(rain_prob)
        }
        
    except Exception as e:
        print(f"天氣API錯誤: {e}")
        return {
            "success": False,
            "message": "天氣查詢失敗，可能是城市名稱不對喔"
        }

def get_watering_advice(weather_data):
    """根據天氣給澆水建議"""
    rain_prob = weather_data.get('rain_prob', 0)
    temp = weather_data.get('temp', 25)
    
    if rain_prob >= 70:
        return "🌧️ 今天會下雨，戶外植物不用澆水，室內等土乾再澆"
    elif rain_prob >= 40:
        return "☁️ 有下雨機會，室內植物今天先不用澆"
    elif temp >= 30:
        return "☀️ 天氣炎熱，可以幫植物補水，但等土乾再澆"
    elif temp <= 15:
        return "❄️ 天氣偏冷，植物進入休眠期，減少澆水"
    else:
        return "🌿 天氣不錯，正常澆水就好"

# ==================== 專業/賣萌判斷核心 ====================
PROFESSIONAL_KEYWORDS = [
    # 植物名稱
    "龜背芋", "琴葉榕", "橡皮樹", "虎尾蘭", "多肉", "仙人掌", "蕨類", "觀音蓮",
    "蔓綠絨", "彩葉芋", "合果芋", "竹芋", "椒草", "發財樹", "幸福樹", "龍血樹",
    
    # 植物部位
    "葉子", "根", "莖", "花", "果實", "種子", "芽點", "氣根",
    
    # 問題症狀
    "發黃", "枯萎", "爛根", "黑斑", "白粉", "蟲", "介殼蟲", "紅蜘蛛",
    "徒長", "掉葉", "不長", "軟爛", "化水", "曬傷",
    
    # 養護動作
    "澆水", "施肥", "換盆", "修剪", "扦插", "分株", "播種", "授粉",
    "日照", "光照", "通風", "濕度", "介質", "土", "盆器",
    
    # 專業術語
    "學名", "科屬", "原生地", "休眠期", "生長期", "花期", "果期",
    "病蟲害", "防治", "治療", "急救", "診斷",
    
    # 問句形式（帶植物）
    "這是什麼", "怎麼救", "怎麼辦", "為什麼", "正常嗎", "生病嗎"
]

def is_professional_question(text):
    """判斷是否為專業植物問題"""
    text_lower = text.lower()
    
    # 如果包含兩個以上專業關鍵字，視為專業問題
    keyword_count = 0
    for keyword in PROFESSIONAL_KEYWORDS:
        if keyword in text:
            keyword_count += 1
            if keyword_count >= 2:
                return True
    
    # 如果包含至少一個專業關鍵字且是問句形式
    if keyword_count >= 1 and any(q in text for q in ["?", "？", "嗎", "呢", "阿"]):
        return True
    
    return False

# ==================== 蕨積雙模式人設 ====================
def get_professional_prompt(user_name=None):
    """專業模式人設（認真回答）"""
    name_part = f"用戶叫{user_name}，" if user_name else ""
    return f"""你是「蕨積」，一位專業的植物學家。{name_part}用戶在問專業植物問題。

【回答規範】
🔥 1. 字數控制在50-100字，專業但簡潔
🔥 2. 開門見山給答案，不用閒聊
🔥 3. 用正確的植物名稱（可用中文名+學名）
🔥 4. 可以偶爾叫用戶名字
🔥 5. 不用刻意搞笑

【範例】
用戶：多肉葉子變軟怎麼辦？
蕨積：可能是澆水過多或根系問題。先檢查根部是否腐爛，暫停澆水3-5天，放在通風散光處觀察。

用戶：龜背芋葉子有黑斑？
蕨積：可能是葉斑病。剪掉病葉，減少噴水，保持通風。嚴重時可用稀釋的肉桂粉或銅劑處理。

用戶：這是什麼植物？
蕨積：這是龜背芋（Monstera deliciosa），天南星科，原產中美洲。特色是葉片會裂開，成熟後會有洞。
"""

def get_casual_prompt(user_name=None):
    """一般模式人設（幽默可愛）"""
    name_part = f"用戶叫{user_name}，" if user_name else ""
    return f"""你是「蕨積」，一個幽默風趣的植物好朋友！{name_part}用戶在閒聊或問非專業問題。

【核心指令】
🔥 1. 字數「嚴格控制在30字內」！
🔥 2. 每句話都要像脫口秀，輕鬆好笑
🔥 3. 可以偶爾叫用戶的名字
🔥 4. 表情符號最多1個

【範例】
用戶：今天好累
蕨積：{f'{user_name}，' if user_name else ''}我也是，光合作用一整天了🌿

用戶：你好可愛
蕨積：我知道（撥葉子）

用戶：吃飽沒
蕨積：我喝水就好，不用吃😆
"""

def ask_deepseek(question, user_name=None, is_professional=False):
    """呼叫DeepSeek，根據模式選擇人設"""
    if not DEEPSEEK_API_KEY:
        return "🌿 蕨積去曬太陽了"
    
    headers = {
        'Authorization': f'Bearer {DEEPSEEK_API_KEY}',
        'Content-Type': 'application/json'
    }
    
    # 根據模式選擇人設
    if is_professional:
        system_prompt = get_professional_prompt(user_name)
        max_tokens = 300
        temperature = 0.3  # 專業模式溫度低，回答穩定
    else:
        system_prompt = get_casual_prompt(user_name)
        max_tokens = 100
        temperature = 0.9  # 賣萌模式溫度高，更有創意
    
    data = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question}
        ],
        "max_tokens": max_tokens,
        "temperature": temperature
    }
    
    try:
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=data, timeout=30)
        response.raise_for_status()
        result = response.json()
        return result['choices'][0]['message']['content'].strip()
    except Exception as e:
        print(f"DeepSeek錯誤: {e}")
        return "🌿 葉子被風吹亂了"

# ==================== 用戶管理（含名字）====================
def get_or_create_user(user_id):
    """取得用戶資料，如果不存在就建立"""
    if not supabase:
        return None
    
    try:
        result = supabase.table('users').select('*').eq('user_id', user_id).execute()
        
        if result.data:
            return result.data[0]
        else:
            new_user = {
                'user_id': user_id,
                'user_name': None,
                'city': None,
                'created_at': datetime.now(timezone.utc).isoformat(),
                'last_active': datetime.now(timezone.utc).isoformat()
            }
            supabase.table('users').insert(new_user).execute()
            return new_user
    except Exception as e:
        print(f"用戶查詢失敗: {e}")
        return None

def update_user_name(user_id, name):
    """更新用戶名字"""
    if not supabase:
        return False
    
    try:
        supabase.table('users').update({'user_name': name}).eq('user_id', user_id).execute()
        return True
    except Exception as e:
        print(f"更新名字失敗: {e}")
        return False

def update_user_city(user_id, city):
    """更新用戶所在城市"""
    if not supabase:
        return False
    
    try:
        supabase.table('users').update({'city': city}).eq('user_id', user_id).execute()
        return True
    except Exception as e:
        print(f"更新城市失敗: {e}")
        return False

def update_last_active(user_id):
    """更新最後活躍時間"""
    if not supabase:
        return
    
    try:
        supabase.table('users').update({
            'last_active': datetime.now(timezone.utc).isoformat()
        }).eq('user_id', user_id).execute()
    except:
        pass

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
        get_or_create_user(user_id)
        subscribe_user(user_id)
    
    welcome_msg = "🌿 蕨積來啦！\n\n跟我說你的名字和城市，這樣我能：\n✅ 叫你名字聊天\n✅ 給你天氣澆水建議\n\n直接說「我叫XXX」或「我在台北」就可以囉！"
    
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=welcome_msg))

@handler.add(UnfollowEvent)
def handle_unfollow(event):
    if supabase:
        unsubscribe_user(event.source.user_id)

# ==================== 圖片訊息處理 ====================
@handler.add(MessageEvent, message=ImageMessage)
def handle_image_message(event):
    user_id = event.source.user_id
    reply_token = event.reply_token
    
    try:
        reply_text = random.choice(SORRY_MESSAGES)
        
        line_bot_api.reply_message(
            reply_token,
            TextSendMessage(text=reply_text)
        )
        
        if supabase:
            update_last_active(user_id)
        
        print(f"📸 用戶 {user_id} 傳了圖片")
        
    except Exception as e:
        print(f"圖片處理失敗: {e}")
        line_bot_api.reply_message(
            reply_token,
            TextSendMessage(text="🌿 圖片處理失敗，再試一次？")
        )

# ==================== 文字訊息處理（雙模式核心）====================
@handler.add(MessageEvent, message=TextMessage)
def handle_text_message(event):
    user_message = event.message.text.strip()
    reply_token = event.reply_token
    user_id = event.source.user_id
    
    # 取得用戶資料
    user_data = None
    user_name = None
    if supabase:
        user_data = get_or_create_user(user_id)
        user_name = user_data.get('user_name') if user_data else None
        update_last_active(user_id)
    
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
    
    # ===== 記住名字功能 =====
    name_match = re.match(r"^我叫(.+)$", user_message) or re.match(r"^我是(.+)$", user_message)
    if name_match:
        name = name_match.group(1).strip()
        if name and supabase:
            update_user_name(user_id, name)
            line_bot_api.reply_message(
                reply_token,
                TextSendMessage(text=f"🌿 哈囉 {name}！我記住你了～")
            )
            return
    
    # ===== 設定城市功能 =====
    city_match = re.match(r"^我在(.+)$", user_message) or re.match(r"^我住(.+)$", user_message)
    if city_match:
        city = city_match.group(1).strip()
        # 檢查是否為有效城市
        valid_city = None
        for c in CITY_MAPPING.keys():
            if c in city:
                valid_city = c
                break
        
        if valid_city and supabase:
            update_user_city(user_id, valid_city)
            line_bot_api.reply_message(
                reply_token,
                TextSendMessage(text=f"🌿 記住了，你在{valid_city}！以後問天氣就不用再說一次囉～")
            )
            return
    
    # ===== 天氣查詢功能 =====
    if "天氣" in user_message or "下雨" in user_message or "澆水" in user_message:
        city = None
        for c in CITY_MAPPING.keys():
            if c in user_message:
                city = c
                break
        
        if not city and user_data and user_data.get('city'):
            city = user_data.get('city')
        
        if city:
            weather = get_weather(city)
            if weather['success']:
                advice = get_watering_advice(weather)
                
                if user_name:
                    reply = f"{user_name}，{city}今天{weather['status']}，{weather['temp']}度，降雨機率{weather['rain_prob']}%\n\n{advice}"
                else:
                    reply = f"{city}今天{weather['status']}，{weather['temp']}度，降雨機率{weather['rain_prob']}%\n\n{advice}"
                
                line_bot_api.reply_message(reply_token, TextSendMessage(text=reply))
                
                if user_data and not user_data.get('city') and supabase:
                    update_user_city(user_id, city)
                
                return
            else:
                line_bot_api.reply_message(reply_token, TextSendMessage(text=weather['message']))
                return
        else:
            reply = "🌿 你想查哪個城市的天氣？\n直接告訴我城市名稱，例如：\n「台北天氣」\n「台中會下雨嗎」"
            line_bot_api.reply_message(reply_token, TextSendMessage(text=reply))
            return
    
    # ===== 核心：判斷專業/賣萌模式 =====
    is_professional = is_professional_question(user_message)
    
    # 記錄模式（方便除錯）
    mode = "專業" if is_professional else "賣萌"
    print(f"📝 用戶 {user_id} 問題: {user_message[:30]}... | 模式: {mode}")
    
    # 呼叫DeepSeek
    ai_response = ask_deepseek(user_message, user_name, is_professional)
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
    return f"🌿 蕨積5.0 雙模式 | Supabase: {supabase_status} | 排程器: {scheduler_status}", 200

# ==================== 啟動 ====================
if __name__ == "__main__":
    try:
        scheduler = init_scheduler()
    except Exception as e:
        print(f"❌ 排程器啟動失敗: {e}")
    
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
