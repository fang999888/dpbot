# app.py
import os
import json
import requests
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

# ==================== 初始化配置 ====================
app = Flask(__name__)

# 从环境变量读取密钥（Render后台设置）
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')

# 检查必要环境变量是否设置
if not LINE_CHANNEL_SECRET:
    print("错误: LINE_CHANNEL_SECRET 环境变量未设置")
if not LINE_CHANNEL_ACCESS_TOKEN:
    print("错误: LINE_CHANNEL_ACCESS_TOKEN 环境变量未设置")
if not DEEPSEEK_API_KEY:
    print("错误: DEEPSEEK_API_KEY 环境变量未设置")

# 初始化LINE Bot
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# DeepSeek API配置
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

# ==================== 植物专家提示词 ====================
PLANT_EXPERT_PROMPT = """你是一位专业的植物学家助手。请根据用户关于植物的问题，提供准确、科学且易懂的回答。

回答规范：
1. 如果问题是植物鉴别：请描述关键特征（叶形、花色、株型等）
2. 如果问题是养护方法：请说明光照、浇水、土壤、温度等需求
3. 如果问题是病害治疗：请诊断可能病因并提供解决方案
4. 如果问题与植物无关：请礼貌引导回植物话题

请用中文回答，语气友好专业。"""

# ==================== DeepSeek API 调用函数 ====================
def ask_deepseek(question):
    """调用DeepSeek API获取植物知识回复"""
    
    # 检查API Key是否存在
    if not DEEPSEEK_API_KEY:
        return "❌ 系统错误：AI机器人尚未配置API密钥，请联系管理员。"
    
    headers = {
        'Authorization': f'Bearer {DEEPSEEK_API_KEY}',
        'Content-Type': 'application/json'
    }
    
    # 构建完整的提示词
    full_prompt = f"{PLANT_EXPERT_PROMPT}\n\n用户问题：{question}"
    
    data = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "你是一位专业、耐心的植物学专家。"},
            {"role": "user", "content": full_prompt}
        ],
        "max_tokens": 1024,
        "temperature": 0.7,
        "top_p": 0.9,
        "stream": False
    }
    
    try:
        print(f"正在调用DeepSeek API，问题：{question[:50]}...")
        response = requests.post(
            DEEPSEEK_API_URL, 
            headers=headers, 
            data=json.dumps(data), 
            timeout=30  # 增加到30秒，避免超时
        )
        
        # 打印状态码以便调试
        print(f"DeepSeek API 状态码: {response.status_code}")
        
        # 检查HTTP错误
        response.raise_for_status()
        
        # 解析响应
        result = response.json()
        
        # 提取AI回复内容
        if 'choices' in result and len(result['choices']) > 0:
            ai_reply = result['choices'][0]['message']['content'].strip()
            print("DeepSeek API 调用成功")
            return ai_reply
        else:
            print(f"API返回格式异常: {result}")
            return "🤖 AI暂时无法理解这个问题，请换个方式问问看。"
            
    except requests.exceptions.Timeout:
        print("DeepSeek API 超时")
        return "⏰ AI思考时间有点长，请稍后再试。"
    except requests.exceptions.HTTPError as e:
        print(f"DeepSeek API HTTP错误: {e}")
        if response.status_code == 401:
            return "❌ API密钥无效，请检查DeepSeek API Key。"
        elif response.status_code == 429:
            return "⚠️ 调用次数过多，请稍后再试。"
        else:
            return f"🔧 AI服务暂时异常，请稍后重试。"
    except Exception as e:
        print(f"调用DeepSeek API时出现未预期错误: {e}")
        return "🌿 植物专家正在思考中，请稍后再试。"

# ==================== LINE Webhook 路由 ====================
@app.route("/callback", methods=['POST'])
def callback():
    """LINE Webhook 入口 - 必须返回200 OK"""
    
    # 获取请求头中的签名和请求体
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    
    # 调试日志
    print(f"收到LINE请求，签名: {signature[:20]}...")
    print(f"请求体: {body[:200]}...")
    
    try:
        # 验证签名并处理事件
        handler.handle(body, signature)
        print("LINE请求处理成功")
    except InvalidSignatureError:
        print("签名验证失败")
        abort(400)  # 签名无效返回400
    except Exception as e:
        print(f"处理LINE请求时出错: {e}")
        abort(500)
    
    # 必须返回200 OK
    return 'OK', 200

# ==================== 消息事件处理器 ====================
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    """处理用户发送的文本消息"""
    
    user_message = event.message.text
    reply_token = event.reply_token
    user_id = event.source.user_id
    
    print(f"收到用户 {user_id} 的消息: {user_message}")
    
    # 调用DeepSeek获取回复
    ai_response = ask_deepseek(user_message)
    
    # 发送回复给LINE
    try:
        line_bot_api.reply_message(
            reply_token,
            TextSendMessage(text=ai_response)
        )
        print("回复发送成功")
    except Exception as e:
        print(f"发送回复失败: {e}")

# ==================== 健康检查路由（可选，用于uptime监控）====================
@app.route("/", methods=['GET'])
def health_check():
    """健康检查，防止Render休眠"""
    return "植物知识LINE Bot 运行中 🌱", 200

@app.route("/health", methods=['GET'])
def health():
    """健康检查端点"""
    return json.dumps({"status": "alive", "service": "plant-bot"}), 200

# ==================== 启动入口 ====================
# 【重要】这行代码必须放在 if __name__ == "__main__": 里面
# 否则Gunicorn启动时会冲突导致部署失败
if __name__ == "__main__":
    # 本地开发时使用
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
