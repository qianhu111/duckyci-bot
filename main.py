import os
import asyncio
import aiohttp
import logging
from telegram import Bot
from collections import deque

os.makedirs('log', exist_ok=True)  # 确保日志目录存在

# === 日志配置（文件 + 控制台同时记录） ===
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# 创建文件日志处理器
file_handler = logging.FileHandler('log/runtime.log')
file_handler.setLevel(logging.INFO)

# 创建控制台日志处理器
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)

# 设置日志格式
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)

# 添加处理器
logger.addHandler(file_handler)
logger.addHandler(console_handler)

logger.info("程序启动")

# 从环境变量读取配置
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")  # 你的 Telegram 用户 ID 或频道 ID
CHECK_INTERVAL = float(os.getenv("CHECK_INTERVAL", 0.3))  # 轮询间隔，秒（支持小数）
AUTHORIZATION_TOKEN = os.getenv("AUTHORIZATION_TOKEN")

bot = Bot(token=TG_BOT_TOKEN) if TG_BOT_TOKEN else None

MAX_CACHE_SIZE = 1000  # 限制缓存最大数量
last_seen_ids = set()
last_seen_queue = deque(maxlen=MAX_CACHE_SIZE)

# 发送 Telegram 消息
async def send_telegram_message(text):
    if bot and TG_CHAT_ID:
        try:
            await bot.send_message(chat_id=TG_CHAT_ID, text=text)
        except Exception as e:
            logger.error(f"[Telegram发送失败] {e}")

def get_headers():
    return {
        "User-Agent": "Mozilla/5.0",
        "authorization": AUTHORIZATION_TOKEN,
        "Accept-Encoding": "gzip, deflate, br",
        "content-type": "application/json",
        "origin": "https://next.duckyci.com",
        "referer": "https://next.duckyci.com/",
        "accept": "*/*",
    }

# 检查商品商店
async def check_store(session):
    try:
        url = "https://api.duckyci.com/v2/compute/droplet/market/stores"
        headers = get_headers()
        async with session.get(url, headers=headers, timeout=30) as resp:
            if resp.status != 200:
                logger.error(f"[错误] 商品商店请求失败，HTTP状态码: {resp.status}")
                return
            data = await resp.json()

        stores = data.get("data", [])
        new_items = []

        for store in stores:
            item_id = store.get("id")
            if item_id and item_id not in last_seen_ids:
                # 新商品，加入缓存
                last_seen_ids.add(item_id)
                last_seen_queue.append(item_id)
                # 超出缓存大小时，deque自动弹出最旧id，这里同步删除set中对应元素
                if len(last_seen_queue) > MAX_CACHE_SIZE:
                    oldest_id = last_seen_queue.popleft()
                    last_seen_ids.discard(oldest_id)

                name = store.get("name", "未知商品")
                location = store.get("location", "")
                price = store.get("price", "N/A")
                new_items.append(f"📦 {name}\n📍 {location}\n💰 {price}")

        if new_items:
            msg = "🛒 检测到新商品：\n\n" + "\n\n".join(new_items)
            await send_telegram_message(msg)

    except Exception as e:
        logger.error(f"[错误] 商品商店请求或解析失败: {e}")

# 检查“权益与容量”的状态
async def check_capacity(session):
    try:
        url = "https://api.duckyci.com/v2/compute/instances/capacity"
        headers = get_headers()
        async with session.get(url, headers=headers, timeout=30) as resp:
            if resp.status != 200:
                logger.error(f"[错误] 容量检查请求失败，HTTP状态码: {resp.status}")
                return
            data = await resp.json()

        # 访问 'data' 键中的列表
        regions = data.get("data", [])

        if isinstance(regions, list):  # 确保返回的是列表格式
            for region_data in regions:
                # 检查是否存在 'data' 键并且不为 None
                region_details = region_data.get("data", [])
                if not region_details:
                    continue  # 如果没有区域数据，跳过此项

                # 遍历每个区域的数据
                for region in region_details:
                    equity = region.get("equity", False)
                    capacity = region.get("capacity", "insufficient")

                    # 如果"权益"启用且容量不是 "insufficient"（即认为容量足够）
                    if equity and capacity != "insufficient":  
                        region_name = region.get("region", {}).get("display", "未知区域")
                        msg = f"🎉 {region_name} 区域的权益与容量启用！\n容量状态: 足够"
                        await send_telegram_message(msg)
        else:
            logger.error(f"[错误] 返回的 'data' 不是列表格式：{regions}")

    except Exception as e:
        logger.error(f"[错误] 容量检查请求或解析失败: {e}")

# 主循环
async def main_loop():
    async with aiohttp.ClientSession() as session:
        while True:
            # 同时检查商品和容量状态
            await asyncio.gather(
                check_store(session),  # 商品商店监控
                check_capacity(session),  # 容量状态监控
            )
            await asyncio.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    logger.info("🔍 开始异步监控商品商店和容量状态...")
    asyncio.run(main_loop())
