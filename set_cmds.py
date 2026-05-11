import asyncio
from bot.state import bot


async def main():
    await bot.set_my_description(
        "AI-analyst Bitcoin with 25 agents. "
        "Analytics, charts, AI chat, paper trading. "
        "PRO — 80 Stars/month."
    )
    print("Description updated")


asyncio.run(main())
