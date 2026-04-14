# app.py - 蕨積專業顧問版（含工程級天氣預警）
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
from flask_cors import CORS
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
CORS(app)

# ==================== 環境變數 ====================
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
CWA_API_KEY = os.getenv('CWA_API_KEY')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
LIFF_ID = os.getenv('LIFF_ID', '')

# 台灣時區
TAIPEI_TZ = pytz.timezone('Asia/Taipei')

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

# ==================== 獲取當前台灣時間 ====================
def get_current_time():
    """取得當前台灣時間 (Asia/Taipei)"""
    now = datetime.now(TAIPEI_TZ)
    return now

def get_current_date_str():
    """取得當前日期字串，例如：2026年4月14日"""
    now = get_current_time()
    return f"{now.year}年{now.month}月{now.day}日"

def get_current_weekday():
    """取得當前星期幾"""
    weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    now = get_current_time()
    return weekdays[now.weekday()]

def get_full_datetime_str():
    """取得完整日期時間字串"""
    now = get_current_time()
    return f"{now.year}年{now.month}月{now.day}日 {now.hour}:{now.minute:02d}"

# ==================== 網頁對話暫存區 ====================
web_pending_replies = {}

# ==================== 蕨積賣萌圖片回覆庫 ====================
SORRY_MESSAGES = [
    "🌿 這我沒辦法讀，很抱歉～你要不要直接問老闆？",
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
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json'
        }
        response = requests.get(url, headers=headers, timeout=15, verify=False)
        response.raise_for_status()
        data = response.json()

        if 'records' not in data or not data['records'].get('location'):
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

def get_weather_backup(city):
    """備用天氣查詢 - 使用不同的 API 端點"""
    if not CWA_API_KEY:
        return {"success": False, "message": "未設定金鑰"}
    
    city_code_map = {
        "台北": "6300000", "新北": "6500000", "桃園": "6800000",
        "台中": "6600000", "台南": "6700000", "高雄": "6400000",
        "基隆": "6900000", "新竹": "6700000", "苗栗": "6600000",
        "彰化": "6600000", "南投": "6600000", "雲林": "6600000",
        "嘉義": "6600000", "屏東": "6600000", "宜蘭": "6700000",
        "花蓮": "6700000", "台東": "6700000"
    }
    
    location_code = city_code_map.get(city, "6300000")
    url = f"https://opendata.cwa.gov.tw/api/v1/rest/datastore/O-A0001-001?Authorization={CWA_API_KEY}&format=JSON&locationId={location_code}"
    
    try:
        response = requests.get(url, timeout=15, verify=False)
        data = response.json()
        
        if 'records' in data and data['records'].get('location'):
            loc = data['records']['location'][0]
            weather_elem = loc['weatherElement']
            
            temp = None
            weather_status = "多雲"
            for elem in weather_elem:
                if elem['elementName'] == 'TEMP':
                    temp = float(elem['elementValue'])
                if elem['elementName'] == 'Weather':
                    weather_status = elem['elementValue']
            
            return {
                "success": True,
                "city": city,
                "status": weather_status,
                "max_temp": int(temp) if temp else 25,
                "min_temp": int(temp) - 2 if temp else 23,
                "rain_prob": 30
            }
    except Exception as e:
        print(f"備用天氣API錯誤: {e}")
    
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

