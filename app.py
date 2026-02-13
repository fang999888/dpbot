import os
import sys
import requests
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, ImageMessage,
    FollowEvent, PostbackEvent, TextSendMessage
)

# ===============================
# 基本設定
# ===============================
app = Flask(__name__)

LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET", "")
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
GEN_API_KEY = os.getenv("GEN_API_KEY", "")

if not LINE_CHANNEL_SECRET or not LINE_CHANNEL_ACCESS_TOKEN or not GEN_API_KEY:
    print("❌ 環境變數未完整設定")
    sys.exit(1)

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

GEN_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"

# ===============================
# Webhook 入口
# ===============================
@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"

# ===============================
# 事件處理
# ===============================
@handler.add(FollowEvent)
def handle_follow(event):
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text="👋 歡迎使用 蕨積植物 AI\n請直接傳送植物照片進行診斷。")
    )

# -------------------------------
# 文字訊息（智慧回覆）
# -------------------------------
@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    user_text = event.message.text.strip()
    
    # 這裡用 Gemini 產生智慧回覆
    prompt = f"你是一位友善植物助理，請用繁體中文回覆，避免重複使用者文字：'{user_text}'"
    
    try:
        res = requests.post(
            f"{GEN_API_URL}?key={GEN_API_KEY}",
            json={
                "contents": [{"parts":[{"text": prompt}]}]
            },
            timeout=25
        )
        data = res.json()
        reply = data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        reply = "抱歉，我暫時無法回答，請稍後再試。"

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply)
    )

# -------------------------------
# 圖片訊息 → Gemini Vision
# -------------------------------
@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    reply_token = event.reply_token
    user_id = event.source.user_id

    # Step1: 立即回覆已收到
    line_bot_api.reply_message(
        reply_token,
        TextSendMessage(text="📸 已收到您的植物照片，V3 圖像模組已接上，正在分析中…")
    )

    # Step2: 後台處理圖片
    process_image(user_id, event.message.id)

# -------------------------------
# Postback
# -------------------------------
@handler.add(PostbackEvent)
def handle_postback(event):
    data = event.postback.data
    if data == "retry":
        reply = "🔁 請重新上傳一張清楚的植物照片"
    else:
        reply = f"📌 收到操作：{data}"
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply)
    )

# -------------------------------
# 圖像分析函數
# -------------------------------
def process_image(user_id, message_id):
    try:
        # 下載圖片
        message_content = line_bot_api.get_message_content(message_id)
        image_bytes = b""
        for chunk in message_content.iter_content():
            image_bytes += chunk

        # 轉 base64
        import base64
        b64_img = base64.b64encode(image_bytes).decode("utf-8")

        # Gemini Vision API call
        prompt = (
            "你是一位植物專家。請分析此圖並提供："
            "1.名稱 2.水分狀況(充足/建議補水/過濕) "
            "3.光照狀況(良好/偏弱) 4.健康建議。"
            "請用親切的繁體中文回答。"
        )
        payload = {
            "contents": [{
                "parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type":"image/jpeg","data":b64_img}}
                ]
            }]
        }

        res = requests.post(f"{GEN_API_URL}?key={GEN_API_KEY}", json=payload, timeout=30)
        data = res.json()
        result_text = data["candidates"][0]["content"]["parts"][0]["text"]

        # push 給用戶（第二則回覆）
        line_bot_api.push_message(
            user_id,
            TextSendMessage(text=result_text)
        )

    except Exception as e:
        line_bot_api.push_message(
            user_id,
            TextSendMessage(text=f"⚠️ 圖像分析失敗：{str(e)}")
        )

# ===============================
# Render / 本機啟動
# ===============================
if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
