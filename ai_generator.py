import google.generativeai as genai
from config import GEMINI_API_KEY, GEMINI_MODEL
from database import get_style_examples

genai.configure(api_key=GEMINI_API_KEY)
_model = genai.GenerativeModel(GEMINI_MODEL)


async def generate_reply(review_text: str, rating: int) -> str:
    examples = await get_style_examples(limit=15)

    examples_block = ""
    if examples:
        examples_block = "\n\nПримеры ответов в нужном стиле:\n"
        for i, ex in enumerate(examples, 1):
            review_part = f"Отзыв: {ex['review_text']}\n" if ex.get("review_text") else ""
            examples_block += f"\n[{i}]\n{review_part}Ответ: {ex['reply_text']}\n"

    prompt = f"""Ты менеджер маркетплейса Ozon. Тебе нужно ответить на отзыв покупателя.
Строго скопируй стиль из примеров ниже: тон, длину, структуру, использование эмодзи, обращения.
Если примеров нет — пиши вежливо и профессионально.{examples_block}

Напиши ТОЛЬКО текст ответа, без пояснений и кавычек.

Отзыв покупателя (рейтинг {rating}/5):
{review_text}"""

    response = await _model.generate_content_async(prompt)
    return response.text.strip()
