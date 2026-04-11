# app.py - 蕨積最終完整版（Gemini圖片識別 + 失敗賣萌 + 網頁對話）
import os
import json
import requests
import uuid
import time
import random
import re
import base64
from datetime import datetime, timezone, timedelta
from flask import Flask, request, abort, jsonify, render_template
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
import urllib3
# Gemini
import google.generativeai as genai
from PIL import Image
from io import BytesIO

# 抑制 SSL 警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)

# ==================== 環境變數 ====================
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
CWA_API_KEY = os.getenv('CWA_API_KEY')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
LIFF_ID = os.getenv('LIFF_ID', '')

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

# Gemini
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    gemini_vision_model = genai.GenerativeModel('gemini-1.5-flash')
    print("✅ Gemini Vision 初始化成功")
else:
    gemini_vision_model = None
    print("⚠️ 未設定 Gemini API Key，圖片識別功能將無法使用")

# ==================== 網頁對話暫存區 ====================
web_pending_replies = {}  # {user_id: {"reply": "內容", "timestamp": time}}

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

# ==================== 內建植物知識庫 ====================
LOCAL_FACTS = [
    "🌵 仙人掌的刺其實是變態葉，用來減少水分蒸發！",
    "🍌 香蕉是莓果，草莓反而不是，植物界也搞詐欺！",
    "🌿 蘆薈晚上會釋放氧氣，很適合放臥室喔～",
    "🎋 竹子其實是草，不是樹，而且有些品種一天可以長一米！",
    "🌻 向日葵會跟著太陽轉，是因為莖部的生長素怕光。",
    "🍍 鳳梨是很多漿果集合成的複合果，每一粒「眼睛」都是一朵花。",
    "🌱 含羞草閉合不是害羞，是為了嚇跑草食動物。",
    "🍅 番茄是水果，但我們把它當蔬菜用，法律上也判為蔬菜。",
    "🌾 稻米是人類一半人口的主食，台灣種植的是梗稻和秈稻。",
    "🍈 哈密瓜和香瓜是親戚，但哈密瓜更怕潮濕。",
    "🌿 龜背芋的洞洞是為了讓陽光穿透到下面的葉子。",
    "🌱 多肉植物晚上吸收二氧化碳，白天關閉氣孔。",
    "🌲 世界上最高的樹是加州紅杉，可以超過100公尺。",
    "🌸 櫻花的葉子發酵後可以製成櫻花茶，有淡淡香氣。",
    "🍂 楓葉變紅是因為秋天葉綠素分解，留下花青素。",
    "🌿 薄荷不僅清涼，還是天然的驅蟲劑。",
    "🌱 豆科植物的根瘤可以固氮，是天然的肥料工廠。",
    "🌻 向日葵的頭狀花序其實是由許多小花組成的。",
    "🍎 蘋果切開後變褐色是因為酚類物質氧化。",
    "🌵 量天尺（火龍果的花）只開一晚，被稱為『夜皇后』。"
]

# ==================== 天氣API設定（城市對照表）====================
CITY_MAPPING = {
    "基隆": "基隆市", "台北": "臺北市", "新北": "新北市", "板橋": "新北市", "永和": "新北市",
    "桃園": "桃園市", "中壢": "桃園市", "新竹": "新竹市", "竹北": "新竹縣", "苗栗": "苗栗縣",
    "台中": "臺中市", "豐原": "臺中市", "彰化": "彰化縣", "南投": "南投縣", "雲林": "雲林縣",
    "嘉義": "嘉義市", "民雄": "嘉義縣", "台南": "臺南市", "永康": "臺南市", "高雄": "高雄市",
    "鳳山": "高雄市", "屏東": "屏東縣", "宜蘭": "宜蘭縣", "羅東": "宜蘭縣", "花蓮": "花蓮縣",
    "台東": "臺東縣", "澎湖": "澎湖縣", "金門": "金門縣", "連江": "連江縣"
}