# ==================== 工程級天氣風險評估 ====================
def get_engineering_weather_risk(city):
    """根據天氣數據評估戶外工程風險等級"""
    weather = get_weather(city)
    
    # 如果主要API失敗，嘗試備援API
    if not weather['success']:
        weather = get_weather_backup(city)
    
    if not weather['success']:
        return None
    
    rain_prob = weather.get('rain_prob', 0)
    max_temp = weather.get('max_temp', 25)
    min_temp = weather.get('min_temp', 20)
    status = weather.get('status', '')
    
    # 風險等級判斷
    risk_level = "低風險"
    risk_icon = "🟢"
    restrictions = []
    suggestions = []
    
    # 降雨風險
    if rain_prob >= 80:
        risk_level = "高風險"
        risk_icon = "🔴"
        restrictions.append("❌ 戶外植生牆施工暫停")
        restrictions.append("❌ 高空作業禁止")
        restrictions.append("❌ 電氣設備禁止戶外使用")
        suggestions.append("✅ 改為室內碳盤查資料整理")
        suggestions.append("✅ 進行植生牆養護計畫檢討")
        suggestions.append("✅ 檢查工地排水系統")
    elif rain_prob >= 50:
        if risk_level == "低風險":
            risk_level = "中風險"
            risk_icon = "🟡"
        restrictions.append("⚠️ 戶外施作建議攜帶遮雨設備")
        restrictions.append("⚠️ 注意介質含水量控制")
        restrictions.append("⚠️ 電器設備做好防水")
        suggestions.append("✅ 可進行短暫戶外作業")
        suggestions.append("✅ 優先安排室內工作")
    
    # 高溫風險
    if max_temp >= 35:
        if risk_level == "低風險":
            risk_level = "中風險"
            risk_icon = "🟡"
        restrictions.append("⚠️ 高溫警戒，注意工人熱危害")
        restrictions.append("⚠️ 植栽水分蒸散快速")
        restrictions.append("⚠️ 每小時強制休息10分鐘")
        suggestions.append("✅ 避開11:00-15:00戶外作業")
        suggestions.append("✅ 增加澆水頻率")
        suggestions.append("✅ 提供充足飲用水")
    elif max_temp >= 32:
        restrictions.append("☀️ 氣溫偏高，定時補充水分")
        suggestions.append("✅ 建議每2小時休息一次")
    
    # 低溫風險
    if min_temp <= 10:
        if risk_level == "低風險":
            risk_level = "中風險"
            risk_icon = "🟡"
        restrictions.append("❄️ 低溫警戒，植物可能進入休眠")
        restrictions.append("❄️ 注意工人保暖")
        suggestions.append("✅ 熱帶植物移入室內")
        suggestions.append("✅ 避免夜間澆水")
        suggestions.append("✅ 戶外作業穿戴保暖裝備")
    
    # 強風/暴雨風險
    if "大雨" in status or "雷雨" in status or "豪雨" in status:
        if risk_level == "低風險":
            risk_level = "中風險"
            risk_icon = "🟡"
        restrictions.append("💨 強陣風/豪雨風險")
        restrictions.append("💨 注意鷹架固定安全")
        suggestions.append("✅ 檢查臨時構造物固定")
        suggestions.append("✅ 暫停高空吊掛作業")
    
    return {
        "city": weather['city'],
        "status": status,
        "max_temp": max_temp,
        "min_temp": min_temp,
        "rain_prob": rain_prob,
        "risk_level": risk_level,
        "risk_icon": risk_icon,
        "restrictions": restrictions,
        "suggestions": suggestions
    }

def format_engineering_weather_message(risk_data, user_name=None):
    """格式化工程天氣預警訊息"""
    if not risk_data:
        return "🌿 暫時無法取得天氣資料，請稍後再試"
    
    name_prefix = f"{user_name}，" if user_name else ""
    
    message = f"""🏗️ **工程級天氣預警** {risk_data['risk_icon']}

{name_prefix}{risk_data['city']} 今日天氣：
🌤️ {risk_data['status']}
🌡️ {risk_data['min_temp']}°C - {risk_data['max_temp']}°C
🌧️ 降雨機率 {risk_data['rain_prob']}%

📊 **風險等級：{risk_data['risk_level']}**

"""

    if risk_data['restrictions']:
        message += "🚧 **作業限制：**\n" + "\n".join(risk_data['restrictions']) + "\n\n"
    
    if risk_data['suggestions']:
        message += "💡 **專業建議：**\n" + "\n".join(risk_data['suggestions']) + "\n\n"
    
    message += "🌿 蕨積關心您的工地安全與植物健康"
    
    return message

def get_quick_construction_advice(city, user_name=None):
    """快速施工建議（簡短版）"""
    risk_data = get_engineering_weather_risk(city)
    if not risk_data:
        return "🌿 暫時無法取得天氣資料"
    
    name_prefix = f"{user_name}，" if user_name else ""
    
    if risk_data['risk_level'] == "低風險":
        return f"✅ {name_prefix}{risk_data['city']} 今日適合戶外施工，{risk_data['status']}，降雨機率{risk_data['rain_prob']}%"
    elif risk_data['risk_level'] == "中風險":
        return f"⚠️ {name_prefix}{risk_data['city']} 今日施工需注意：{risk_data['restrictions'][0] if risk_data['restrictions'] else '天氣不穩定'}"
    else:
        return f"❌ {name_prefix}{risk_data['city']} 今日不建議戶外施工，{risk_data['restrictions'][0] if risk_data['restrictions'] else '天氣條件不佳'}"

