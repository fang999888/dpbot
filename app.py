import os
import sys
import base64
from flask import Flask, request, abort

from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError

from linebot.models import (
    MessageEvent,
    TextMessage,
    ImageMessage,
    FollowEvent,
    PostbackEvent,
    TextSendMessage
)

# ===============================
# 基本設定
# ===============================

app = Flask(__name__)

LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET", "")
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")

if not LINE_CHANNEL_SECRET or not LINE_CHANNEL_ACCESS_TOKEN:
    print("❌ LINE 環境變數未設定")
    sys.exit(1)

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

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
# 文字訊息
# -------------------------------

@handler.add(MessageEvent, message=TextMessage)
def handle_text(event):
    text = event.message.text.strip()

    if text in ["hi", "你好", "help"]:
        reply = "📸 請直接上傳植物照片，我會幫你做初步診斷。"
    else:
        reply = "我目前主要看照片喔 🌿\n請上傳植物圖片。"

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply)
    )

# -------------------------------
# 圖片訊息（v3 最小版）
# -------------------------------

@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    message_id = event.message.id
    message_content = line_bot_api.get_message_content(message_id)

    image_bytes = b""
    for chunk in message_content.iter_content():
        image_bytes += chunk

    # 這裡先不真的送 Gemini
    # 只確認「圖片事件流程正常」

    reply_text = (
        "📷 已收到植物照片\n\n"
        "（v3 圖像辨識模組已接上，後續可整合 Gemini Vision）"
    )

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )

# -------------------------------
# Postback（這次炸掉的來源）
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

# ===============================
# Render / 本機啟動
# ===============================

if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