def get_weather(city):
    """從中央氣象署API取得即時天氣資料"""
    if not CWA_API_KEY:
        return {"success": False, "message": "❌ 未設定氣象API金鑰，請在環境變數中加入 CWA_API_KEY"}

    city_name = CITY_MAPPING.get(city, city)
    dataset_id = 'F-C0032-001'
    url = f"https://opendata.cwa.gov.tw/api/v1/rest/datastore/{dataset_id}?Authorization={CWA_API_KEY}&format=JSON&locationName={city_name}"

    try:
        response = requests.get(url, timeout=10, verify=False)
        response.raise_for_status()
        data = response.json()

        if 'records' not in data:
            return {"success": False, "message": "天氣資料格式異常"}

        location = data['records']['location'][0]
        weather_elements = location['weatherElement']
        weather_status = weather_elements[0]['time'][0]['parameter']['parameterName']
        rain_prob = weather_elements[1]['time'][0]['parameter']['parameterName']
        min_temp = weather_elements[2]['time'][0]['parameter']['parameterName']
        max_temp = weather_elements[4]['time'][0]['parameter']['parameterName']

        def safe_int(val):
            try:
                return int(float(val))
            except:
                return 0

        return {
            "success": True,
            "city": location['locationName'],
            "status": weather_status,
            "max_temp": safe_int(max_temp),
            "min_temp": safe_int(min_temp),
            "rain_prob": safe_int(rain_prob)
        }
    except Exception as e:
        print(f"天氣API錯誤: {e}")
        return {"success": False, "message": "天氣查詢失敗"}

def get_watering_advice(weather_data):
    rain_prob = weather_data.get('rain_prob', 0)
    temp = weather_data.get('max_temp', 25)
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

# ==================== 專業/賣萌判斷核心（權重版）====================
PROFESSIONAL_WEIGHTS = {
    "多肉": 3, "龜背芋": 3, "琴葉榕": 3, "虎尾蘭": 3, "仙人掌": 3,
    "蕨類": 3, "觀音蓮": 3, "蔓綠絨": 3, "彩葉芋": 3, "竹芋": 3,
    "發財樹": 3, "幸福樹": 3, "龍血樹": 3, "黃金葛": 3, "吊蘭": 3,
    "常春藤": 3, "薄荷": 3, "迷迭香": 3, "薰衣草": 3, "羅勒": 3,
    "辣椒": 3, "番茄": 3, "草莓": 3, "藍莓": 3,
    "軟": 2, "黃": 2, "黑": 2, "爛": 2, "枯": 2, "掉": 2, "垂": 2,
    "軟葉": 3, "發黃": 3, "變黃": 3, "黑斑": 3, "爛根": 3,
    "枯萎": 3, "掉葉": 3, "徒長": 3, "化水": 3, "曬傷": 3,
    "斑": 2, "洞": 2, "蟲": 3, "介殼蟲": 3, "紅蜘蛛": 3,
    "蚜蟲": 3, "粉蝨": 3, "黴": 2, "鏽": 2,
    "澆水": 2, "施肥": 2, "換盆": 2, "修剪": 2, "扦插": 2,
    "分株": 2, "播種": 2, "授粉": 2,
    "日照": 1, "光照": 1, "通風": 1, "濕度": 1, "介質": 1,
    "土": 1, "盆": 1, "水": 1,
    "學名": 2, "科屬": 2, "原生地": 2, "休眠期": 2, "生長期": 2,
    "病蟲害": 2, "防治": 2, "治療": 2, "急救": 2, "診斷": 2,
    "怎麼辦": 1, "怎麼救": 1, "為什麼": 1, "正常嗎": 1, "生病嗎": 1,
    "什麼問題": 1, "怎麼了": 1, "如何": 1, "怎樣": 1
}
PLANT_LIST = ["多肉", "龜背芋", "虎尾蘭", "仙人掌", "蕨類", "發財樹", "黃金葛", "吊蘭", "薄荷", "迷迭香", "薰衣草"]
CASUAL_PHRASES = ["你好", "嗨", "哈囉", "早安", "午安", "晚安", "吃飯", "吃飽", "累了", "無聊", "可愛", "喜歡", "哈哈", "呵呵", "加油", "謝謝", "在嗎", "幹嘛", "好哦", "真的", "假的", "笑死", "傻眼", "天氣", "下雨", "熱", "冷", "颱風", "今天", "明天"]

