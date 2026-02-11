# app.py - DeepSeek 繁體中文正式版（充值後可用）
# 功能：LINE 植物知識機器人，全程繁體中文，專業親切

import os
import json
import requests
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

# ==================== 初始化配置 ====================
app = Flask(__name__)

# 從環境變數讀取金鑰（Render 後台設定）
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')

# 檢查必要環境變數是否設定
if not LINE_CHANNEL_SECRET:
    print("錯誤: LINE_CHANNEL_SECRET 環境變數未設定")
if not LINE_CHANNEL_ACCESS_TOKEN:
    print("錯誤: LINE_CHANNEL_ACCESS_TOKEN 環境變數未設定")
if not DEEPSEEK_API_KEY:
    print("錯誤: DEEPSEEK_API_KEY 環境變數未設定")

# 初始化 LINE Bot
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# DeepSeek API 設定
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

# ==================== 植物專家提示詞（繁體中文・台灣用語）====================
PLANT_EXPERT_PROMPT = """你是一位專業的植物學家助手，擅長園藝、植栽養護和植物辨識。

請**全程使用繁體中文（正體中文）**回答，語氣親切自然，像是一位在花市擺攤的老闆娘或園藝達人。

回答規範：
1. 🌱 **植物鑑別**：描述葉子形狀、花朵顏色、植株特徵，告訴用戶這是什麼植物
2. 💧 **養護方法**：說明澆水頻率、日照需求、土壤選擇、適合溫度
3. 🍂 **病害治療**：診斷可能病因，提供實用解決方案
4. 🌿 **繁殖方式**：說明扦插、分株、播種等繁殖技巧
5. ❌ **與植物無關的問題**：統一回覆：「不好意思，我是植物學專家助手，只能回答植物相關的問題喔～🪴 有任何花草樹木、園藝養護的問題都歡迎問我！」

可以適時使用 🌱、🌿、🌸、🌻、🪴、🍀 等表情符號，讓回應更有親切感。"""

# ==================== DeepSeek API 呼叫函式 ====================
def ask_deepseek(question):
    """呼叫 DeepSeek API 取得植物知識回覆"""
    
    # 檢查 API Key 是否存在
    if not DEEPSEEK_API_KEY:
        return "❌ 系統錯誤：AI 機器人尚未設定 API 金鑰，請聯繫管理員。"
    
    headers = {
        'Authorization': f'Bearer {DEEPSEEK_API_KEY}',
        'Content-Type': 'application/json'
    }
    
    # 建構完整的提示詞
    data = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "你是一位專業、耐心的植物學專家。請全程使用繁體中文回答。"},
            {"role": "user", "content": f"{PLANT_EXPERT_PROMPT}\n\n用戶問題：{question}"}
        ],
        "max_tokens": 1024,
        "temperature": 0.7,
        "top_p": 0.9,
        "stream": False
    }
    
    try:
        print(f"正在呼叫 DeepSeek API，問題：{question[:50]}...")
        response = requests.post(
            DEEPSEEK_API_URL, 
            headers=headers, 
            data=json.dumps(data), 
            timeout=30
        )
        
        print(f"DeepSeek API 狀態碼: {response.status_code}")
        response.raise_for_status()
        
        result = response.json()
        
        if 'choices' in result and len(result['choices']) > 0:
            ai_reply = result['choices'][0]['message']['content'].strip()
            print("✅ DeepSeek API 呼叫成功")
            return ai_reply
        else:
            print(f"API 回傳格式異常: {result}")
            return "🤖 AI 暫時無法理解這個問題，請換個方式問問看。"
            
    except requests.exceptions.Timeout:
        print("DeepSeek API 逾時")
        return "⏰ AI 思考時間有點長，請稍後再試。"
    except requests.exceptions.HTTPError as e:
        print(f"DeepSeek API HTTP 錯誤: {e}")
        if response.status_code == 401:
            return "❌ API 金鑰無效，請檢查 DeepSeek API Key。"
        elif response.status_code == 402:
            return "💰 API 餘額不足，請至 DeepSeek 平台儲值。"
        elif response.status_code == 429:
            return "⚠️ 呼叫次數過多，請稍後再試。"
        else:
            return "🔧 AI 服務暫時異常，請稍後重試。"
    except Exception as e:
        print(f"呼叫 DeepSeek API 時出現未預期錯誤: {e}")
        return "🌿 植物專家正在思考中，請稍後再試。"

# ==================== LINE Webhook 路由 ====================
@app.route("/callback", methods=['POST'])
def callback():
    """LINE Webhook 入口"""
    
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    
    return 'OK', 200

# ==================== 訊息事件處理器 ====================
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    """處理用戶發送的文字訊息"""
    
    user_message = event.message.text
    reply_token = event.reply_token
    user_id = event.source.user_id
    
    print(f"收到用戶 {user_id} 的訊息: {user_message}")
    
    # 呼叫 DeepSeek 取得回覆
    ai_response = ask_deepseek(user_message)
    
    # 發送回覆給 LINE
    try:
        line_bot_api.reply_message(
            reply_token,
            TextSendMessage(text=ai_response)
        )
        print("✅ 回覆發送成功")
    except Exception as e:
        print(f"❌ 發送回覆失敗: {e}")

# ==================== 健康檢查路由 ====================
@app.route("/", methods=['GET'])
def health_check():
    """健康檢查，防止 Render 休眠"""
    return "🌱 植物知識 LINE Bot 繁體中文版・運行中", 200

@app.route("/health", methods=['GET'])
def health():
    """健康檢查端點"""
    return json.dumps({"status": "alive", "service": "plant-bot-zh-tw"}), 200

# ==================== 啟動入口 ====================
if __name__ == "__main__":
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
