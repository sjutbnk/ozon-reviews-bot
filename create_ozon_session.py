import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

async def create_session(output='storage/ozon_state.json'):
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False); context = await browser.new_context(); page = await context.new_page()
        await page.goto('https://seller.ozon.ru/'); print('Выполните вход вручную, затем нажмите Enter здесь.'); await asyncio.to_thread(input)
        await context.storage_state(path=output); await browser.close()
if __name__ == '__main__': asyncio.run(create_session())

