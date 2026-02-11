# config.py
import os

# 从环境变量读取，或直接写在这里（仅用于测试，生产环境务必用环境变量）
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET', '你的LINE Channel Secret')
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN', '你的LINE Channel Access Token')
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY', '你的DeepSeek API Key')
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
