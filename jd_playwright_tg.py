import asyncio
import os
import time
import requests
import sys
import re
from playwright.async_api import async_playwright

# 强制实时刷新日志
sys.stdout.reconfigure(line_buffering=True)

# 环境变量
TG_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")
PROXY_URL = os.getenv("PROXY_URL", "socks5://greenwave1987.iask.in:19873")

# 初始化 TG 消息偏移量
last_tg_offset = 0

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

def send_tg_msg(text):
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": TG_CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=20)
    except: pass

def send_tg_photo(photo_path, caption):
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto"
    try:
        with open(photo_path, 'rb') as f:
            requests.post(url, data={"chat_id": TG_CHAT_ID, "caption": caption, "parse_mode": "HTML"}, files={"photo": f}, timeout=30)
    except: pass

def update_tg_offset():
    global last_tg_offset
    url = f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates"
    try:
        resp = requests.get(url, params={"timeout": 0}, timeout=15).json()
        if resp.get("ok") and resp.get("result"):
            last_tg_offset = resp["result"][-1]["update_id"]
            log(f"📡 TG 消息 Offset 已初始化为: {last_tg_offset}")
    except: pass

def get_tg_code():
    global last_tg_offset
    url = f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates"
    try:
        resp = requests.get(url, params={"offset": last_tg_offset + 1, "timeout": 20}, timeout=35).json()
        if resp.get("ok") and resp.get("result"):
            for item in resp["result"]:
                msg = item.get("message", {})
                text = msg.get("text", "")
                last_tg_offset = item["update_id"]
                code_match = re.search(r'^\d{6}$', text.strip())
                if code_match:
                    return code_match.group()
    except: pass
    return None

async def run_qq_login():
    async with async_playwright() as p:
        log("🚀 启动 Chromium...")
        launch_args = {"headless": True}
        if PROXY_URL:
            launch_args["proxy"] = {"server": PROXY_URL}

        browser = await p.chromium.launch(**launch_args)
        context = await browser.new_context(viewport={'width': 1280, 'height': 800})
        context.set_default_timeout(180000)
        page = await context.new_page()

        # 1. 访问京东
        log("🌐 正在访问京东登录页...")
        await page.goto("https://passport.jd.com/new/login.aspx", wait_until="commit")

        # 2. 点击 QQ 登录
        log("🔍 触发 QQ 登录跳转...")
        for i in range(1, 11):
            if "qq.com" not in page.url:
                await page.evaluate("() => { const b = document.querySelector('a.pdl[onclick*=\"qqLogin\"]'); if(b) b.click(); }")
                await asyncio.sleep(6)
            else: break

        # --- 核心修复：提取并发送二维码 ---
        log("📸 正在提取 QQ 二维码...")
        qr_sent = False
        for _ in range(10): # 循环探测 iframe 里的二维码
            try:
                frame = page.frame_locator("#ptlogin_iframe")
                qr_img = frame.locator("#qrlogin_img")
                if await qr_img.is_visible():
                    await qr_img.screenshot(path="qq_qr.png")
                    send_tg_photo("qq_qr.png", "🛡️ <b>京东 QQ 扫码</b>\n请尽快完成扫码！")
                    qr_sent = True
                    log("✅ 二维码已发送至 Telegram")
                    break
            except: pass
            await asyncio.sleep(3)
        
        if not qr_sent:
            log("❌ 未能提取到二维码，请检查截图")
            await page.screenshot(path="error_no_qr.png")
            send_tg_photo("error_no_qr.png", "❌ 无法定位二维码元素")
            await browser.close()
            return

        # 初始化消息偏移量 (在发送二维码后，防止读到之前的消息)
        update_tg_offset()

        # 3. 监控安全验证与交互
        log("📡 监控安全验证状态 (总长 600s)...")
        start_time = time.time()
        voice_triggered = False
        login_success = False
        account_locked = False

        while time.time() - start_time < 600:
            current_url = page.url
            
            # --- 新增：黑屋/风控检测 ---
            if "aq.jd.com" in current_url:
                # 检查是否存在“暂无法在京东网页端使用”的警告
                lock_msg_locator = page.locator("h5.tip-title")
                if await lock_msg_locator.is_visible():
                    lock_text = await lock_msg_locator.inner_text()
                    if "暂无法在京东网页端使用" in lock_text:
                        log(f"❌ 账号风险拦截: {lock_text}")
                        await page.screenshot(path="account_locked.png")
                        send_tg_photo("account_locked.png", f"🚫 <b>账号安全拦截</b>\n\n{lock_text}\n\n⚠️ 此账号已被网页端锁定，脚本无法继续，请前往 APP 处理。")
                        account_locked = True
                        break

                # 原有的语音验证触发逻辑
                voice_btn = page.locator("button.btn-voice:has-text('获取语音验证码')")
                if await voice_btn.is_visible() and not voice_triggered:
                    log("🖱️ 点击‘获取语音验证码’...")
                    await voice_btn.click()
                    voice_triggered = True
                    send_tg_msg("📞 <b>语音验证码已发出</b>\n请接听电话并回复 6 位数字。")
                    await asyncio.sleep(5)
                    await page.screenshot(path="voice_sent.png")
                    send_tg_photo("voice_sent.png", "📞 验证界面截图")

                # 原有的验证码填入逻辑
                input_selector = "input.field[placeholder='请输入手机验证码']"
                if await page.locator(input_selector).is_visible():
                    code = get_tg_code()
                    if code:
                        log(f"📥 收到验证码: {code}，正在提交...")
                        await page.fill(input_selector, code)
                        await asyncio.sleep(2)
                        submit_btn = page.locator("button.btn-primary:has-text('提交认证')")
                        if await submit_btn.is_visible():
                            await submit_btn.click()
                            await asyncio.sleep(10)

            # 判定真正的成功（排除掉仍在验证页的情况）
            if "jd.com" in current_url and ("home" in current_url or "myJd" in current_url) and "aq.jd.com" not in current_url:
                log(f"🎊 登录成功: {current_url}")
                login_success = True
                break
                
            await asyncio.sleep(5)

        # 4. 提取 Cookie (增加锁定状态判断)
        if login_success and not account_locked:
            log("⏳ 提取最终 Cookie...")
            await asyncio.sleep(15)
            try: await page.goto("https://home.m.jd.com/myJd/home.action", timeout=60000)
            except: pass
            
            cookies = await context.cookies()
            ck_dict = {c['name']: c['value'] for c in cookies}
            pt_key = ck_dict.get('pt_key')
            if pt_key:
                res = f"pt_key={pt_key};pt_pin={ck_dict.get('pt_pin','')};"
                send_tg_msg(f"✅ <b>京东登录成功</b>\n<code>{res}</code>")
        elif account_locked:
            log("🛑 任务因账号风控锁定而终止。")
        else:
            log("❌ 任务结束，未成功登录。")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(run_qq_login())
