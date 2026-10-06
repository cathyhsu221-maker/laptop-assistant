from typing import Optional
from dotenv import load_dotenv
from google import genai
from pydantic import BaseModel, Field

load_dotenv()
client = genai.Client()
MODEL = "gemini-3.5-flash-lite"

class LaptopNeed(BaseModel):
    max_price_twd: Optional[int] = Field(None, description="預算上限（新台幣），沒提到則為 null")
    max_weight_kg: Optional[float] = Field(None, description="重量上限（公斤），說『輕』可設 1.5")
    min_ram_gb: Optional[int] = Field(None, description="最低記憶體 GB")
    purpose: str = Field(description="主要用途，例如：文書、寫程式、遊戲、影像剪輯")

PROMPT = """你是筆電選購顧問。請從使用者的需求中抽出條件。
沒有提到的條件一律填 null，不要自行猜測。

使用者需求：{text}"""

def parse_need(text: str) -> LaptopNeed:
    interaction = client.interactions.create(
        model=MODEL,
        input=PROMPT.format(text=text),
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": LaptopNeed.model_json_schema(),
        },
    )
    return LaptopNeed.model_validate_json(interaction.output_text)

if __name__ == "__main__":
    for q in ["兩萬到三萬之間，輕一點，不要超過 1 公斤半，寫程式用",
              "想玩 3A 遊戲",
              "幫我推薦一台筆電"]:
        print(q, "→", parse_need(q))