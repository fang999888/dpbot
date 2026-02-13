import os
import sys
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

# 追蹤 / 加好友
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

    if text.lower() in ["hi", "你好", "help"]:
        reply = "📸 請直接上傳植物照片，我會幫你做初步診斷。"
    else:
        reply = f"💬 你說的是：{text}\n目前我主要看照片喔，請上傳植物圖片。"

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply)
    )

# -------------------------------
# 圖片訊息（V3 模組） 
# -------------------------------
@handler.add(MessageEvent, message=ImageMessage)
def handle_image(event):
    reply_token = event.reply_token
    user_id = event.source.user_id

    # Step1: 立刻回覆「已收到」
    line_bot_api.reply_message(
        reply_token,
        TextSendMessage(
            text="📸 已收到您的植物照片，V3 圖像模組已接上，準備分析中…"
        )
    )

    # Step2: 後續分析 → push
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
# 圖像分析模組（V3 假裝分析）
# -------------------------------
def process_image(user_id, message_id):
    try:
        # 下載圖片
        message_content = line_bot_api.get_message_content(message_id)
        image_bytes = b""
        for chunk in message_content.iter_content():
            image_bytes += chunk

        # ⚠️ 這裡暫時假裝分析
        # 之後可以改成 Gemini Vision 呼叫
        result_text = (
            "🌿 植物辨識完成（V3 模組示範）：\n"
            "植物名稱：鹿角蕨\n"
            "水分狀況：偏乾\n"
            "光照狀況：偏弱\n"
            "健康建議：提高空氣濕度，避免直射西曬，葉片可適度噴水"
        )

        # push 給用戶（replyToken 只能用一次，所以這裡用 push）
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