# ==================== 專業關鍵字權重 ====================
PROFESSIONAL_WEIGHTS = {
    "多肉": 3, "龜背芋": 3, "琴葉榕": 3, "虎尾蘭": 3, 
    "蕨類": 3, "觀音蓮": 3, "蔓綠絨": 3, "彩葉芋": 3, "竹芋": 3,
    "發財樹": 3, "幸福樹": 3, "龍血樹": 3, "黃金葛": 3, "吊蘭": 3,
    "常春藤": 3, "薄荷": 3, "迷迭香": 3, "薰衣草": 3, "羅勒": 3,
    "辣椒": 3, "番茄": 3, "草莓": 3, "藍莓": 3,
    "植生牆": 3, "綠牆": 3, "垂直綠化": 3,
    "軟": 2, "黃": 2, "黑": 2, "爛": 2, "枯": 2, "掉": 2, "垂": 2,
    "軟葉": 3, "發黃": 3, "變黃": 3, "黑斑": 3, "爛根": 3,
    "枯萎": 3, "掉葉": 3, "徒長": 3, "化水": 3, "曬傷": 3,
    "斑": 2, "洞": 2, "蟲": 3, "介殼蟲": 3, "紅蜘蛛": 3,
    "蚜蟲": 3, "粉蝨": 3, "黴": 2, "鏽": 2,
    "澆水": 2, "施肥": 2, "換盆": 2, "修剪": 2, "扦插": 2,
    "分株": 2, "播種": 2, "授粉": 2,
    "日照": 1, "光照": 1, "通風": 1, "濕度": 1, "介質": 1,
    "土": 1, "盆": 1, "水": 1,
    "碳": 3, "碳盤查": 3, "溫室氣體": 3, "碳排放": 3, "ISO": 3,
    "14064": 3, "14067": 3, "範疇": 3, "碳足跡": 3, "碳中和": 3,
    "減碳": 3, "淨零": 3, "永續": 2, "ESG": 3,
    "職安": 3, "營造": 3, "工地": 2, "安全": 2, "證照": 2,
    "工程": 2, "施工": 2, "工安": 3,
    "天氣": 2, "下雨": 2, "溫度": 2, "降雨": 2, "氣象": 2,
    "學名": 2, "科屬": 2, "原生地": 2, "休眠期": 2, "生長期": 2,
    "病蟲害": 2, "防治": 2, "治療": 2, "急救": 2, "診斷": 2,
    "怎麼辦": 1, "怎麼救": 1, "為什麼": 1, "正常嗎": 1, "生病嗎": 1,
    "什麼問題": 1, "怎麼了": 1, "如何": 1, "怎樣": 1
}

def is_professional_question(text):
    if len(text) <= 2:
        return False
    return True

# ==================== 蕨積專業顧問人設（含當前時間）====================
def get_professional_prompt(user_name=None):
    current_date = get_current_date_str()
    current_weekday = get_current_weekday()
    current_time = get_full_datetime_str()
    
    name_part = f"用戶叫{user_name}，" if user_name else ""
    return f"""你是「蕨積」，一位跨領域的專業顧問。{name_part}

【重要資訊 - 當前時間】
今天是 {current_date}，{current_weekday}，當前時間為 {current_time}。
請務必使用這個正確的日期來回答任何與日期、時間相關的問題！

【你的專業背景】
🔥 碳管理：熟悉 ISO 14064-1 (組織溫室氣體盤查)、ISO 14067 (產品碳足跡)
🔥 職安衛：具備營造業職業安全衛生證照，熟悉工地安全管理
🔥 植物養護：8年植生牆與植物養護經驗，擅長植物診斷、修剪、照顧
🔥 工程整合：植生牆系統設計、施工、維護一條龍
🔥 生活提案：結合碳、植物、工程、教學，推廣綠色生活

【回答風格】
- 專業、準確、實用
- 結合你的跨領域經驗（碳+植物+工程）
- 字數控制在80-200字
- 可以適度使用🌿、💚等植物符號，但不要過度

【鐵則】
✅ 保持專業、親切、實用
✅ 善用你的跨領域知識
✅ 回答日期問題時，直接說「今天是 {current_date}，{current_weekday}」
❌ 不要過度使用表情符號
"""