def is_professional_question(text):
    text_lower = text.lower()
    if len(text) <= 6:
        for plant in PLANT_LIST:
            if plant in text:
                return True
        return False
    for phrase in CASUAL_PHRASES:
        if phrase in text_lower and len(text) < 15:
            return False
    total_weight = 0
    has_plant = False
    for keyword, weight in PROFESSIONAL_WEIGHTS.items():
        if keyword in text:
            total_weight += weight
            if weight >= 3 and keyword in PLANT_LIST:
                has_plant = True
    if has_plant and total_weight >= 2:
        return True
    if total_weight >= 3:
        return True
    if has_plant and total_weight >= 1 and any(q in text for q in ["?", "？", "嗎", "呢"]):
        return True
    if ("怎麼" in text or "如何" in text) and total_weight >= 1:
        return True
    return False

# ==================== 蕨積雙模式人設 ====================
def get_professional_prompt(user_name=None):
    name_part = f"用戶叫{user_name}，" if user_name else ""
    return f"""你是「蕨積」，一位專業的植物學家。{name_part}用戶在問專業植物問題。

【⚠️ 非常重要 - 必須遵守】
🔥 1. 你現在是「植物學博士」，不是搞笑藝人
🔥 2. 絕對不能開玩笑、不能用表情符號
🔥 3. 回答要像教科書一樣專業、準確
🔥 4. 字數控制在50-100字，但寧可長不能隨便
🔥 5. 必須包含：原因分析 + 解決方案 + 預防建議
🔥 6. 如果用戶沒給足夠資訊，要反問關鍵細節

【回答格式強制要求】
- 第一句：直接診斷問題原因
- 第二句：給具體解決步驟
- 第三句：預防再次發生

【範例】
用戶：多肉葉子變軟怎麼辦？
蕨積：這是典型澆水過多導致的根部問題。建議立即停止澆水，將植株移到通風處，檢查根系是否有腐爛跡象。未來澆水需等土壤完全乾燥再進行。

【鐵則】
❌ 禁止：哈哈、喔喔、耶、啦、吧、～、🌿、💚 等任何語氣詞和表情符號
✅ 必須：專業、冷靜、準確、有用
"""

def get_casual_prompt(user_name=None):
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
"""

# ==================== DeepSeek 呼叫 ====================
def ask_deepseek(question, user_name=None, is_professional=False):
    if not DEEPSEEK_API_KEY:
        return "🌿 蕨積去曬太陽了"
    headers = {'Authorization': f'Bearer {DEEPSEEK_API_KEY}', 'Content-Type': 'application/json'}
    if is_professional:
        forced_question = f"""【重要】你現在是植物學博士，請用極度專業、冷靜、準確的方式回答。禁止使用任何語氣詞、表情符號。回答必須包含原因、解法、預防。
