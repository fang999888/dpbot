# app.py - 極簡測試版（保證部署成功）
import os
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

# 從環境變數讀取金鑰
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')

# 初始化 LINE Bot
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

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
    """極簡回覆：直接把用戶說的話回傳"""
    user_message = event.message.text
    reply_token = event.reply_token
    
    reply_text = f"🌱 你說：{user_message}\n\n（極簡測試模式，部署成功！）"
    
    line_bot_api.reply_message(
        reply_token,
        TextSendMessage(text=reply_text)
    )

@app.route("/", methods=['GET'])
def health_check():
    return "✅ 極簡測試版運行中", 200

if __name__ == "__main__":
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
