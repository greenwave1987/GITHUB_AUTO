import asyncio
import os
import time
import requests
import sys
from playwright.async_api import async_playwright

# 强制实时刷新日志
sys.stdout.reconfigure(line_buffering=True)

# 环境变量获取
TG_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")
PROXY_URL = "socks5://greenwave1987.iask.in:19873"#os.getenv("PROXY_URL")

def log(msg):
    timestamp = time.strftime('%H:%M:%S')
    print(f"[{timestamp}] {msg}", flush=True)

def send_tg_photo(photo_path, caption):
    """发送图片到 Telegram"""
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto"
    try:
        with open(photo_path, 'rb') as f:
            resp = requests.post(url, data={
                "chat_id": TG_CHAT_ID, 
                "caption": caption, 
                "parse_mode": "HTML"
            }, files={"photo": f}, timeout=20)
            return resp.status_code == 200
    except Exception as e:
        log(f"❌ TG 发送失败: {e}")
        return False

async def run_jd_login():
    async with async_playwright() as p:
        log("🚀 正在初始化 Chromium (使用代理)...")
        
        launch_args = {"headless": True}
        if PROXY_URL:
            launch_args["proxy"] = {"server": PROXY_URL}
            log(f"🌐 代理节点: {PROXY_URL.split('@')[-1]}")

        browser = await p.chromium.launch(**launch_args)
        # 模拟桌面端环境，避免 H5 端的频繁验证码
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        # --- 精准资源拦截 (针对内网穿透优化) ---
        async def smart_route(route):
            req = route.request
            # 必须放行：JS 脚本、二维码接口、Passport 主域名
            if req.resource_type == "script" or "jd.com" in req.url:
                await route.continue_()
            # 拦截：CSS、字体、广告、无关图片
            elif req.resource_type in ["stylesheet", "font", "media"] or "google" in req.url:
                await route.abort()
            else:
                await route.continue_()
        
        await page.route("**/*", smart_route)

        log("🌐 正在连接京东登录页...")
        try:
            # 1. 尝试进入页面
            await page.goto("https://passport.jd.com/new/login.aspx", wait_until="domcontentloaded", timeout=60000)
            log("✅ 页面 DOM 已加载，等待 JS 渲染...")
            
            # 2. 初始状态截图
            await asyncio.sleep(5)
            await page.screenshot(path="init.png")
            send_tg_photo("init.png", "📡 <b>初始化监控</b>\n页面已打开，正在生成二维码...")

            # 3. 寻找二维码 (核心修复段)
            qr_selector = "#passport-main-qrcode-img"
            try:
                # 等待 20 秒，给代理一点时间加载
                await page.wait_for_selector(qr_selector, timeout=20000)
                
                # --- 黑科技：注入 JS 脚本，强制删除京东的刷新遮罩层 ---
                log("🚫 正在强制移除二维码遮罩层...")
                try:
                    # 这个选择器通常对应遮挡二维码的那个透明方块
                    await page.evaluate("""() => {
                        const mask = document.querySelector('.qrcode-pnl .qrcode-msg');
                        if (mask) {
                            mask.style.display = 'none'; // 隐藏遮罩
                            mask.remove(); // 强制删除元素
                        }
                        const qrImg = document.querySelector('#passport-main-qrcode-img');
                        if (qrImg) {
                            qrImg.style.opacity = 1; // 确保图片本身是可见的
                        }
                    }""")
                exceptException as js_e:
                    log(f"⚠️ 移除遮罩失败 (非致命): {js_e}")
    
                # --- 修改截图方式：不再只截元素，而是截全屏后再裁剪 ---
                log("📸 正在截取完整的二维码区域...")
                # 我们截取全屏，因为全屏截图是不受 HTML 遮罩影响的（如果遮罩已被删除）
                await page.screenshot(path="full_qrcode.png")
                
                # 或者：如果上面的 JS 删除了遮罩，这里就可以再次尝试元素截图
                # await page.locator(qr_selector).screenshot(path="qrcode.png")
                
                log("📸 二维码已清理，发送至 TG...")
                send_tg_photo("full_qrcode.png", "✅ <b>京东二维码 (已强制清理遮罩)</b>\n请立即扫码")
    
            except Exception as e:
                log(f"❌ 无法定位二维码元素: {e}")
                await page.screenshot(path="not_found.png")
                send_tg_photo("not_found.png", "⚠️ <b>无法加载二维码</b>\n代理可能太慢或已失效。")

            # 4. 实时循环监控
            log("📡 进入扫码状态监控 (120秒)...")
            start_time = time.time()
            last_shot = time.time()
            
            while time.time() - start_time < 120:
                # 检查跳转
                if "passport.jd.com" not in page.url or "home" in page.url:
                    log(f"🎊 检测到 URL 跳转: {page.url}")
                    break
                
                # 每 15 秒同步一次现场截图
                if time.time() - last_shot >= 15:
                    await page.screenshot(path="live.png")
                    send_tg_photo("live.png", f"⏳ <b>扫码监控中</b>\n当前 URL: {page.url}\n时间: {time.strftime('%H:%M:%S')}")
                    last_shot = time.time()
                
                await asyncio.sleep(2)

            # 5. 结果处理
            log("⏳ 正在提取 Cookie...")
            await asyncio.sleep(5)
            cookies = await context.cookies()
            ck_dict = {c['name']: c['value'] for c in cookies}
            
            pt_key = ck_dict.get('pt_key')
            pt_pin = ck_dict.get('pt_pin') or ck_dict.get('pin')

            if pt_key and pt_pin:
                ck_str = f"pt_key={pt_key};pt_pin={pt_pin};"
                log(f"🎉 成功获取 Cookie: {pt_pin}")
                requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", 
                             data={"chat_id": TG_CHAT_ID, "text": f"✅ <b>登录成功</b>\n\n<code>{ck_str}</code>", "parse_mode": "HTML"})
            else:
                await page.screenshot(path="final_fail.png")
                send_tg_photo("final_fail.png", f"⚠️ <b>未提取到 pt_key</b>\n当前 URL: {page.url}\nKeys: {list(ck_dict.keys())}")

        except Exception as e:
            log(f"❌ 运行崩溃: {e}")
            await page.screenshot(path="crash.png")
            send_tg_photo("crash.png", f"❌ <b>脚本运行崩溃</b>\n原因: {str(e)[:100]}")

        await browser.close()
        log("🏁 任务结束")

if __name__ == "__main__":
    if TG_TOKEN and TG_CHAT_ID:
        asyncio.run(run_jd_login())
    else:
        log("❌ 错误: TG 环境变量未配置")
