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
    """发送纯文本消息到 TG"""
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    try:
        requests.post(url, data={"chat_id": TG_CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=20)
    except: pass

def send_tg_photo(photo_path, caption):
    """发送图片到 TG"""
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto"
    try:
        with open(photo_path, 'rb') as f:
            requests.post(url, data={"chat_id": TG_CHAT_ID, "caption": caption, "parse_mode": "HTML"}, files={"photo": f}, timeout=30)
    except: pass

def update_tg_offset():
    """初始化 TG 消息偏移量，忽略旧消息"""
    global last_tg_offset
    url = f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates"
    try:
        resp = requests.get(url, params={"timeout": 0}, timeout=15).json()
        if resp.get("ok") and resp.get("result"):
            # 获取最新一条消息的 ID
            last_tg_offset = resp["result"][-1]["update_id"]
            log(f"📡 TG 消息 Offset 已初始化为: {last_tg_offset}")
    except Exception as e:
        log(f"⚠️ 初始化 TG Offset 失败: {e}")

def get_tg_code():
    """监听 TG，获取最新的 6 位纯数字验证码"""
    global last_tg_offset
    url = f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates"
    try:
        # 只获取比上一次消息更晚的消息，timeout=20 表示长轮询
        resp = requests.get(url, params={"offset": last_tg_offset + 1, "timeout": 20}, timeout=35).json()
        if resp.get("ok") and resp.get("result"):
            for item in resp["result"]:
                msg = item.get("message", {})
                text = msg.get("text", "")
                
                # 更新偏移量，防止重复读取
                last_tg_offset = item["update_id"]
                
                # 精确匹配 6 位纯数字
                code_match = re.search(r'^\d{6}$', text.strip())
                if code_match:
                    return code_match.group()
    except Exception as e:
        log(f"⚠️ 读取 TG 消息出错: {e}")
    return None

async def run_qq_login():
    async with async_playwright() as p:
        log("🚀 启动 Chromium...")
        launch_args = {"headless": True}
        if PROXY_URL:
            launch_args["proxy"] = {"server": PROXY_URL}
            log(f"🌐 使用代理: {PROXY_URL}")

        browser = await p.chromium.launch(**launch_args)
        context = await browser.new_context(viewport={'width': 1280, 'height': 800})
        # 针对慢速代理和验证环节设置长超时
        context.set_default_timeout(180000)
        page = await context.new_page()

        # 1. 访问京东登录页
        try:
            log("🌐 正在访问京东登录页...")
            await page.goto("https://passport.jd.com/new/login.aspx", wait_until="commit", timeout=90000)
        except Exception as e:
            log(f"❌ 加载超时: {e}")
            await browser.close()
            return

        # 2. 触发 QQ 登录与二维码探测循环
        log("🔍 进入循环探测与点击模式...")
        for i in range(1, 11): # 尝试 10 次触发
            if "qq.com" not in page.url:
                log(f"🖱️ 第 {i} 次点击 QQ 登录按钮...")
                await page.evaluate("""() => {
                    const btn = document.querySelector('a.pdl[onclick*="qqLogin"]');
                    if (btn) btn.click();
                }""")
                await asyncio.sleep(8) # 给代理网络跳转时间
            else: break

        # 初始化 TG 消息队列，忽略点击前的旧消息
        update_tg_offset()

        log("📡 请扫描 TG 机器人发送的二维码...")
        # ... (此处省略提取二维码截图发送的逻辑，假设你已扫码) ...

        # 3. 核心：安全验证监控与 TG 交互循环
        log("📡 监控安全验证状态 (总长 600s)...")
        start_time = time.time()
        voice_triggered = False
        login_success = False

        while time.time() - start_time < 600: # 监控 10 分钟
            current_url = page.url
            
            # --- 场景：进入安全验证页 ---
            if "aq.jd.com" in current_url:
                # A. 触发语音验证码按钮
                voice_btn_selector = "button.btn-voice:has-text('获取语音验证码')"
                if await page.locator(voice_btn_selector).is_visible() and not voice_triggered:
                    log("🖱️ 点击‘获取语音验证码’...")
                    await page.click(voice_btn_selector)
                    voice_triggered = True
                    send_tg_msg("📞 <b>语音验证码已发出</b>\n请接听电话，并将 6 位数字直接回复给我！")
                    await asyncio.sleep(5)
                    await page.screenshot(path="voice_sent.png")
                    send_tg_photo("voice_sent.png", "📞 验证已触发，等待输入。")

                # B. 发现输入框，启动 TG 监听
                input_selector = "input.field[placeholder='请输入手机验证码']"
                submit_btn_selector = "button.btn-primary:has-text('提交认证')"
                
                if await page.locator(input_selector).is_visible():
                    log("⌨️ 检测到输入框，开始监听 TG 验证码...")
                    
                    # 监听并提取验证码 (此方法会阻塞 20s)
                    code = get_tg_code()
                    
                    if code:
                        log(f"📥 收到验证码: {code}，正在填入并提交...")
                        await page.fill(input_selector, code)
                        await asyncio.sleep(2)
                        
                        # 点击“提交认证”按钮
                        if await page.locator(submit_btn_selector).is_visible():
                            await page.click(submit_btn_selector)
                            send_tg_msg(f"✅ 已点击“提交认证”，验证码: <code>{code}</code>")
                            await asyncio.sleep(10) # 给代理网络时间提交
                        else:
                            log("⚠️ 未发现“提交认证”按钮")
                            await page.screenshot(path="no_submit_btn.png")

            # --- 场景：登录成功 (跳转回京东主域) ---
            if "jd.com" in current_url and ("home" in current_url or "index" in current_url or "myJd" in current_url):
                log(f"🎊 登录成功跳转: {current_url}")
                login_success = True
                break
                
            await asyncio.sleep(5)

        # 4. 提取最终 Cookie
        if login_success:
            log("⏳ 等待 Cookie 持久化 (20s)...")
            await asyncio.sleep(20) # 针对慢速网络延长等待
            
            # 激活 Cookie
            try:
                await page.goto("https://home.m.jd.com/myJd/home.action", wait_until="domcontentloaded", timeout=60000)
                await asyncio.sleep(5)
            except: pass

            log("🔍 正在提取全量 Cookie...")
            all_cookies = await context.cookies()
            ck_dict = {c['name']: c['value'] for c in all_cookies}
            pt_key = ck_dict.get('pt_key')
            pt_pin = ck_dict.get('pt_pin') or ck_dict.get('pin')

            if pt_key:
                res = f"pt_key={pt_key};pt_pin={pt_pin};"
                log(f"🎉 获取成功: {pt_pin}")
                requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", 
                             data={"chat_id": TG_CHAT_ID, "text": f"✅ <b>京东登录成功</b>\n\n<code>{res}</code>", "parse_mode": "HTML"})
            else:
                log("❌ 未能在全量 Cookie 中找到 pt_key")
                await page.screenshot(path="final_cookie_error.png")
        else:
            log("❌ 任务最终超时或验证失败")
            await page.screenshot(path="final_timeout.png")
            send_tg_photo("final_timeout.png", "⚠️ 任务结束，验证超时或失败。")

        await browser.close()
        log("🏁 任务结束")

if __name__ == "__main__":
    if TG_TOKEN and TG_CHAT_ID:
        asyncio.run(run_qq_login())
    else:
        log("❌ 环境变量错误")
