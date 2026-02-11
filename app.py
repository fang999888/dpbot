# app.py - DeepSeek 繁體中文精簡版（無 Supabase）
import os
import json
import requests
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

# 環境變數
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')

# 初始化 LINE
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# DeepSeek API
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

# ==================== 提示詞（精簡互動版）====================
PLANT_EXPERT_PROMPT = """你是一位風趣的植物達人，綽號「小植」。

**回答風格**：
- ✅ 字數**控制在50~100字以內**
- ✅ 開頭直接講重點，不用客套
- ✅ 結尾加一個**反問**，像朋友聊天
- ✅ 偶爾用 🌱🌿🌸🪴 表情符號
- ✅ 全程繁體中文

**範例**：
用戶：多肉怎麼澆水？
你：土乾透才澆！夏天大概10天1次，冬天2週1次💧
你家的多肉現在多久澆一次呀？

用戶：這是什麼植物？
你：看葉子應該是**龜背芋**，那種大洞洞是它的招牌喔！
你家也有養龜背芋嗎？🌿

**非植物問題**：
一律回：「我只懂植物啦～問我花草樹木都可以唷🪴」
"""

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
    except requests.exceptions.HTTPError as e:
        if response.status_code == 402:
            return "💰 DeepSeek 餘額不足，請至平台儲值～"
        else:
            return "🌿 小植正在澆花，晚點回你喔～"
    except Exception as e:
        print(f"API錯誤: {e}")
        return "🌿 小植正在澆花，晚點回你喔～"

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    
    return 'OK', 200

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_message = event.message.text
    reply_token = event.reply_token
    
    ai_response = ask_deepseek(user_message)
    
    line_bot_api.reply_message(
        reply_token,
        TextSendMessage(text=ai_response)
    )

@app.route("/", methods=['GET'])
def health_check():
    return "🌱 植物機器人 DeepSeek 版運行中", 200

if __name__ == "__main__":
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
