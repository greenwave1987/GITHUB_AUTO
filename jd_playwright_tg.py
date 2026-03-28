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
        # 统一全局超时为 100 秒，应对慢速代理
        context.set_default_timeout(100000)
        page = await context.new_page()

        log("🌐 访问京东登录页...")
        await page.goto("https://passport.jd.com/new/login.aspx", wait_until="domcontentloaded")

        # 1. 点击 QQ 登录
        try:
            qq_btn = page.locator('a.pdl:has-text("QQ登录")')
            await qq_btn.wait_for(state="visible", timeout=30000)
            log("🖱️ 点击 QQ 登录按钮...")
            
            # 点击后立即监听 URL 变化，wait_until="commit" 是关键
            await page.click('a.pdl:has-text("QQ登录")')
            log("📡 正在等待 URL 跳转 (commit 模式)...")
            await page.wait_for_url("**/qq.com/**", wait_until="commit", timeout=60000)
            log(f"✅ 已检测到重定向至: {page.url}")
        except Exception as e:
            log(f"❌ 跳转判定失败: {e}")
            await page.screenshot(path="jump_fail.png")
            send_tg_photo("jump_fail.png", "❌ 跳转 QQ 页面超时或失败")
            await browser.close()
            return

        # 2. 寻找 QQ 二维码 (增加循环探测，防止 iframe 还没挂载)
        log("🔍 正在探测 QQ 登录 Iframe...")
        qr_img = None
        iframe_selector = "#ptlogin_iframe"
        
        # 尝试循环 15 次探测 iframe 和里面的二维码
        for i in range(1, 16):
            try:
                # 检查 iframe 是否存在
                if await page.query_selector(iframe_selector):
                    frame = page.frame_locator(iframe_selector)
                    # 尝试寻找二维码图片
                    target_qr = frame.locator("#qrlogin_img")
                    if await target_qr.is_visible():
                        qr_img = target_qr
                        log(f"✅ 第 {i} 次探测：成功发现二维码！")
                        break
                
                # 如果没找到，检查是否需要点击“二维码登录”切换按钮
                # 有些页面默认显示账号密码，需要点一下左下角图标
                switch_btn = page.frame_locator(iframe_selector).locator("#qr_switch_logo")
                if await switch_btn.is_visible():
                    await switch_btn.click()
                    log("🖱️ 检测到账号模式，已手动切换至二维码模式")
            except:
                pass
            
            log(f"⏳ 第 {i} 次探测中，等待二维码渲染...")
            await asyncio.sleep(4)

        if qr_img:
            # 截图并发送
            await qr_img.screenshot(path="qq_qr.png")
            send_tg_photo("qq_qr.png", "🛡️ <b>京东 QQ 扫码</b>\n请尽快扫码完成登录")
        else:
            log("❌ 探测结束，未能捕获二维码")
            await page.screenshot(path="detect_fail.png")
            send_tg_photo("detect_fail.png", "⚠️ <b>无法定位 QQ 二维码</b>\n请检查截图排查是否有验证码拦截")
            await browser.close()
            return

        # 3. 监控扫码结果
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
        pt_pin = ck_dict.get('pt_pin') or ck_dict.get('pin')

        if pt_key:
            res = f"pt_key={pt_key};pt_pin={pt_pin};"
            requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", 
                         data={"chat_id": TG_CHAT_ID, "text": f"✅ <b>QQ 登录成功</b>\n<code>{res}</code>", "parse_mode": "HTML"})
            log(f"🎉 任务圆满完成: {pt_pin}")
        else:
            log("❌ 获取 pt_key 失败")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(run_qq_login())
