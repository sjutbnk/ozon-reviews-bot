import asyncio
from pathlib import Path
from playwright.async_api import async_playwright


async def create_session(output: str = "storage/ozon_state.json") -> None:
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto("https://seller.ozon.ru/")
        print("Выполните вход вручную в открывшемся окне браузера, затем нажмите Enter здесь...")
        await asyncio.to_thread(input)
        await context.storage_state(path=str(target))
        await browser.close()
    print(f"Сессия успешно сохранена в {target}")


if __name__ == "__main__":
    asyncio.run(create_session())


