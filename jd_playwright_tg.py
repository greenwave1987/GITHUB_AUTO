import asyncio
import os
import time
import requests
import sys
from playwright.async_api import async_playwright

# 强制实时刷新日志
sys.stdout.reconfigure(line_buffering=True)

TG_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")
PROXY_URL = os.getenv("PROXY_URL")

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

def send_tg_photo(photo_path, caption):
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto"
    try:
        with open(photo_path, 'rb') as f:
            requests.post(url, data={"chat_id": TG_CHAT_ID, "caption": caption, "parse_mode": "HTML"}, files={"photo": f}, timeout=20)
    except Exception as e:
        log(f"❌ TG 发送失败: {e}")

async def run_jd_login():
    async with async_playwright() as p:
        log("🚀 启动浏览器...")
        
        launch_args = {"headless": True}
        if PROXY_URL:
            launch_args["proxy"] = {"server": PROXY_URL}
            log(f"🌐 代理: {PROXY_URL.split('@')[-1]}")

        browser = await p.chromium.launch(**launch_args)
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        log("🌐 访问京东登录页...")
        try:
            await page.goto("https://passport.jd.com/new/login.aspx", wait_until="domcontentloaded", timeout=60000)
            log("✅ 页面基础加载完成，等待二维码生成...")
            
            # 预留加载时间
            await asyncio.sleep(8)
            
            # --- 关键：移除遮罩层 ---
            log("🚫 清理页面遮挡物...")
            try:
                await page.evaluate("""() => {
                    const selectors = ['.qrcode-msg', '.qrcode-mod .qrcode-msg', '.msg-err'];
                    selectors.forEach(s => {
                        const el = document.querySelector(s);
                        if (el) el.remove();
                    });
                    const img = document.querySelector('#passport-main-qrcode-img');
                    if (img) img.style.opacity = '1';
                }""")
            except Exception as js_e:
                log(f"⚠️ JS 执行略过: {js_e}")

            # 截图二维码区域
            qr_selector = "#passport-main-qrcode-img"
            if await page.is_visible(qr_selector):
                await page.locator(qr_selector).screenshot(path="qrcode.png")
                send_tg_photo("qrcode.png", "✅ <b>京东二维码</b>\n遮罩已尝试强制移除，请扫码")
                log("📸 二维码已发送")
            else:
                await page.screenshot(path="debug.png")
                send_tg_photo("debug.png", "⚠️ <b>未发现二维码</b>\n请查看全屏诊断图")
                log("⚠️ 未发现二维码元素")

            # 监控逻辑
            start_time = time.time()
            while time.time() - start_time < 120:
                if "passport.jd.com" not in page.url or "home" in page.url:
                    log(f"🎊 检测到跳转: {page.url}")
                    break
                await asyncio.sleep(3)

            # 提取 Cookie
            log("🔍 提取 Cookie...")
            await asyncio.sleep(5)
            cookies = await context.cookies()
            ck_dict = {c['name']: c['value'] for c in cookies}
            pt_key = ck_dict.get('pt_key')
            pt_pin = ck_dict.get('pt_pin') or ck_dict.get('pin')

            if pt_key and pt_pin:
                log(f"🎉 成功: {pt_pin}")
                requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", 
                             data={"chat_id": TG_CHAT_ID, "text": f"✅ <b>登录成功</b>\n<code>pt_key={pt_key};pt_pin={pt_pin};</code>", "parse_mode": "HTML"})
            else:
                log("❌ 未能获取 pt_key")

        except Exception as e:
            log(f"❌ 运行崩溃: {e}")
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(run_jd_login())
