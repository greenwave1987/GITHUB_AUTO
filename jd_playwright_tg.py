import asyncio
import os
import time
import requests
import sys
from playwright.async_api import async_playwright

# 强制实时刷新日志
sys.stdout.reconfigure(line_buffering=True)

# 环境变量
TG_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")
PROXY_URL = "socks5://greenwave1987.iask.in:19873"#os.getenv("PROXY_URL") # 格式: socks5://user:pass@host:port

def log(msg):
    timestamp = time.strftime('%H:%M:%S')
    print(f"[{timestamp}] {msg}", flush=True)

def send_tg_photo(photo_path, caption):
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto"
    try:
        with open(photo_path, 'rb') as f:
            requests.post(url, data={
                "chat_id": TG_CHAT_ID, 
                "caption": caption, 
                "parse_mode": "HTML"
            }, files={"photo": f}, timeout=15)
    except Exception as e:
        log(f"❌ TG 发送异常: {e}")

async def run_jd_login():
    async with async_playwright() as p:
        # --- 核心修改：配置代理 ---
        launch_args = {
            "headless": True,
        }
        
        if PROXY_URL:
            log(f"🌐 检测到代理配置: {PROXY_URL.split('@')[-1]}") # 隐藏密码打印
            launch_args["proxy"] = {"server": PROXY_URL}
        else:
            log("⚠️ 未检测到代理配置，将使用 GitHub 直连（极易被拦截）")

        log("🚀 启动浏览器...")
        browser = await p.chromium.launch(**launch_args)
        
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        # 1. 访问登录页
        log("🌐 访问京东登录页面...")
        try:
            await page.goto("https://passport.jd.com/new/login.aspx", wait_until="networkidle", timeout=60000)
        except Exception as e:
            log(f"❌ 页面加载超时: {e}")
            await browser.close()
            return

        # 2. 获取初始二维码
        qr_selector = "#passport-main-qrcode-img"
        try:
            await page.wait_for_selector(qr_selector, timeout=20000)
            await asyncio.sleep(2)
            await page.locator(qr_selector).screenshot(path="qrcode.png")
            log("📸 初始二维码已发送至 TG")
            send_tg_photo("qrcode.png", "🔔 <b>京东扫码登录</b>\n代理已开启，请立即扫码！")
        except Exception as e:
            log(f"❌ 无法加载二维码，可能是代理失效或 IP 被封: {e}")
            await page.screenshot(path="error_page.png")
            send_tg_photo("error_page.png", "❌ <b>页面加载失败</b>\n请检查代理或日志")
            await browser.close()
            return

        # 3. 实时监控与截图
        log("📡 监控模式已启动 (120秒)...")
        start_time = time.time()
        last_shot = time.time()
        
        try:
            while time.time() - start_time < 120:
                current_url = page.url
                
                # 判断是否登录成功跳转
                if "passport.jd.com" not in current_url or "home" in current_url:
                    log(f"🎊 检测到 URL 跳转: {current_url}")
                    break
                
                # 每 20 秒发送一次实时截图
                if time.time() - last_shot >= 20:
                    await page.screenshot(path="monitor.png")
                    send_tg_photo("monitor.png", f"⏳ 状态监控\nURL: {current_url}\nTime: {time.strftime('%H:%M:%S')}")
                    last_shot = time.time()
                
                await asyncio.sleep(2)

            log("⏳ 等待 5 秒完成数据同步...")
            await asyncio.sleep(5)
            
            # 4. 提取 Cookie
            cookies = await context.cookies()
            ck_dict = {c['name']: c['value'] for c in cookies}
            
            pt_key = ck_dict.get('pt_key')
            pt_pin = ck_dict.get('pt_pin') or ck_dict.get('pin')

            if pt_key and pt_pin:
                ck_str = f"pt_key={pt_key};pt_pin={pt_pin};"
                log(f"🎉 成功抓取！用户: {pt_pin}")
                requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", 
                             data={"chat_id": TG_CHAT_ID, "text": f"✅ <b>登录成功</b>\n\n<code>{ck_str}</code>", "parse_mode": "HTML"})
            else:
                log("⚠️ 页面已跳转但未发现 pt_key")
                await page.screenshot(path="result_error.png")
                send_tg_photo("result_error.png", f"⚠️ <b>未抓取到 pt_key</b>\n当前 Cookie 键: {list(ck_dict.keys())}")

        except Exception as e:
            log(f"⏰ 运行异常: {e}")

        await browser.close()
        log("🏁 脚本结束")

if __name__ == "__main__":
    if TG_TOKEN and TG_CHAT_ID:
        asyncio.run(run_jd_login())
    else:
        log("❌ 错误: 环境变量不完整")
