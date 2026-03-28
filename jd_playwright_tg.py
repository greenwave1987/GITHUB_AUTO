import asyncio
import os
import time
import requests
import sys
from playwright.async_api import async_playwright

# 强制实时刷新日志
sys.stdout.reconfigure(line_buffering=True)

TG_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")
PROXY_URL = os.getenv("PROXY_URL")

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
            }, files={"photo": f}, timeout=20)
    except Exception as e:
        log(f"❌ TG 图片发送失败: {e}")

async def run_jd_login():
    async with async_playwright() as p:
        log("🚀 启动浏览器...")
        launch_args = {"headless": True}
        if PROXY_URL:
            launch_args["proxy"] = {"server": PROXY_URL}
            log(f"🌐 代理节点: {PROXY_URL.split('@')[-1]}")

        browser = await p.chromium.launch(**launch_args)
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        log("🌐 访问京东登录页...")
        try:
            # 延长加载超时到 90 秒
            await page.goto("https://passport.jd.com/new/login.aspx", wait_until="domcontentloaded", timeout=90000)
            
            # 等待二维码加载并清理遮罩
            await asyncio.sleep(8)
            await page.evaluate("""() => {
                ['.qrcode-msg', '.msg-err', '.qrcode-mod .qrcode-msg'].forEach(s => {
                    const el = document.querySelector(s);
                    if (el) el.remove();
                });
                const img = document.querySelector('#passport-main-qrcode-img');
                if (img) img.style.opacity = '1';
            }""")

            qr_selector = "#passport-main-qrcode-img"
            if await page.is_visible(qr_selector):
                await page.locator(qr_selector).screenshot(path="qrcode.png")
                send_tg_photo("qrcode.png", "✅ <b>京东二维码已就绪</b>\n请立即扫码。脚本将每 10 秒发送一次实时截图。")
                log("📸 二维码已发送，进入实时监控...")
            else:
                log("⚠️ 未发现二维码，发送全屏截图")
                await page.screenshot(path="no_qr.png")
                send_tg_photo("no_qr.png", "⚠️ <b>未发现二维码</b>")

            # --- 核心：定时截图监控逻辑 ---
            start_time = time.time()
            last_screenshot_time = time.time()
            
            # 监控 3 分钟 (180秒)
            while time.time() - start_time < 180:
                current_url = page.url
                
                # 检查是否成功跳转（通常跳转到 home.m.jd.com 或 www.jd.com）
                if "passport.jd.com" not in current_url or "home" in current_url:
                    log(f"🎉 检测到页面跳转: {current_url}")
                    # 额外截最后一张图确认
                    await page.screenshot(path="success_jump.png")
                    send_tg_photo("success_jump.png", f"🎊 <b>检测到跳转</b>\nURL: {current_url}")
                    break
                
                # 每 10 秒发送一次实时状态截图
                if time.time() - last_screenshot_time >= 10:
                    log(f"📡 正在发送实时截图... 当前 URL: {current_url}")
                    await page.screenshot(path="live_status.png")
                    # 在 caption 里加入当前时间，防止 TG 消息折叠
                    send_tg_photo("live_status.png", f"🕒 <b>实时状态 ({time.strftime('%H:%M:%S')})</b>\n请检查是否出现了滑块验证码或扫码确认提示。")
                    last_screenshot_time = time.time()

                await asyncio.sleep(1) # 1秒检查一次 URL

            # --- 提取 Cookie ---
            log("🔍 正在等待 5 秒确认 Cookie 写入...")
            await asyncio.sleep(5)
            cookies = await context.cookies()
            ck_dict = {c['name']: c['value'] for c in cookies}
            
            pt_key = ck_dict.get('pt_key')
            pt_pin = ck_dict.get('pt_pin') or ck_dict.get('pin')

            if pt_key and pt_pin:
                cookie_str = f"pt_key={pt_key};pt_pin={pt_pin};"
                log(f"🎉 成功获取 Cookie: {pt_pin}")
                requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", 
                             data={"chat_id": TG_CHAT_ID, "text": f"✅ <b>登录成功</b>\n\n<code>{cookie_str}</code>", "parse_mode": "HTML"})
            else:
                log("❌ 最终未能提取到 pt_key")
                await page.screenshot(path="final_error.png")
                send_tg_photo("final_error.png", f"⚠️ <b>登录结束但未发现 pt_key</b>\nKeys: {list(ck_dict.keys())}")

        except Exception as e:
            log(f"❌ 运行崩溃: {e}")
            await page.screenshot(path="crash_debug.png")
            send_tg_photo("crash_debug.png", f"❌ <b>脚本异常退出</b>\n{str(e)[:100]}")
        
        await browser.close()
        log("🏁 任务完成")

if __name__ == "__main__":
    if TG_TOKEN and TG_CHAT_ID:
        asyncio.run(run_jd_login())
    else:
        log("❌ 缺失 TG 环境变量")
