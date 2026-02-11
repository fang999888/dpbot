# app.py - 确定性测试版本（完全绕过DeepSeek API）
# 用途：验证LINE Bot部署是否成功，Render环境配置是否正确

import os
import json
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

# ==================== 初始化配置 ====================
app = Flask(__name__)

# 从环境变量读取密钥（Render后台设置）
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')

# 检查必要环境变量是否设置
if not LINE_CHANNEL_SECRET:
    print("错误: LINE_CHANNEL_SECRET 环境变量未设置")
if not LINE_CHANNEL_ACCESS_TOKEN:
    print("错误: LINE_CHANNEL_ACCESS_TOKEN 环境变量未设置")

# 初始化LINE Bot
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# ==================== 测试回复函数（完全绕过DeepSeek）====================
def get_test_reply(user_message):
    """返回详细的测试状态信息，帮助诊断问题"""
    
    # 获取环境变量状态（不显示真实值，只显示是否已设置）
    line_secret_status = "✅ 已设置" if LINE_CHANNEL_SECRET else "❌ 未设置"
    line_token_status = "✅ 已设置" if LINE_CHANNEL_ACCESS_TOKEN else "❌ 未设置"
    deepseek_key = os.getenv('DEEPSEEK_API_KEY')
    deepseek_status = "✅ 已设置" if deepseek_key else "❌ 未设置"
    
    # 构建详细的系统状态报告
    reply = f"""🌱 **LINE Bot 确定性测试成功！**

═══════════════════════
✅ **你的机器人已经完全跑通！**

📋 **系统状态：**
• LINE Secret: {line_secret_status}
• LINE Token: {line_token_status}
• DeepSeek Key: {deepseek_status}

💬 **你刚才发送的消息：**
「{user_message}」

═══════════════════════

🔍 **问题诊断：**
目前你收到「请稍后再试」的原因是：
**DeepSeek 账户余额为 $0.00 USD**

🚀 **解决方案（二选一）：**
1️⃣ **充值 $5**（推荐）
   → 登录 platform.deepseek.com
   → 右上角头像 → 充值
   → 充值后立即生效，无需改代码

2️⃣ **改用免费 Gemini API**
   → 我提供完整替换代码

═══════════════════════
⚡ 当前模式：确定性测试模式
🌿 此回复直接由你的LINE Bot产生
💪 部署成功！接下来只需解决API余额问题
"""
    
    return reply

# ==================== LINE Webhook 路由 ====================
@app.route("/callback", methods=['POST'])
def callback():
    """LINE Webhook 入口"""
    
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    
    print(f"收到LINE请求，签名: {signature[:20]}...")
    
    try:
        handler.handle(body, signature)
        print("LINE请求处理成功")
    except InvalidSignatureError:
        print("签名验证失败")
        abort(400)
    except Exception as e:
        print(f"处理LINE请求时出错: {e}")
        abort(500)
    
    return 'OK', 200

# ==================== 消息事件处理器 ====================
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    """处理用户发送的文本消息 - 测试模式"""
    
    user_message = event.message.text
    reply_token = event.reply_token
    user_id = event.source.user_id
    
    print(f"收到用户 {user_id} 的消息: {user_message}")
    
    # 【关键】直接返回测试回复，完全不调用任何外部API
    test_reply = get_test_reply(user_message)
    
    try:
        line_bot_api.reply_message(
            reply_token,
            TextSendMessage(text=test_reply)
        )
        print("✅ 测试回复发送成功！")
    except Exception as e:
        print(f"❌ 发送回复失败: {e}")

# ==================== 健康检查路由 ====================
@app.route("/", methods=['GET'])
def health_check():
    return "✅ LINE Bot 确定性测试模式运行中 - 2026年2月", 200

@app.route("/health", methods=['GET'])
def health():
    return json.dumps({"status": "alive", "mode": "test"}), 200

# ==================== 启动入口 ====================
if __name__ == "__main__":
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
