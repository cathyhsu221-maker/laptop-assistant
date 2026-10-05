from dotenv import load_dotenv
from google import genai

load_dotenv()                 # 讀取 .env 中的 GEMINI_API_KEY
client = genai.Client()       # 自動使用環境變數中的金鑰

MODEL = "gemini-3.8-flash"

interaction = client.interactions.create(
    model=MODEL,
    input="用三句話解釋什麼是 RAG（檢索增強生成）。",
)
print(interaction.output_text)
