import asyncio
import os
import time
import requests
import sys
from playwright.async_api import async_playwright

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
        # 允许极长的超时，防止脚本中途崩溃
        context.set_default_timeout(120000)
        page = await context.new_page()

        log("🌐 访问京东登录页...")
        await page.goto("https://passport.jd.com/new/login.aspx", wait_until="domcontentloaded")

        # 1. 点击 QQ 登录 (不再使用 wait_for_url)
        try:
            qq_btn_selector = 'a.pdl:has-text("QQ登录")'
            await page.wait_for_selector(qq_btn_selector, state="visible", timeout=30000)
            log("🖱️ 点击 QQ 登录按钮，启动异步探测...")
            await page.click(qq_btn_selector)
        except Exception as e:
            log(f"❌ 初始页面异常: {e}")
            await browser.close()
            return

        # 2. 强力探测循环：无视 URL 跳转状态，直接找二维码
        log("🔍 进入扫描探测模式...")
        qr_img = None
        iframe_selector = "#ptlogin_iframe"
        
        # 尝试 20 次探测，每次间隔 4 秒，总计 80 秒
        for i in range(1, 21):
            curr_url = page.url
            log(f"⏳ 第 {i} 次探测 | 当前 URL: {curr_url}")
            
            try:
                # 方案 A: 检查是否存在 QQ 登录的 iframe
                if await page.query_selector(iframe_selector):
                    frame = page.frame_locator(iframe_selector)
                    
                    # 探测二维码图片
                    target_qr = frame.locator("#qrlogin_img")
                    if await target_qr.is_visible():
                        qr_img = target_qr
                        log("✅ 成功！在 Iframe 中发现 QQ 二维码")
                        break
                
                # 方案 B: 检查是否需要切换模式
                switch_btn = page.frame_locator(iframe_selector).locator("#qr_switch_logo")
                if await switch_btn.is_visible():
                    await switch_btn.click()
                    log("🖱️ 已手动切换至扫码模式")
            except Exception as e:
                pass # 忽略探测过程中的微小报错
            
            # 如果 12 次探测（约 50 秒）还没到，但截图已经显示有了，可能是 Playwright 缓存问题
            # 这里我们不报错，继续等
            await asyncio.sleep(4)

        if qr_img:
            # 截取二维码并发送
            await qr_img.screenshot(path="qq_qr.png")
            send_tg_photo("qq_qr.png", "🛡️ <b>京东 QQ 扫码</b>\n请尽快扫码")
        else:
            log("❌ 探测超时，未能在页面中提取到二维码元素")
            await page.screenshot(path="final_debug.png")
            send_tg_photo("final_debug.png", "⚠️ <b>探测失败</b>\n请检查截图，看页面是否卡在了加载圈或验证码。")
            await browser.close()
            return

        # 3. 监控扫码跳转
        log("📡 监控登录跳转 (180s)...")
        start_time = time.time()
        while time.time() - start_time < 180:
            if "jd.com" in page.url and "passport" not in page.url:
                log("🎊 登录成功！")
                break
            await asyncio.sleep(5)

        # 4. 提取 Cookie
        log("🔍 提取 Cookie...")
        await asyncio.sleep(5)
        cookies = await context.cookies()
        ck_dict = {c['name']: c['value'] for c in cookies}
        pt_key = ck_dict.get('pt_key')
        
        if pt_key:
            res = f"pt_key={pt_key};pt_pin={ck_dict.get('pt_pin')};"
            requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", 
                         data={"chat_id": TG_CHAT_ID, "text": f"✅ <b>QQ 登录成功</b>\n<code>{res}</code>", "parse_mode": "HTML"})
        else:
            log("❌ 未获取到 pt_key")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(run_qq_login())