問題：{question}"""
        system_prompt = get_professional_prompt(user_name)
        data = {"model": "deepseek-chat", "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": forced_question}], "max_tokens": 400, "temperature": 0.1, "top_p": 0.1}
    else:
        system_prompt = get_casual_prompt(user_name)
        data = {"model": "deepseek-chat", "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": question}], "max_tokens": 100, "temperature": 0.9}
    try:
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=data, timeout=30)
        response.raise_for_status()
        return response.json()['choices'][0]['message']['content'].strip()
    except Exception as e:
        print(f"DeepSeek錯誤: {e}")
        return "🌿 葉子被風吹亂了"

# ==================== 用戶管理 ====================
def get_or_create_user(user_id):
    if not supabase: return None
    try:
        result = supabase.table('users').select('*').eq('user_id', user_id).execute()
        if result.data:
            return result.data[0]
        else:
            new_user = {'user_id': user_id, 'user_name': None, 'city': None, 'created_at': datetime.now(timezone.utc).isoformat(), 'last_active': datetime.now(timezone.utc).isoformat()}
            supabase.table('users').insert(new_user).execute()
            return new_user
    except Exception as e:
        print(f"用戶查詢失敗: {e}")
        return None

def update_user_name(user_id, name):
    if not supabase: return False
    try:
        supabase.table('users').update({'user_name': name}).eq('user_id', user_id).execute()
        return True
    except Exception as e:
        print(f"更新名字失敗: {e}")
        return False

def update_user_city(user_id, city):
    if not supabase: return False
    try:
        supabase.table('users').update({'city': city}).eq('user_id', user_id).execute()
        return True
    except Exception as e:
        print(f"更新城市失敗: {e}")
        return False

def update_last_active(user_id):
    if not supabase: return
    try:
        supabase.table('users').update({'last_active': datetime.now(timezone.utc).isoformat()}).eq('user_id', user_id).execute()
    except:
        pass

# ==================== 訂閱管理 ====================
def subscribe_user(user_id):
    if not supabase: return False
    try:
        existing = supabase.table('subscribers').select('*').eq('user_id', user_id).execute()
        if not existing.data:
            data = {'user_id': user_id, 'subscribed_at': datetime.now(timezone.utc).isoformat(), 'last_push_date': None, 'is_active': True}
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

# ==================== 主動查詢小知識 ====================
def get_random_local_fact():
    return random.choice(LOCAL_FACTS)

# ==================== 每日植物小知識（永不重複版）====================
_last_fact = None

def get_daily_plant_fact():
    global _last_fact
    today_yday = datetime.now(timezone.utc).timetuple().tm_yday
    backup_index = today_yday % len(LOCAL_FACTS)
    backup_fact = LOCAL_FACTS[backup_index]

    try:
        headers = {'Authorization': f'Bearer {DEEPSEEK_API_KEY}', 'Content-Type': 'application/json'}
        fact_prompt = """請給一則「20字內」的搞笑植物知識，要讓人會心一笑。今天的主題可以和昨天完全不同。範例：
