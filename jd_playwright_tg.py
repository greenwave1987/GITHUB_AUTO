import asyncio
import os
import time
import requests
import sys
from playwright.async_api import async_playwright

sys.stdout.reconfigure(line_buffering=True)

# 基础配置
TG_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")
DEFAULT_PROXY = "socks5://greenwave1987.iask.in:19873"
PROXY_URL = os.getenv("PROXY_URL", DEFAULT_PROXY)

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
        log("🚀 启动浏览器...")
        launch_args = {"headless": True}
        if PROXY_URL:
            launch_args["proxy"] = {"server": PROXY_URL}

        browser = await p.chromium.launch(**launch_args)
        context = await browser.new_context(viewport={'width': 1280, 'height': 800})
        page = await context.new_page()

        log("🌐 访问京东登录页...")
        await page.goto("https://passport.jd.com/new/login.aspx", wait_until="domcontentloaded")

        # 1. 点击 QQ 登录按钮
        try:
            log("🖱️ 正在定位 QQ 登录图标并点击...")
            # 京东登录页的 QQ 登录通常是一个包含 'QQ' 字样的链接或图标
            qq_btn = page.locator("a:has-text('QQ'), .pdl:has-text('QQ')").first
            await qq_btn.click()
            await asyncio.sleep(5) # 等待跳转或弹窗
        except Exception as e:
            log(f"❌ 点击 QQ 登录失败: {e}")
            await page.screenshot(path="click_fail.png")
            send_tg_photo("click_fail.png", "❌ 点击 QQ 登录失败")
            await browser.close()
            return

        # 2. 定位 QQ 二维码 (通常在 iframe 中)
        log("🔍 正在寻找 QQ 二维码元素...")
        qr_selector = ".qrlogin_img_out"
        
        # 因为 QQ 登录可能是新页面或 iframe，我们需要遍历所有 frames
        qr_found = False
        for _ in range(10): # 循环尝试 10 次
            # 检查主页面和所有 iframe
            frames = page.frames
            for frame in frames:
                try:
                    # 尝试在 frame 中定位元素
                    target = frame.locator(qr_selector)
                    if await target.is_visible():
                        log(f"✅ 在 Frame [{frame.name}] 中发现二维码")
                        # 确保图片加载完成 (src 存在)
                        img_locator = frame.locator(f"{qr_selector} img")
                        await img_locator.wait_for(state="visible", timeout=10000)
                        
                        # 截图
                        await img_locator.screenshot(path="qq_qr.png")
                        send_tg_photo("qq_qr.png", "🛡️ <b>京东 - QQ 扫码登录</b>\n请使用手机 QQ 扫码")
                        qr_found = True
                        break
                except:
                    continue
            
            if qr_found: break
            log("⏳ 尚未发现二维码，等待重试...")
            await asyncio.sleep(3)

        if not qr_found:
            log("❌ 最终未能获取到 QQ 二维码")
            await page.screenshot(path="qq_fail.png")
            send_tg_photo("qq_fail.png", "❌ <b>QQ 二维码加载失败</b>\n请检查代理或截图状态")
            await browser.close()
            return

        # 3. 实时监控跳转
        log("📡 开始监控 QQ 扫码后的页面跳转...")
        start_time = time.time()
        while time.time() - start_time < 180:
            # 判定跳转回京东且包含登录特征
            if "jd.com" in page.url and "passport" not in page.url:
                log(f"🎉 登录成功跳转: {page.url}")
                break
            await asyncio.sleep(5)

        # 4. 提取 Cookie
        await asyncio.sleep(5)
        cookies = await context.cookies()
        ck_dict = {c['name']: c['value'] for c in cookies}
        pt_key = ck_dict.get('pt_key')
        pt_pin = ck_dict.get('pt_pin')

        if pt_key:
            log("🎊 获取 pt_key 成功！")
            requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", 
                         data={"chat_id": TG_CHAT_ID, "text": f"✅ <b>QQ 登录成功</b>\n<code>pt_key={pt_key};pt_pin={pt_pin};</code>", "parse_mode": "HTML"})
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(run_qq_login())
