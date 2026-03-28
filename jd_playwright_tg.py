import asyncio
import os
import time
import requests
import sys
from playwright.async_api import async_playwright

# 强制实时打印日志
sys.stdout.reconfigure(line_buffering=True)

# 变量名更新
TG_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")

def log(msg):
    timestamp = time.strftime('%H:%M:%S')
    print(f"[{timestamp}] {msg}", flush=True)

def send_tg_photo(photo_path, caption):
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto"
    try:
        with open(photo_path, 'rb') as f:
            resp = requests.post(url, data={
                "chat_id": TG_CHAT_ID, 
                "caption": caption, 
                "parse_mode": "HTML"
            }, files={"photo": f}, timeout=15)
            if resp.status_code == 200:
                log("✅ TG 二维码发送成功")
            else:
                log(f"❌ TG 发送失败 (Status: {resp.status_code}): {resp.text}")
    except Exception as e:
        log(f"❌ TG 请求异常: {e}")

async def run_jd_login():
    async with async_playwright() as p:
        log("🚀 启动 Chromium 浏览器...")
        browser = await p.chromium.launch(headless=True)
        
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 720},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        log("🌐 访问京东登录页面...")
        await page.goto("https://passport.jd.com/new/login.aspx", wait_until="networkidle")

        qr_selector = "#passport-main-qrcode-img"
        try:
            log("⏳ 等待二维码加载...")
            await page.wait_for_selector(qr_selector, timeout=20000)
            await asyncio.sleep(2)
            await page.locator(qr_selector).screenshot(path="qrcode.png")
            
            log(f"📸 截图成功，发送至 TG Chat: {TG_CHAT_ID}")
            send_tg_photo("qrcode.png", "🔔 <b>京东扫码登录</b>\n请立即扫码并在手机端确认！")
            
        except Exception as e:
            log(f"❌ 获取二维码失败: {e}")
            await browser.close()
            return

        log("📡 等待手机端扫码确认 (2分钟超时)...")
        try:
            # 监控 URL 变化，判定登录成功
            await page.wait_for_url(
                lambda url: "passport.jd.com" not in url or "home" in url or ("jd.com" in url and "login" not in url), 
                timeout=120000
            )
            
            log(f"🎊 检测到跳转: {page.url}")
            log("⏳ 等待 Cookie 注入...")
            await asyncio.sleep(5)
            
            log("🔍 提取登录凭证...")
            cookies = await context.cookies()
            ck_dict = {c['name']: c['value'] for c in cookies}
            
            pt_key = ck_dict.get('pt_key')
            pt_pin = ck_dict.get('pt_pin') or ck_dict.get('pin')

            if pt_key and pt_pin:
                ck_str = f"pt_key={pt_key};pt_pin={pt_pin};"
                log(f"🎉 登录成功: {pt_pin}")
                requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", 
                             data={"chat_id": TG_CHAT_ID, "text": f"✅ <b>登录成功</b>\n\n<code>{ck_str}</code>", "parse_mode": "HTML"})
            else:
                keys = [k for k in ck_dict.keys() if k in ['pin', 'wskey', 'pt_key', 'pt_pin', 'unick']]
                log(f"⚠️ 关键 Cookie 缺失，当前键: {keys}")
                requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", 
                             data={"chat_id": TG_CHAT_ID, "text": f"⚠️ <b>登录跳转成功但 pt_key 缺失</b>\nKeys: {keys}", "parse_mode": "HTML"})

        except Exception as e:
            log(f"⏰ 流程结束: {e}")

        await browser.close()
        log("🏁 任务完成。")

if __name__ == "__main__":
    if TG_TOKEN and TG_CHAT_ID:
        asyncio.run(run_jd_login())
    else:
        log("❌ 错误: 环境变量 TG_BOT_TOKEN 或 TG_CHAT_ID 缺失")
