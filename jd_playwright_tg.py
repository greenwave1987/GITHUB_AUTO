import asyncio
import os
import time
import requests
import sys
from playwright.async_api import async_playwright

# 强制实时刷新日志
sys.stdout.reconfigure(line_buffering=True)

# 优先级：GitHub Secrets > 默认值
TG_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")

# --- 修改点：设置默认代理 URL ---
DEFAULT_PROXY = "socks5://greenwave1987.iask.in:19873"
PROXY_URL = os.getenv("PROXY_URL", DEFAULT_PROXY)

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
            }, files={"photo": f}, timeout=25)
    except:
        pass

async def run_jd_login():
    async with async_playwright() as p:
        log("🚀 启动浏览器...")
        
        launch_args = {"headless": True}
        if PROXY_URL:
            launch_args["proxy"] = {"server": PROXY_URL}
            log(f"🌐 使用代理: {PROXY_URL}")

        browser = await p.chromium.launch(**launch_args)
        # 调高硬件规格模拟，减少被识别为爬虫的概率
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        page.set_default_timeout(60000) # 针对慢速代理设置 60s 超时

        qr_ready = False
        # --- 核心重试循环：10次尝试 ---
        for attempt in range(1, 11):
            log(f"🔄 正在进行第 {attempt}/10 次尝试获取二维码...")
            try:
                # 1. 访问页面 (domcontentloaded 模式最快)
                await page.goto("https://passport.jd.com/new/login.aspx", wait_until="domcontentloaded", timeout=45000)
                
                # 2. 等待二维码容器出现
                qr_selector = "#passport-main-qrcode-img"
                await page.wait_for_selector(qr_selector, state="visible", timeout=30000)
                
                # 3. 强制留出 JS 渲染时间 (慢速代理的关键)
                await asyncio.sleep(7)
                
                # 4. 检查图片内容是否真的加载出来了
                has_src = await page.evaluate(f"""() => {{
                    const img = document.querySelector('{qr_selector}');
                    return img && img.src && (img.src.startsWith('data:image') || img.src.startsWith('http'));
                }}""")

                if has_src:
                    log("✅ 二维码图片数据已到达，正在清理遮罩...")
                    # 强力清理遮罩层
                    await page.evaluate("""() => {
                        const bad_elements = ['.qrcode-msg', '.msg-err', '.qrcode-pnl .qrcode-msg'];
                        bad_elements.forEach(s => document.querySelectorAll(s).forEach(el => el.remove()));
                        const img = document.querySelector('#passport-main-qrcode-img');
                        if (img) {
                            img.style.opacity = '1';
                            img.style.visibility = 'visible';
                            img.style.display = 'block';
                        }
                    }""")
                    
                    # 5. 截图并发送
                    await page.locator(qr_selector).screenshot(path="qrcode.png")
                    send_tg_photo("qrcode.png", f"✅ <b>二维码获取成功</b>\n尝试次数: {attempt}\n请立即扫码！")
                    qr_ready = True
                    break
                else:
                    log(f"⚠️ 第 {attempt} 次获取失败：元素存在但图片数据未加载。")
                    raise Exception("QR_IMG_EMPTY")

            except Exception as e:
                log(f"❌ 第 {attempt} 次尝试出错: {str(e)[:60]}")
                if attempt < 10:
                    log("⏳ 正在刷新页面并等待 5 秒重试...")
                    await asyncio.sleep(5)
                else:
                    log("💀 10次重试全部失败，代理带宽可能不足以支撑加载。")

        if not qr_ready:
            await page.screenshot(path="fail.png")
            send_tg_photo("fail.png", "❌ <b>重试 10 次后依然无法加载</b>\n请检查代理是否稳定。")
            await browser.close()
            return

        # --- 成功后的实时监控阶段 ---
        log("📡 开启实时扫码监控 (180秒)...")
        start_time = time.time()
        last_shot = time.time()
        
        while time.time() - start_time < 180:
            if "passport.jd.com" not in page.url or "home" in page.url:
                log(f"🎉 页面已跳转: {page.url}")
                break
            
            # 每 15 秒同步一次实时画面
            if time.time() - last_shot >= 15:
                await page.screenshot(path="live.png")
                send_tg_photo("live.png", f"🕒 实时状态 ({time.strftime('%H:%M:%S')})\nURL: {page.url}")
                last_shot = time.time()
            
            await asyncio.sleep(2)

        # 提取 Cookie
        log("🔍 提取最终 Cookie...")
        await asyncio.sleep(5)
        cookies = await context.cookies()
        ck_dict = {c['name']: c['value'] for c in cookies}
        pt_key = ck_dict.get('pt_key')
        pt_pin = ck_dict.get('pt_pin') or ck_dict.get('pin')

        if pt_key and pt_pin:
            res = f"pt_key={pt_key};pt_pin={pt_pin};"
            log(f"🎉 登录成功: {pt_pin}")
            requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", 
                         data={"chat_id": TG_CHAT_ID, "text": f"✅ <b>登录成功</b>\n<code>{res}</code>", "parse_mode": "HTML"})
        else:
            log("❌ 未提取到 pt_key，请检查实时监控截图。")

        await browser.close()

if __name__ == "__main__":
    if TG_TOKEN and TG_CHAT_ID:
        asyncio.run(run_jd_login())
    else:
        log("❌ 错误: 必须配置 TG_BOT_TOKEN 和 TG_CHAT_ID")