# ==================== DeepSeek 呼叫 ====================
def ask_deepseek(question, user_name=None, is_professional=False):
    if not DEEPSEEK_API_KEY:
        return "🌿 蕨積去曬太陽了"
    headers = {'Authorization': f'Bearer {DEEPSEEK_API_KEY}', 'Content-Type': 'application/json'}
    
    system_prompt = get_professional_prompt(user_name)
    data = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question}
        ],
        "max_tokens": 500,
        "temperature": 0.3
    }
    
    try:
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=data, timeout=30)
        response.raise_for_status()
        return response.json()['choices'][0]['message']['content'].strip()
    except Exception as e:
        print(f"DeepSeek錯誤: {e}")
        return "🌿 蕨積暫時無法回應，請稍後再試"

# ==================== 用戶管理 ====================
def get_or_create_user(user_id):
    if not supabase: return None
    try:
        result = supabase.table('users').select('*').eq('user_id', user_id).execute()
        if result.data:
            return result.data[0]
        else:
            new_user = {'user_id': user_id, 'user_name': None, 'city': None, 'created_at': datetime.now(TAIPEI_TZ).isoformat(), 'last_active': datetime.now(TAIPEI_TZ).isoformat()}
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
        supabase.table('users').update({'last_active': datetime.now(TAIPEI_TZ).isoformat()}).eq('user_id', user_id).execute()
    except:
        pass

# ==================== 訂閱管理 ====================
def subscribe_user(user_id):
    if not supabase: return False
    try:
        existing = supabase.table('subscribers').select('*').eq('user_id', user_id).execute()
        if not existing.data:
            data = {'user_id': user_id, 'subscribed_at': datetime.now(TAIPEI_TZ).isoformat(), 'last_push_date': None, 'is_active': True}
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

# ==================== 每日植物小知識 ====================
_last_fact = None

def get_daily_plant_fact():
    global _last_fact
    today_yday = get_current_time().timetuple().tm_yday
    backup_index = today_yday % len(LOCAL_FACTS)
    backup_fact = LOCAL_FACTS[backup_index]

    try:
        headers = {'Authorization': f'Bearer {DEEPSEEK_API_KEY}', 'Content-Type': 'application/json'}
        fact_prompt = f"""今天是 {get_current_date_str()}，請給一則「20字內」的搞笑植物知識，要讓人會心一笑。範例：
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
    
    today_taipei = get_current_time()
    today_str = today_taipei.date().isoformat()
    today_display = get_current_date_str()
    
    print(f"🔍 今天的日期 (台北): {today_str}")
    try:
        response = supabase.table('subscribers').select('*').eq('is_active', True).execute()
        all_active = response.data
        subscribers = [user for user in all_active if user.get('last_push_date') != today_str]
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

            message_text = f"🌱 **蕨積早安 - {today_display}**\n\n{daily_fact}{weather_text}"

            try:
                line_bot_api.push_message(user_id, TextSendMessage(text=message_text))
                supabase.table('subscribers').update({'last_push_date': today_str}).eq('user_id', user_id).execute()
                success_count += 1
            except Exception as e:
                print(f"❌ 推播失敗 {user_id}: {e}")

        print(f"📊 推播完成：成功 {success_count} / 總共 {len(subscribers)}")
    except Exception as e:
        print(f"❌ 推播處理例外: {e}")

# ==================== 排程器 ====================
def init_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(func=send_daily_push, trigger=CronTrigger(hour=8, minute=0, timezone=TAIPEI_TZ), id='daily_push', replace_existing=True)
    scheduler.start()
    print("✅ 排程器已啟動，每天 08:00 (台北時間) 推播")
    atexit.register(lambda: scheduler.shutdown())
    return scheduler

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
    today = get_current_date_str()
    if supabase:
        get_or_create_user(user_id)
        subscribe_user(user_id)
    welcome_msg = f"""🌿 **蕨積專業顧問來啦！** 今天是 {today}

我是跨領域專業顧問，專精：
✅ 碳盤查 (ISO 14064-1 / 14067)
✅ 營造業職安衛
✅ 植物養護 & 植生牆 (8年資歷)
✅ 工程整合 & 生活提案

**常用指令：**
🏗️ `工程天氣` - 工程級天氣預警
✅ `可以施工嗎` - 快速判斷施工適宜性
🌤️ `台北天氣` - 一般天氣查詢
📅 `今天幾號` - 查詢日期
📍 `我在台北` - 設定位置
📬 `訂閱` - 每日植物小知識

