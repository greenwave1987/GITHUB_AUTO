import asyncio
import os
import time
import requests
import sys
from playwright.async_api import async_playwright

# 强制实时打印日志
sys.stdout.reconfigure(line_buffering=True)

# 变量获取
TG_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")

def log(msg):
    timestamp = time.strftime('%H:%M:%S')
    print(f"[{timestamp}] {msg}", flush=True)

def send_tg_msg(text):
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": TG_CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=15)

def send_tg_photo(photo_path, caption):
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto"
    try:
        with open(photo_path, 'rb') as f:
            resp = requests.post(url, data={
                "chat_id": TG_CHAT_ID, 
                "caption": caption, 
                "parse_mode": "HTML"
            }, files={"photo": f}, timeout=15)
            return resp.status_code == 200
    except Exception as e:
        log(f"❌ TG 发送异常: {e}")
        return False

async def run_jd_login():
    async with async_playwright() as p:
        log("🚀 启动浏览器...")
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        log("🌐 访问京东登录页面...")
        await page.goto("https://passport.jd.com/new/login.aspx", wait_until="networkidle")

        # 1. 发送初始二维码
        qr_selector = "#passport-main-qrcode-img"
        try:
            await page.wait_for_selector(qr_selector, timeout=20000)
            await asyncio.sleep(2)
            await page.locator(qr_selector).screenshot(path="qrcode.png")
            log("📸 初始二维码已发送至 TG")
            send_tg_photo("qrcode.png", "🔔 <b>京东扫码登录</b>\n请立即扫码！脚本将开启实时监控...")
        except Exception as e:
            log(f"❌ 获取二维码失败: {e}")
            await browser.close()
            return

        log("📡 进入实时监控模式 (120秒)...")
        start_time = time.time()
        last_screenshot_time = time.time()
        
        # 2. 轮询监控与实时截图
        try:
            while time.time() - start_time < 120:
                current_url = page.url
                
                # 检查是否已经跳转离开登录页
                if "passport.jd.com" not in current_url or "home" in current_url:
                    log(f"🎊 检测到页面跳转: {current_url}")
                    break
                
                # 每隔 15 秒发送一次实时截图，同步进度
                if time.time() - last_screenshot_time >= 15:
                    await page.screenshot(path="status.png")
                    send_tg_photo("status.png", f"⏳ <b>扫码监控中</b>\n当前页面: {current_url}\n时间: {time.strftime('%H:%M:%S')}")
                    log("📸 已发送实时状态截图")
                    last_screenshot_time = time.time()

                await asyncio.sleep(2) # 降低 CPU 占用

            # 3. 登录后的收尾工作
            log("⏳ 等待跳转完成与 Cookie 注入...")
            await asyncio.sleep(5)
            
            log("🔍 提取最终 Cookie...")
            cookies = await context.cookies()
            ck_dict = {c['name']: c['value'] for c in cookies}
            
            pt_key = ck_dict.get('pt_key')
            pt_pin = ck_dict.get('pt_pin') or ck_dict.get('pin')

            if pt_key and pt_pin:
                ck_str = f"pt_key={pt_key};pt_pin={pt_pin};"
                log(f"🎉 登录成功: {pt_pin}")
                send_tg_msg(f"✅ <b>登录成功</b>\n\n<code>{ck_str}</code>")
            else:
                # 截图留证，看看跳转到了哪里
                await page.screenshot(path="final_error.png")
                send_tg_photo("final_error.png", "⚠️ <b>登录异常</b>\n页面已跳转但未发现 pt_key，请检查截图内容。")
                log(f"⚠️ 关键键缺失，当前键: {list(ck_dict.keys())}")

        except Exception as e:
            log(f"⏰ 运行出错: {e}")

        await browser.close()
        log("🏁 脚本结束")

if __name__ == "__main__":
    if TG_TOKEN and TG_CHAT_ID:
        asyncio.run(run_jd_login())
    else:
        log("❌ 错误: 环境变量配置不完整")
