# app.py
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import requests
import json
import config  # 导入配置文件

app = Flask(__name__)

# 初始化LINE Bot
line_bot_api = LineBotApi(config.LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(config.LINE_CHANNEL_SECRET)

# 植物知识专家系统提示词
PLANT_EXPERT_PROMPT = """你是一位专业的植物学家助手。请根据用户关于植物的问题，提供准确、科学且易懂的回答。
回答需基于植物学知识，内容可以包括：植物名称鉴别、养护方法（浇水、光照、土壤）、常见病害、繁殖方式、生态习性等。
如果问题涉及植物识别，请描述关键特征或建议提供更多信息（如叶形、花色）。
如果用户问题与植物无关，请礼貌地提醒并引导至植物相关话题。
请用中文回答，保持友好和专业。
用户问题："""

def ask_deepseek(question):
    """调用DeepSeek API的函数"""
    headers = {
        'Authorization': f'Bearer {config.DEEPSEEK_API_KEY}',
        'Content-Type': 'application/json'
    }
    
    # 构建包含专业提示词的完整问题
    full_prompt = PLANT_EXPERT_PROMPT + question
    
    data = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "你是一位专业且热情的植物学家助手。"},
            {"role": "user", "content": full_prompt}
        ],
        "max_tokens": 1024,
        "temperature": 0.7
    }
    
    try:
        response = requests.post(config.DEEPSEEK_API_URL, 
                                headers=headers, 
                                data=json.dumps(data), 
                                timeout=10)
        response.raise_for_status()  # 检查HTTP错误
        result = response.json()
        return result['choices'][0]['message']['content'].strip()
    except requests.exceptions.Timeout:
        return "抱歉，AI思考时间有点长，请稍后再试。"
    except Exception as e:
        print(f"调用DeepSeek API时出错: {e}")
        return "暂时无法获取植物知识，请稍后重试。"

@app.route("/callback", methods=['POST'])
def callback():
    """LINE Webhook 回调入口"""
    signature = request.headers['X-Line-Signature']  # 获取签名
    body = request.get_data(as_text=True)  # 获取请求体
    
    try:
        handler.handle(body, signature)  # 验证签名并处理事件
    except InvalidSignatureError:
        abort(400)  # 签名无效则返回400错误
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    """处理用户文本消息"""
    user_message = event.message.text  # 获取用户消息
    reply_token = event.reply_token  # 获取回复令牌
    
    # 调用DeepSeek获取植物知识回复
    ai_response = ask_deepseek(user_message)
    
    # 构建回复消息并传回LINE
    reply_message = TextSendMessage(text=ai_response)
    line_bot_api.reply_message(reply_token, reply_message)

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)