直接說你的問題，我會用專業角度回答！"""
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
    message_id = event.message.id

    try:
        message_content = line_bot_api.get_message_content(message_id)
        image_bytes = b''
        for chunk in message_content.iter_content():
            image_bytes += chunk

        if gemini_vision_model:
            result = analyze_image_with_gemini(image_bytes)
            if result:
                line_bot_api.reply_message(reply_token, TextSendMessage(text=result))
                print(f"📸 用戶 {user_id} 圖片識別成功")
                return

        reply_text = random.choice(SORRY_MESSAGES)
        line_bot_api.reply_message(reply_token, TextSendMessage(text=reply_text))
        print(f"📸 用戶 {user_id} 圖片識別失敗，改用賣萌")

    except Exception as e:
        print(f"圖片處理失敗: {e}")
        reply_text = random.choice(SORRY_MESSAGES)
        line_bot_api.reply_message(reply_token, TextSendMessage(text=reply_text))

    finally:
        if supabase:
            update_last_active(user_id)

# ==================== 文字訊息處理（LINE Bot）====================
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

    # 除錯指令
    if user_message == "我的ID":
        line_bot_api.reply_message(reply_token, TextSendMessage(text=f"你的 LINE Bot User ID: {user_id}"))
        return
    
    # ==================== 日期/時間查詢 ====================
    if user_message in ["今天幾號", "今天是幾號", "今天日期", "日期", "幾月幾號", "今天星期幾", "星期幾"]:
        today = get_current_date_str()
        weekday = get_current_weekday()
        reply_text = f"🌿 今天是 {today}，{weekday}"
        line_bot_api.reply_message(reply_token, TextSendMessage(text=reply_text))
        return
    
    if user_message in ["現在幾點", "幾點", "現在時間", "時間"]:
        now = get_current_time()
        reply_text = f"🌿 現在是 {now.hour}:{now.minute:02d}"
        line_bot_api.reply_message(reply_token, TextSendMessage(text=reply_text))
        return

    # ==================== 工程級天氣預警（核心新功能）====================
    if user_message in ["工程天氣", "工地天氣", "施工天氣", "天氣預警", "工程級天氣"]:
        city = None
        if user_data and user_data.get('city'):
            city = user_data.get('city')
        
        if not city:
            # 嘗試從訊息中提取城市（但這裡已經是純指令，沒有城市）
            pass
        
        if city:
            risk_data = get_engineering_weather_risk(city)
            reply = format_engineering_weather_message(risk_data, user_name)
            line_bot_api.reply_message(reply_token, TextSendMessage(text=reply))
            return
        else:
            reply = """🏗️ 請先設定工地位置，例如：
「我在台北」
「我住台中」

設定完成後，輸入「工程天氣」即可獲得完整風險評估"""
            line_bot_api.reply_message(reply_token, TextSendMessage(text=reply))
            return

    # 快速施工判斷
    if user_message in ["可以施工嗎", "今天能施工嗎", "適合施工嗎", "能施工嗎"]:
        city = user_data.get('city') if user_data else None
        if city:
            reply = get_quick_construction_advice(city, user_name)
            line_bot_api.reply_message(reply_token, TextSendMessage(text=reply))
            return
        else:
            reply = "🌿 請先告訴我你的位置，例如「我在台北」"
            line_bot_api.reply_message(reply_token, TextSendMessage(text=reply))
            return

    # 指定城市的工程天氣查詢（如：台北工程天氣）
    engineering_weather_match = re.match(r"^(.{2,3})(?:工程天氣|工地天氣|施工天氣)$", user_message)
    if engineering_weather_match:
        city = engineering_weather_match.group(1)
        # 驗證城市是否有效
        valid_city = None
        for c in CITY_MAPPING.keys():
            if c in city:
                valid_city = c
                break
        if valid_city:
            risk_data = get_engineering_weather_risk(valid_city)
            reply = format_engineering_weather_message(risk_data, user_name)
            line_bot_api.reply_message(reply_token, TextSendMessage(text=reply))
            # 順便記住這個城市
            if supabase:
                update_user_city(user_id, valid_city)
            return
        else:
            reply = "🌿 請輸入正確的城市名稱，例如：台北工程天氣"
            line_bot_api.reply_message(reply_token, TextSendMessage(text=reply))
            return

    # ==================== 訂閱相關 ====================
    if supabase:
        if user_message in ["取消訂閱", "停止推播", "unsubscribe"]:
            unsubscribe_user(user_id)
            line_bot_api.reply_message(reply_token, TextSendMessage(text="📭 已取消訂閱，想回來說「訂閱」即可"))
            return
        if user_message in ["訂閱", "subscribe"]:
            subscribe_user(user_id)
            line_bot_api.reply_message(reply_token, TextSendMessage(text="📬 訂閱成功！每天 08:00 發送植物小常識！"))
            return

    # ==================== 記住名字 ====================
    name_match = re.match(r"^我叫(.+)$", user_message) or re.match(r"^我是(.+)$", user_message)
    if name_match:
        name = name_match.group(1).strip()
        if name and supabase:
            update_user_name(user_id, name)
            reply_text = f"🌿 哈囉 {name}！我是蕨積專業顧問，有什麼可以幫你的？\n\n💡 試試輸入「工程天氣」或「可以施工嗎」"
            line_bot_api.reply_message(reply_token, TextSendMessage(text=reply_text))
            return

    # ==================== 設定城市 ====================
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
            reply_text = f"""🌿 記住了，你在 {valid_city}！

