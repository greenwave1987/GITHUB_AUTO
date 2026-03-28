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
            requests.post(url, data={"chat_id": TG_CHAT_ID, "caption": caption, "parse_mode": "HTML"}, files={"photo": f}, timeout=30)
    except: pass

async def run_qq_login():
    async with async_playwright() as p:
        log("🚀 启动 Chromium...")
        launch_args = {"headless": True}
        if PROXY_URL:
            launch_args["proxy"] = {"server": PROXY_URL}

        browser = await p.chromium.launch(**launch_args)
        # 允许极长的超时时间 (120秒)，应对慢速代理
        context = await browser.new_context(viewport={'width': 1280, 'height': 800})
        context.set_default_timeout(120000) 
        page = await context.new_page()

        # --- 1. 访问京东首页 (带重试逻辑) ---
        success = False
        for attempt in range(1, 4):
            try:
                log(f"🌐 正在访问京东登录页 (第 {attempt} 次尝试)...")
                # 使用 wait_until="commit" 只要服务器响应就继续，不等待 DOM
                await page.goto("https://passport.jd.com/new/login.aspx", wait_until="commit", timeout=90000)
                success = True
                break
            except Exception as e:
                log(f"⚠️ 访问超时: {str(e)[:50]}，正在重试...")
                await asyncio.sleep(5)

        if not success:
            log("❌ 经过多次重试依然无法打开页面，请检查代理是否在线。")
            await browser.close()
            return

        # --- 2. 强力触发点击与探测循环 ---
        log("🔍 进入循环探测与点击模式...")
        qr_img_element = None
        iframe_selector = "#ptlogin_iframe"

        for i in range(1, 25): # 增加到 25 次，约 100 秒总长
            curr_url = page.url
            
            # 如果进入了 QQ 页面
            if "qq.com" in curr_url:
                try:
                    # 探测 iframe
                    frame = page.frame_locator(iframe_selector)
                    target_qr = frame.locator("#qrlogin_img")
                    if await target_qr.is_visible():
                        qr_img_element = target_qr
                        log("✅ 成功发现 QQ 二维码！")
                        break
                    
                    # 检查是否需要手动切换到二维码模式
                    switch_btn = frame.locator("#qr_switch_logo")
                    if await switch_btn.is_visible():
                        await switch_btn.click()
                        log("🖱️ 已手动切换至扫码模式")
                except: pass
            else:
                # 还没跳转，尝试点击 (每 3 次探测点一次)
                if i % 3 == 1:
                    log(f"🖱️ 第 {i} 次探测：尝试通过 JS 触发 QQ 登录按钮...")
                    try:
                        await page.evaluate("""() => {
                            const qqBtn = document.querySelector('a.pdl[onclick*="qqLogin"]');
                            if (qqBtn) qqBtn.click();
                        }""")
                    except: pass

            await asyncio.sleep(4)

        # --- 3. 结果处理 ---
        if qr_img_element:
            await qr_img_element.screenshot(path="qq_qr.png")
            send_tg_photo("qq_qr.png", "🛡️ <b>京东 QQ 扫码</b>\n请尽快扫码")
            
            # 监控登录成功
            log("📡 监控登录状态...")
            start_time = time.time()
            while time.time() - start_time < 180:
                if "jd.com" in page.url and "passport" not in page.url:
                    log("🎊 登录成功！")
                    break
                await asyncio.sleep(5)

            # 提取 Cookie
            await asyncio.sleep(5)
            cookies = await context.cookies()
            ck_dict = {c['name']: c['value'] for c in cookies}
            pt_key = ck_dict.get('pt_key')
            if pt_key:
                res = f"pt_key={pt_key};pt_pin={ck_dict.get('pt_pin', '')};"
                requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", 
                             data={"chat_id": TG_CHAT_ID, "text": f"✅ <b>QQ 登录成功</b>\n<code>{res}</code>", "parse_mode": "HTML"})
        else:
            log("❌ 最终未捕获到二维码")
            await page.screenshot(path="final_debug.png")
            send_tg_photo("final_debug.png", "⚠️ 无法获取二维码，代理可能太慢。")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(run_qq_login())
