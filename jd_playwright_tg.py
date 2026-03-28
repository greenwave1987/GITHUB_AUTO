import asyncio
import os
import time
import requests
from playwright.async_api import async_playwright

# 配置
TG_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_ID = os.getenv("TG_USER_ID")

def send_tg_msg(text):
    requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", 
                  data={"chat_id": TG_ID, "text": text, "parse_mode": "HTML"})

def send_tg_photo(photo_path, caption):
    with open(photo_path, 'rb') as f:
        requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto", 
                      data={"chat_id": TG_ID, "caption": caption, "parse_mode": "HTML"}, 
                      files={"photo": f})

async def jd_login():
    async with async_playwright() as p:
        # 1. 启动浏览器 (推荐使用 Chromium)
        browser = await p.chromium.launch(headless=True) # GitHub 环境必须 headless
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        print("[*] 正在打开京东登录页...")
        await page.goto("https://passport.jd.com/new/login.aspx", wait_until="networkidle")

        # 2. 定位二维码元素并截图
        # 京东登录页二维码选择器通常是 #passport-main-qrcode-img
        qr_selector = "#passport-main-qrcode-img"
        try:
            await page.wait_for_selector(qr_selector, timeout=10000)
            await page.locator(qr_selector).screenshot(path="qrcode.png")
            print("[+] 二维码已截取")
            send_tg_photo("qrcode.png", "📢 <b>Playwright 京东扫码</b>\n请在 2 分钟内扫码并确认")
        except Exception as e:
            print(f"[-] 无法定位二维码: {e}")
            await browser.close()
            return

        # 3. 循环等待页面跳转 (登录成功标志)
        print("[*] 等待扫码确认中...")
        try:
            # 监控 URL 变化，直到不再是登录页 (或者包含 ticket/home/myJd)
            # 这里的 timeout 设置为 120 秒
            await page.wait_for_url(lambda url: "passport.jd.com" not in url or "home.m.jd.com" in url, timeout=120000)
            print("[+] 检测到页面跳转，登录可能已成功！")
            
            # 额外等待 3 秒确保 Cookie 同步完成
            await asyncio.sleep(3)
            
            # 4. 提取 Cookie
            cookies = await context.cookies()
            cookie_dict = {ck['name']: ck['value'] for ck in cookies}
            
            pt_key = cookie_dict.get('pt_key')
            pt_pin = cookie_dict.get('pt_pin') or cookie_dict.get('pin')

            if pt_key and pt_pin:
                msg = f"✅ <b>登录成功</b>\n\n<code>pt_key={pt_key};pt_pin={pt_pin};</code>"
                send_tg_msg(msg)
                print(f"[+] 抓取成功: {pt_pin}")
            else:
                # 如果没拿到 pt_key，把所有能用的都发出来调试
                all_ck = "; ".join([f"{k}={v}" for k, v in cookie_dict.items() if k in ['pin', 'wskey', 'pt_key', 'pt_pin', 'unick']])
                send_tg_msg(f"⚠️ <b>未发现 pt_key</b>\n抓取到的关键内容: <code>{all_ck}</code>")
                
        except Exception as e:
            print(f"[-] 等待扫码超时或出错: {e}")
            send_tg_msg("⏰ <b>扫码超时</b>\n未检测到页面跳转，脚本已停止。")

        await browser.close()

if __name__ == "__main__":
    if not TG_TOKEN or not TG_ID:
        print("请设置 TG_BOT_TOKEN 和 TG_USER_ID 环境变量")
    else:
        asyncio.run(jd_login())