🏗️ 試試輸入「工程天氣」查看工地風險評估
🌤️ 或輸入「{valid_city}天氣」查詢一般天氣
✅ 輸入「可以施工嗎」快速判斷"""
            line_bot_api.reply_message(reply_token, TextSendMessage(text=reply_text))
            return
        else:
            reply_text = "🌿 請輸入台灣縣市名稱，例如：我在台北、我住台中"
            line_bot_api.reply_message(reply_token, TextSendMessage(text=reply_text))
            return

    # ==================== 一般天氣查詢 ====================
    if any(keyword in user_message for keyword in ["天氣", "下雨", "澆水"]):
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
                today = get_current_date_str()
                if user_name:
                    reply = f"{user_name}，今天是 {today}\n\n{weather['city']}今天{weather['status']}，最高{weather['max_temp']}度，最低{weather['min_temp']}度，降雨機率{weather['rain_prob']}%\n\n{advice}\n\n🏗️ 想了解工地風險？輸入「工程天氣」"
                else:
                    reply = f"今天是 {today}\n\n{weather['city']}今天{weather['status']}，最高{weather['max_temp']}度，最低{weather['min_temp']}度，降雨機率{weather['rain_prob']}%\n\n{advice}\n\n🏗️ 想了解工地風險？輸入「工程天氣」"
                line_bot_api.reply_message(reply_token, TextSendMessage(text=reply))
                if user_data and not user_data.get('city') and supabase:
                    update_user_city(user_id, city)
                return
            else:
                # 主要API失敗，嘗試備援
                weather_backup = get_weather_backup(city)
                if weather_backup['success']:
                    today = get_current_date_str()
                    reply = f"今天是 {today}\n\n{weather_backup['city']}目前{weather_backup['status']}，氣溫約{weather_backup['max_temp']}°C"
                    line_bot_api.reply_message(reply_token, TextSendMessage(text=reply))
                    return
                else:
                    line_bot_api.reply_message(reply_token, TextSendMessage(text=weather['message']))
                return
        else:
            reply = "🌿 你想查哪個城市的天氣？直接告訴我城市名稱，例如「台北天氣」\n\n🏗️ 或先設定位置「我在台北」"
            line_bot_api.reply_message(reply_token, TextSendMessage(text=reply))
            return

    # ==================== 主動查詢小知識 ====================
    if any(keyword in user_message for keyword in ["知識", "常識", "小知識", "冷知識"]):
        fact = get_random_local_fact()
        line_bot_api.reply_message(reply_token, TextSendMessage(text=fact))
        return
    
    # ==================== 指令說明 ====================
    if user_message in ["指令", "help", "說明", "功能"]:
        help_text = """🌿 **蕨積專業顧問 - 指令說明**

🏗️ **工程級天氣**
`工程天氣` - 完整工地風險評估
`可以施工嗎` - 快速施工判斷
`台北工程天氣` - 查詢指定城市

🌤️ **一般天氣**
`台北天氣` - 城市天氣查詢
`我在台北` - 設定位置

📅 **日期時間**
`今天幾號` - 查詢日期
`現在幾點` - 查詢時間

📬 **訂閱功能**
`訂閱` - 每日植物小知識
`取消訂閱` - 停止推播

