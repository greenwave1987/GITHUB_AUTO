import asyncio
import os
import time
import requests
import re
from playwright.async_api import async_playwright

# 从环境变量获取配置
TG_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_ID = os.getenv("TG_USER_ID")

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")

def send_tg_photo(photo_path, caption):
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto"
    try:
        with open(photo_path, 'rb') as f:
            requests.post(url, data={"chat_id": TG_ID, "caption": caption, "parse_mode": "HTML"}, files={"photo": f}, timeout=10)
    except Exception as e:
        log(f"TG 发送失败: {e}")

async def run_jd_login():
    async with async_playwright() as p:
        log("启动浏览器...")
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        log("访问京东登录页面...")
        await page.goto("https://passport.jd.com/new/login.aspx", wait_until="networkidle")

        # 定位二维码并截图
        qr_selector = "#passport-main-qrcode-img"
        try:
            await page.wait_for_selector(qr_selector, timeout=15000)
            # 给二维码一点点加载时间，防止截到空白
            await asyncio.sleep(2)
            await page.locator(qr_selector).screenshot(path="qrcode.png")
            log("二维码截图成功，发送至 Telegram...")
            send_tg_photo("qrcode.png", "📌 <b>GitHub Playwright 登录</b>\n请在 2 分钟内完成扫码确认")
        except Exception as e:
            log(f"获取二维码失败: {e}")
            await browser.close()
            return

        log("等待页面跳转 (监控登录状态)...")
        try:
            # 这里的逻辑是：一直等到 URL 不再包含 passport.jd.com，或者进入了 home/list 等页面
            await page.wait_for_url(lambda url: "passport.jd.com" not in url or "home" in url, timeout=120000)
            log("检测到跳转！正在抓取 Cookie...")
            
            # 强制等待 5 秒确保所有跳转和内部计算完成
            await asyncio.sleep(5)
            
            cookies = await context.cookies()
            ck_dict = {c['name']: c['value'] for c in cookies}
            
            pt_key = ck_dict.get('pt_key')
            pt_pin = ck_dict.get('pt_pin') or ck_dict.get('pin')

            if pt_key and pt_pin:
                res_msg = f"✅ <b>京东登录成功</b>\n\n<code>pt_key={pt_key};pt_pin={pt_pin};</code>"
                requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", data={"chat_id": TG_ID, "text": res_msg, "parse_mode": "HTML"})
                log(f"成功抓取 Cookie: {pt_pin}")
            else:
                # 备选：打印所有拿到的关键 key，辅助排查
                keys = list(ck_dict.keys())
                log(f"未发现 pt_key，当前可用键: {keys}")
                requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", 
                             data={"chat_id": TG_ID, "text": f"⚠️ 登录跳转成功但未发现 pt_key\nKeys: {keys}", "parse_mode": "HTML"})
                
        except Exception as e:
            log(f"扫码超时或异常: {e}")

        await browser.close()
        log("浏览器已关闭")

if __name__ == "__main__":
    if TG_TOKEN and TG_ID:
        asyncio.run(run_jd_login())
    else:
        log("错误: 缺少 TG 环境变量配置")
