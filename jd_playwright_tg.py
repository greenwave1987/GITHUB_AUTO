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
        page = await context.new_page()

        log("🌐 访问京东登录页...")
        await page.goto("https://passport.jd.com/new/login.aspx", wait_until="domcontentloaded")
        
        # 等待页面 JS 绑定（很重要）
        await asyncio.sleep(5)

        # 1. 强力触发点击循环
        log("🔍 准备触发 QQ 登录按钮...")
        qr_img_element = None
        iframe_selector = "#ptlogin_iframe"

        for i in range(1, 21):
            curr_url = page.url
            log(f"⏳ 第 {i} 次探测 | URL: {curr_url}")

            # 检查是否已经在 QQ 页面了
            if "qq.com" in curr_url:
                # 尝试探测 iframe 里的二维码
                try:
                    frame = page.frame_locator(iframe_selector)
                    target_qr = frame.locator("#qrlogin_img")
                    if await target_qr.is_visible():
                        qr_img_element = target_qr
                        log("✅ 成功发现二维码！")
                        break
                except: pass
            else:
                # 如果还在京东页面，尝试点击（每 3 次探测尝试点击一次）
                if i % 3 == 1:
                    log("🖱️ 尝试通过 JS 强行触发 QQ 登录按钮...")
                    try:
                        await page.evaluate("""() => {
                            const qqBtn = document.querySelector('a.pdl[onclick*="qqLogin"]');
                            if (qqBtn) {
                                qqBtn.click();
                                return "CLICKED";
                            }
                            return "NOT_FOUND";
                        }""")
                    except Exception as e:
                        log(f"⚠️ 点击尝试异常: {e}")

            await asyncio.sleep(4)

        # 2. 结果处理
        if qr_img_element:
            await qr_img_element.screenshot(path="qq_qr.png")
            send_tg_photo("qq_qr.png", "🛡️ <b>京东 QQ 扫码</b>\n请尽快扫码")
            
            # 3. 监控扫码跳转
            log("📡 监控扫码跳转 (180s)...")
            start_time = time.time()
            while time.time() - start_time < 180:
                if "jd.com" in page.url and "passport" not in page.url:
                    log("🎊 登录成功跳转！")
                    break
                await asyncio.sleep(5)

            # 4. 提取 Cookie
            log("🔍 提取最终 Cookie...")
            await asyncio.sleep(5)
            cookies = await context.cookies()
            ck_dict = {c['name']: c['value'] for c in cookies}
            pt_key = ck_dict.get('pt_key')
            if pt_key:
                res = f"pt_key={pt_key};pt_pin={ck_dict.get('pt_pin', '')};"
                requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", 
                             data={"chat_id": TG_CHAT_ID, "text": f"✅ <b>QQ 登录成功</b>\n<code>{res}</code>", "parse_mode": "HTML"})
        else:
            log("❌ 最终未能捕获二维码")
            await page.screenshot(path="final_fail.png")
            send_tg_photo("final_fail.png", "⚠️ <b>捕获失败</b>\n请检查代理是否屏蔽了跳转请求")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(run_qq_login())