🌱 **其他**
`我叫小美` - 讓我記住你
`小知識` - 隨機植物冷知識

有問題直接問，我會用專業角度回答！"""
        line_bot_api.reply_message(reply_token, TextSendMessage(text=help_text))
        return

    # ==================== 專業 AI 回覆 ====================
    print(f"📝 用戶 {user_id} | 問題: {user_message}")
    ai_response = ask_deepseek(user_message, user_name, is_professional=True)
    line_bot_api.reply_message(reply_token, TextSendMessage(text=ai_response))

# ==================== 網頁對話 API ====================
@app.route("/webchat/send", methods=['POST'])
def webchat_send():
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        message = data.get('message', '').strip()
        
        print(f"📤 [網頁] 收到訊息 - user_id: {user_id}, message: {message}")
        
        if not user_id or not message:
            return jsonify({'success': False, 'error': '缺少參數'}), 400
        
        user_name = None
        if supabase:
            try:
                user_data = supabase.table('users').select('user_name').eq('user_id', user_id).execute()
                if user_data.data and user_data.data[0].get('user_name'):
                    user_name = user_data.data[0]['user_name']
            except:
                pass
        
        ai_response = ask_deepseek(message, user_name, is_professional=True)
        
        print(f"✅ [網頁] AI 回覆: {ai_response[:100]}...")
        
        web_pending_replies[user_id] = {"reply": ai_response, "timestamp": time.time()}
        print(f"💾 [網頁] 已存入暫存區")
        
        return jsonify({'success': True})
        
    except Exception as e:
        print(f"❌ [網頁] 錯誤: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route("/webchat/reply", methods=['GET'])
def webchat_get_reply():
    user_id = request.args.get('user_id')
    
    if not user_id:
        return jsonify({'has_reply': False, 'error': '缺少 user_id'}), 400
    
    if user_id in web_pending_replies:
        reply_data = web_pending_replies.pop(user_id)
        print(f"📤 [網頁] 送出回覆給 {user_id}")
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

@app.route("/test-datetime", methods=['GET'])
def test_datetime():
    """測試日期時間函數是否正常"""
    return {
        "current_date": get_current_date_str(),
        "current_weekday": get_current_weekday(),
        "current_time": get_full_datetime_str(),
        "timestamp": get_current_time().isoformat()
    }, 200

@app.route("/test-weather", methods=['GET'])
def test_weather():
    """測試天氣API連線狀況"""
    city = request.args.get('city', '台北')
    
    result = {
        "server_time": get_full_datetime_str(),
        "city": city,
        "cwa_api_key_exists": bool(CWA_API_KEY),
        "primary_api_result": None,
        "backup_api_result": None
    }
    
    # 測試主要API
    try:
        city_name = CITY_MAPPING.get(city, city)
        url = f"https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-C0032-001?Authorization={CWA_API_KEY}&format=JSON&locationName={city_name}"
        r = requests.get(url, timeout=15, verify=False)
        result["primary_api_status"] = r.status_code
        result["primary_api_response_length"] = len(r.text)
        if r.status_code == 200:
            data = r.json()
            result["primary_api_has_records"] = 'records' in data
    except Exception as e:
        result["primary_api_error"] = str(e)
    
    # 測試備援API
    try:
        url2 = f"https://opendata.cwa.gov.tw/api/v1/rest/datastore/O-A0001-001?Authorization={CWA_API_KEY}&format=JSON"
        r2 = requests.get(url2, timeout=15, verify=False)
        result["backup_api_status"] = r2.status_code
    except Exception as e:
        result["backup_api_error"] = str(e)
    
    return jsonify(result)

@app.route("/", methods=['GET'])
def health():
    supabase_status = "✅ 已連線" if supabase else "⚠️ 未設定"
    scheduler_status = "✅ 運行中" if 'scheduler' in globals() else "⚠️ 未啟動"
    gemini_status = "✅ 已啟用" if gemini_vision_model else "⚠️ 未設定"
    liff_status = "✅ 已設定" if LIFF_ID else "⚠️ 未設定"
    now = get_current_date_str()
    return f"🌿 蕨積專業顧問版 | 現在時間: {now} | Supabase: {supabase_status} | 排程器: {scheduler_status} | Gemini: {gemini_status} | LIFF: {liff_status}", 200

# ==================== 啟動 ====================
if __name__ == "__main__":
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
