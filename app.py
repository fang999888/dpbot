import os
import sys
import base64
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

LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
GEN_API_KEY = os.getenv("GEN_API_KEY")  # 可以沒有

if not LINE_CHANNEL_SECRET or not LINE_CHANNEL_ACCESS_TOKEN:
    print("❌ LINE 環境變數未設定")
    sys.exit(1)

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

GEN_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"

# ===============================
# Webhook
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
# Follow
# ===============================
@handler.add(FollowEvent)
def handle_follow(event):
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(
            text="👋 歡迎使用「蕨積植物 AI」\n請直接傳送植物照片進行診斷。"
        )
    )

# ===============================
# Text Message（不鸚鵡）
# ===============================
@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    text = event.message.text.strip()

    if "怎麼" in text or "如何" in text:
        reply = "🌿 如果是植物問題，建議直接上傳照片，我可以幫你看得更準確。"
    elif "你好" in text or "hi" in text.lower():
        reply = "你好！我是蕨積植物 AI，可以協助植物辨識與照護建議。"
    else:
        reply = "📸 我目前最擅長看植物照片，歡迎直接上傳圖片。"

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply)
    )

# ===============================
# Image Message（V3）
# ===============================
@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    user_id = event.source.user_id

    # 第一句：一定回
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(
            text="📸 已收到植物照片，V3 圖像模組已接上，分析中…"
        )
    )

    # 第二句：一定 push
    process_image(user_id, event.message.id)

# ===============================
# Postback
# ===============================
@handler.add(PostbackEvent)
def handle_postback(event):
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text="📌 操作已收到，請繼續傳送植物照片。")
    )

# ===============================
# 圖像分析（有 key 用 Gemini，沒 key 用假資料）
# ===============================
def process_image(user_id, message_id):
    try:
        # 下載圖片
        message_content = line_bot_api.get_message_content(message_id)
        image_bytes = b"".join(message_content.iter_content())

        # 沒有 Gemini Key → fallback
        if not GEN_API_KEY:
            result_text = (
                "🌿 植物初步診斷（示範模式）：\n"
                "植物名稱：待辨識\n"
                "水分狀況：可能偏乾\n"
                "光照狀況：建議明亮散射光\n"
                "健康建議：保持通風，避免積水\n\n"
                "ℹ️ 目前尚未啟用進階圖像辨識模組"
            )
        else:
            # 有 key → Gemini Vision
            b64_img = base64.b64encode(image_bytes).decode("utf-8")
            payload = {
                "contents": [{
                    "parts": [
                        {
                            "text": (
                                "你是一位植物專家。請分析此圖並提供："
                                "1.名稱 2.水分狀況 3.光照狀況 4.健康建議。"
                                "請用繁體中文回答。"
                            )
                        },
                        {
                            "inline_data": {
                                "mime_type": "image/jpeg",
                                "data": b64_img
                            }
                        }
                    ]
                }]
            }

            res = requests.post(
                f"{GEN_API_URL}?key={GEN_API_KEY}",
                json=payload,
                timeout=30
            )
            data = res.json()
            result_text = data["candidates"][0]["content"]["parts"][0]["text"]

        line_bot_api.push_message(
            user_id,
            TextSendMessage(text=result_text)
        )

    except Exception as e:
        line_bot_api.push_message(
            user_id,
            TextSendMessage(text=f"⚠️ 分析過程發生錯誤：{e}")
        )

# ===============================
# 啟動
# ===============================
if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
