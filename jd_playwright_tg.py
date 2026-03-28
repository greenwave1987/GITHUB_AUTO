import asyncio
import os
import time
import requests
import sys
from playwright.async_api import async_playwright

# 实时日志输出
sys.stdout.reconfigure(line_buffering=True)

TG_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")
PROXY_URL = os.getenv("PROXY_URL", "socks5://greenwave1987.iask.in:19873")

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

def send_tg_photo(photo_path, caption):
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto"
    try:
        with open(photo_path, 'rb') as f:
            requests.post(url, data={"chat_id": TG_CHAT_ID, "caption": caption, "parse_mode": "HTML"}, files={"photo": f}, timeout=25)
    except: pass

async def run_qq_login():
    async with async_playwright() as p:
        log("🚀 启动 Chromium...")
        launch_args = {"headless": True}
        if PROXY_URL:
            launch_args["proxy"] = {"server": PROXY_URL}

        browser = await p.chromium.launch(**launch_args)
        context = await browser.new_context(viewport={'width': 1280, 'height': 800})
        context.set_default_timeout(90000)
        page = await context.new_page()

        log("🌐 访问京东登录页...")
        try:
            await page.goto("https://passport.jd.com/new/login.aspx", wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            log(f"❌ 访问超时: {e}")
            await browser.close()
            return

        # 1. 直接在当前窗口点击 QQ 登录
        try:
            qq_btn_selector = 'a.pdl:has-text("QQ登录")'
            log("🖱️ 等待并点击 QQ 登录按钮 (当前窗口跳转)...")
            await page.wait_for_selector(qq_btn_selector, state="visible", timeout=30000)
            
            # 点击并等待 URL 发生变化（跳转到 qq.com）
            await page.click(qq_btn_selector)
            log("📡 已点击，正在等待页面重定向至 QQ...")
            
            # 等待 URL 包含 qq.com
            await page.wait_for_url("**/qq.com/**", timeout=60000)
            log(f"✅ 已进入 QQ 登录页: {page.url}")
        except Exception as e:
            log(f"❌ 跳转 QQ 页面失败: {e}")
            await page.screenshot(path="jump_error.png")
            send_tg_photo("jump_error.png", "❌ 点击 QQ 登录后未成功跳转")
            await browser.close()
            return

        # 2. 定位 iframe 里的二维码
        log("🔍 正在寻找 QQ 二维码 (Iframe)...")
        try:
            # 这里的 iframe ID 在重定向模式下通常保持一致
            iframe_selector = "#ptlogin_iframe"
            await page.wait_for_selector(iframe_selector, timeout=45000)
            
            frame = page.frame_locator(iframe_selector)
            
            # 寻找二维码图片元素
            qr_img_selector = "#qrlogin_img"
            await frame.locator(qr_img_selector).wait_for(state="visible", timeout=30000)
            
            # 截图
            log("📸 成功捕获 QQ 二维码！")
            await frame.locator(qr_img_selector).screenshot(path="qq_qr.png")
            send_tg_photo("qq_qr.png", "🛡️ <b>京东 QQ 扫码 (重定向版)</b>\n请尽快扫码")
            
        except Exception as e:
            log(f"❌ 获取二维码失败: {e}")
            await page.screenshot(path="qq_page_diag.png")
            send_tg_photo("qq_page_diag.png", f"❌ QQ 页面二维码加载异常")
            await browser.close()
            return

        # 3. 监控跳转回京东 (登录成功)
        log("📡 正在监控扫码结果...")
        start_time = time.time()
        while time.time() - start_time < 180:
            # 如果 URL 回到了 jd.com 且不再是 passport，说明成功
            if "jd.com" in page.url and "passport" not in page.url:
                log(f"🎊 登录成功，当前 URL: {page.url}")
                break
            await asyncio.sleep(5)

        # 4. 提取 Cookie
        log("🔍 提取 pt_key...")
        await asyncio.sleep(5)
        cookies = await context.cookies()
        ck_dict = {c['name']: c['value'] for c in cookies}
        
        pt_key = ck_dict.get('pt_key')
        pt_pin = ck_dict.get('pt_pin') or ck_dict.get('pin')

        if pt_key:
            res = f"pt_key={pt_key};pt_pin={pt_pin};"
            requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", 
                         data={"chat_id": TG_CHAT_ID, "text": f"✅ <b>QQ 登录成功</b>\n<code>{res}</code>", "parse_mode": "HTML"})
        else:
            log("⚠️ 未能提取到 Cookie，请检查跳转是否彻底完成")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(run_qq_login())