「香蕉是莓果，草莓不是」
「蘆薈晚上吐氧氣」
「含羞草不是害羞」
「豬籠草會吃蟲」"""
        data = {"model": "deepseek-chat", "messages": [{"role": "user", "content": fact_prompt}], "max_tokens": 100, "temperature": 0.9}
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=data, timeout=30)
        ai_fact = response.json()['choices'][0]['message']['content'].strip()
        if len(ai_fact) > 50:
            ai_fact = ai_fact[:50] + "…"

        if random.random() < 0.7 and ai_fact != _last_fact:
            _last_fact = ai_fact
            return ai_fact
        else:
            final_fact = backup_fact
            if final_fact == _last_fact:
                final_fact = LOCAL_FACTS[(backup_index + 1) % len(LOCAL_FACTS)]
            _last_fact = final_fact
            return final_fact
    except Exception as e:
        print(f"AI知識失敗: {e}")
        final_fact = backup_fact
        if final_fact == _last_fact:
            final_fact = LOCAL_FACTS[(backup_index + 1) % len(LOCAL_FACTS)]
        _last_fact = final_fact
        return final_fact

# ==================== Gemini Vision 圖片識別 ====================
def analyze_image_with_gemini(image_bytes):
    """使用Gemini Vision分析圖片，返回描述文字，失敗返回None"""
    if not gemini_vision_model:
        return None
    try:
        img = Image.open(BytesIO(image_bytes))
        if img.mode != 'RGB':
            img = img.convert('RGB')
        max_size = (1024, 1024)
        img.thumbnail(max_size, Image.Resampling.LANCZOS)

        prompt = "請描述這張圖片中的內容，特別是如果裡面有植物，請告訴我它是什麼植物、有什麼特徵。如果沒有植物，就描述圖片內容。"

        response = gemini_vision_model.generate_content([prompt, img])
        if response and response.text:
            return response.text.strip()
        else:
            return None
    except Exception as e:
        print(f"Gemini Vision 錯誤: {e}")
        return None

# ==================== 推播函數 ====================
def send_daily_push():
    if not supabase:
        print("❌ Supabase未連線，無法推播")
        return
    today = datetime.now(timezone.utc).date().isoformat()
    print(f"🔍 今天的日期 (UTC): {today}")
    try:
        response = supabase.table('subscribers').select('*').eq('is_active', True).execute()
        all_active = response.data
        subscribers = [user for user in all_active if user.get('last_push_date') != today]
        if not subscribers:
            print("📭 今天沒有需要推播的用戶")
            return

        daily_fact = get_daily_plant_fact()
        print(f"🌱 今日知識: {daily_fact}")

        success_count = 0
        for sub in subscribers:
            user_id = sub['user_id']
            city = None
            try:
                user_res = supabase.table('users').select('city').eq('user_id', user_id).execute()
                if user_res.data and user_res.data[0].get('city'):
                    city = user_res.data[0]['city']
                else:
                    city = "桃園"
            except:
                city = "桃園"

            weather_text = ""
            if city:
                weather = get_weather(city)
                if weather['success']:
                    weather_text = f"\n\n今日天氣（{weather['city']}）：{weather['status']}，最高{weather['max_temp']}°C，最低{weather['min_temp']}°C，降雨機率{weather['rain_prob']}%"

            message_text = f"🌱 **蕨積早安**\n\n{daily_fact}{weather_text}"

            try:
                line_bot_api.push_message(user_id, TextSendMessage(text=message_text))
                supabase.table('subscribers').update({'last_push_date': today}).eq('user_id', user_id).execute()
                success_count += 1
            except Exception as e:
                print(f"❌ 推播失敗 {user_id}: {e}")

        print(f"📊 推播完成：成功 {success_count} / 總共 {len(subscribers)}")
    except Exception as e:
        print(f"❌ 推播處理例外: {e}")

# ==================== 排程器 ====================
def init_scheduler():
    scheduler = BackgroundScheduler()
    tz = pytz.timezone('Asia/Taipei')
    scheduler.add_job(func=send_daily_push, trigger=CronTrigger(hour=8, minute=0, timezone=tz), id='daily_push', replace_existing=True)
    scheduler.start()
    print("✅ 排程器已啟動，每天 08:00 推播")
    atexit.register(lambda: scheduler.shutdown())
    return scheduler

# 全域啟動排程器
if not app.debug or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
    try:
        scheduler = init_scheduler()
    except Exception as e:
        print(f"❌ 排程器啟動失敗: {e}")

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
    if supabase:
        get_or_create_user(user_id)
        subscribe_user(user_id)
    welcome_msg = "🌿 蕨積來啦！\n\n跟我說你的名字和城市，這樣我能：\n✅ 叫你名字聊天\n✅ 給你天氣澆水建議\n✅ 說「知識」隨機給你小知識\n✅ 傳圖片我會幫你識別（如果失敗就賣萌）\n\n直接說「我叫XXX」或「我在台北」就可以囉！"
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=welcome_msg))

@handler.add(UnfollowEvent)
def handle_unfollow(event):
    if supabase:
        unsubscribe_user(event.source.user_id)

# ==================== 圖片訊息處理（Gemini識別 + 失敗賣萌）====================
@handler.add(MessageEvent, message=ImageMessage)
def handle_image_message(event):
    user_id = event.source.user_id
    reply_token = event.reply_token
    message_id = event.message.id

    try:
        message_content = line_bot_api.get_message_content(message_id)
        image_bytes = b''
        for chunk in message_content.iter_content():
            image_bytes += chunk

        if gemini_vision_model:
            result = analyze_image_with_gemini(image_bytes)
            if result:
                # 儲存回覆給網頁輪詢
                web_pending_replies[user_id] = {"reply": result, "timestamp": time.time()}
                line_bot_api.reply_message(reply_token, TextSendMessage(text=result))
                print(f"📸 用戶 {user_id} 圖片識別成功")
                return

        reply_text = random.choice(SORRY_MESSAGES)
        # 儲存回覆給網頁輪詢
        web_pending_replies[user_id] = {"reply": reply_text, "timestamp": time.time()}
        line_bot_api.reply_message(reply_token, TextSendMessage(text=reply_text))
        print(f"📸 用戶 {user_id} 圖片識別失敗，改用賣萌")

    except Exception as e:
        print(f"圖片處理失敗: {e}")
        reply_text = random.choice(SORRY_MESSAGES)
        web_pending_replies[user_id] = {"reply": reply_text, "timestamp": time.time()}
        line_bot_api.reply_message(reply_token, TextSendMessage(text=reply_text))

    finally:
        if supabase:
            update_last_active(user_id)

# ==================== 文字訊息處理 ====================
@handler.add(MessageEvent, message=TextMessage)
def handle_text_message(event):
    user_message = event.message.text.strip()
    reply_token = event.reply_token
    user_id = event.source.user_id
    user_data = None
    user_name = None
    if supabase:
        user_data = get_or_create_user(user_id)
        user_name = user_data.get('user_name') if user_data else None
        update_last_active(user_id)

    # 除錯指令：顯示 User ID
    if user_message == "我的ID":
        line_bot_api.reply_message(reply_token, TextSendMessage(text=f"你的 LINE Bot User ID: {user_id}"))
        return

    # 訂閱相關
    if supabase:
        if user_message in ["取消訂閱", "停止推播", "unsubscribe"]:
            unsubscribe_user(user_id)
            line_bot_api.reply_message(reply_token, TextSendMessage(text="📭 已取消，想回來說「訂閱」"))
            return
        if user_message in ["訂閱", "subscribe"]:
            subscribe_user(user_id)
            line_bot_api.reply_message(reply_token, TextSendMessage(text="📬 訂閱成功！不定時發送植物小常識！"))
            return

    # 記住名字
    name_match = re.match(r"^我叫(.+)$", user_message) or re.match(r"^我是(.+)$", user_message)
    if name_match:
        name = name_match.group(1).strip()
        if name and supabase:
            update_user_name(user_id, name)
            reply_text = f"🌿 哈囉 {name}！我記住你了～"
            web_pending_replies[user_id] = {"reply": reply_text, "timestamp": time.time()}
            line_bot_api.reply_message(reply_token, TextSendMessage(text=reply_text))
            return

    # 設定城市
    city_match = re.match(r"^我在(.+)$", user_message) or re.match(r"^我住(.+)$", user_message)
    if city_match:
        city = city_match.group(1).strip()
        valid_city = None
        for c in CITY_MAPPING.keys():
            if c in city:
                valid_city = c
                break
        if valid_city and supabase:
            update_user_city(user_id, valid_city)
            reply_text = f"🌿 記住了，你在{valid_city}！以後問天氣就不用再說一次囉～"
            web_pending_replies[user_id] = {"reply": reply_text, "timestamp": time.time()}
            line_bot_api.reply_message(reply_token, TextSendMessage(text=reply_text))
            return

    # 天氣查詢
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
                    reply = f"{user_name}，{weather['city']}今天{weather['status']}，最高{weather['max_temp']}度，最低{weather['min_temp']}度，降雨機率{weather['rain_prob']}%\n\n{advice}"
                else:
                    reply = f"{weather['city']}今天{weather['status']}，最高{weather['max_temp']}度，最低{weather['min_temp']}度，降雨機率{weather['rain_prob']}%\n\n{advice}"
                web_pending_replies[user_id] = {"reply": reply, "timestamp": time.time()}
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

    # 主動查詢小知識
    if any(keyword in user_message for keyword in ["知識", "常識", "小知識", "冷知識"]):
        fact = get_random_local_fact()
        web_pending_replies[user_id] = {"reply": fact, "timestamp": time.time()}
        line_bot_api.reply_message(reply_token, TextSendMessage(text=fact))
        return

    # 專業判斷
    is_professional = is_professional_question(user_message)
    mode = "🔬 專業模式" if is_professional else "😊 賣萌模式"
    print(f"📝 用戶 {user_id} | {mode} | 問題: {user_message}")
    ai_response = ask_deepseek(user_message, user_name, is_professional)
    # 儲存回覆給網頁輪詢
    web_pending_replies[user_id] = {"reply": ai_response, "timestamp": time.time()}
    line_bot_api.reply_message(reply_token, TextSendMessage(text=ai_response))

# ==================== 網頁對話功能（LIFF + 輪詢）====================
@app.route("/webchat", methods=['GET'])
def webchat_page():
    """提供網頁聊天室介面（含 LIFF）"""
    return render_template('webchat.html', liff_id=LIFF_ID)

@app.route("/webchat/send", methods=['POST'])
def webchat_send():
    """網頁發送訊息 - 直接呼叫 AI，不走 LINE"""
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        message = data.get('message', '').strip()
        
        print(f"📤 收到網頁訊息 - user_id: {user_id}, message: {message}")
        
        if not user_id or not message:
            return jsonify({'success': False, 'error': '缺少參數'}), 400
        
        # 從 Supabase 獲取用戶名稱（如果有）
        user_name = None
        if supabase:
            try:
                user_data = supabase.table('users').select('user_name').eq('user_id', user_id).execute()
                if user_data.data and user_data.data[0].get('user_name'):
                    user_name = user_data.data[0]['user_name']
            except:
                pass
        
        # 直接呼叫 AI
        is_professional = is_professional_question(message)
        ai_response = ask_deepseek(message, user_name, is_professional)
        
        print(f"✅ AI 回覆: {ai_response[:50]}...")
        
        # 儲存回覆給網頁輪詢
        web_pending_replies[user_id] = {"reply": ai_response, "timestamp": time.time()}
        
        return jsonify({'success': True})
        
    except Exception as e:
        print(f"❌ 錯誤: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route("/webchat/reply", methods=['GET'])
def webchat_get_reply():
    """網頁輪詢取得 AI 回覆"""
    user_id = request.args.get('user_id')
    
    if not user_id:
        return jsonify({'has_reply': False, 'error': '缺少 user_id'}), 400
    
    if user_id in web_pending_replies:
        reply_data = web_pending_replies.pop(user_id)
        return jsonify({'has_reply': True, 'reply': reply_data['reply']})
    
    return jsonify({'has_reply': False})

# ==================== 測試端點 ====================
@app.route("/test-push", methods=['GET'])
def test_push():
    send_daily_push()
    return {"status": "push triggered"}, 200

@app.route("/test-line-push", methods=['GET'])
def test_line_push():
    try:
        line_bot_api.push_message('Uaa8ad4daa73c549dd400f9ad2ef92217', TextSendMessage(text="🧪 這是 LINE Push 測試訊息"))
        return {"status": "success"}, 200
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500

@app.route("/", methods=['GET'])
def health():
    supabase_status = "✅ 已連線" if supabase else "⚠️ 未設定"
    scheduler_status = "✅ 運行中" if 'scheduler' in globals() else "⚠️ 未啟動"
    gemini_status = "✅ 已啟用" if gemini_vision_model else "⚠️ 未設定"
    liff_status = "✅ 已設定" if LIFF_ID else "⚠️ 未設定"
    return f"🌿 蕨積最終版（Gemini圖片 + 網頁對話） | Supabase: {supabase_status} | 排程器: {scheduler_status} | Gemini: {gemini_status} | LIFF: {liff_status}", 200

# ==================== 啟動 ====================
if __name__ == "__main__":
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
