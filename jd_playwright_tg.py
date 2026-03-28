import asyncio
import os
import time
import requests
import sys
from playwright.async_api import async_playwright

# 实时日志输出
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
        await page.goto("https://passport.jd.com/new/login.aspx", wait_until="networkidle")

        # 1. 触发 QQ 登录弹窗
        qq_page = None
        try:
            log("🖱️ 正在点击 'QQ登录' 按钮...")
            # 使用你提供的特定 class 和文本进行定位
            qq_btn = page.locator('a.pdl:has-text("QQ登录")')
            
            # 确保按钮在视图中并点击，同时监听新弹出的窗口
            async with page.expect_popup() as popup_info:
                await qq_btn.click()
            qq_page = await popup_info.value
            log(f"✅ 已成功捕获 QQ 弹窗: {qq_page.url}")
        except Exception as e:
            log(f"❌ 触发弹窗失败: {e}")
            await page.screenshot(path="page_error.png")
            send_tg_photo("page_error.png", "❌ 无法点击 QQ 登录按钮，请检查页面截图")
            await browser.close()
            return

        # 2. 在 QQ 弹窗中提取二维码
        log("🔍 正在定位 QQ 二维码 (进入 Iframe)...")
        try:
            # QQ 登录页的内容几乎都在这个 iframe 里
            iframe_selector = "#ptlogin_iframe"
            await qq_page.wait_for_selector(iframe_selector, timeout=30000)
            
            frame = qq_page.frame_locator(iframe_selector)
            
            # 尝试定位二维码图片容器
            qr_container = frame.locator(".qrlogin_img_out")
            await qr_container.wait_for(state="visible", timeout=20000)
            
            # 强制等待图片 src 加载完成
            qr_img = qr_container.locator("img#qrlogin_img")
            await qr_img.wait_for(state="visible", timeout=10000)
            
            log("📸 成功捕获 QQ 二维码！")
            await qr_img.screenshot(path="qq_qr.png")
            send_tg_photo("qq_qr.png", "🛡️ <b>京东 - QQ 扫码登录</b>\n请立即使用手机 QQ 扫码")
            
        except Exception as e:
            log(f"❌ 获取二维码失败: {e}")
            await qq_page.screenshot(path="qq_diag.png")
            send_tg_photo("qq_diag.png", f"❌ QQ 页面加载异常: {str(e)[:100]}")
            await browser.close()
            return

        # 3. 监控扫码状态
        log("📡 正在监控扫码结果 (180s)...")
        start_time = time.time()
        last_log_url = ""
        while time.time() - start_time < 180:
            current_url = page.url
            if current_url != last_log_url:
                log(f"🔗 当前主页面 URL: {current_url}")
                last_log_url = current_url

            # 登录成功的标志：跳转回京东首页或个人中心
            if "jd.com" in current_url and "passport" not in current_url:
                log("🎊 检测到成功跳转！")
                break
            
            # 如果 QQ 弹窗关闭了，也说明可能操作结束
            if qq_page.is_closed():
                log("ℹ️ QQ 弹窗已关闭，准备提取 Cookie...")
                break
                
            await asyncio.sleep(5)

        # 4. 提取 Cookie
        log("🔍 正在提取 pt_key...")
        await asyncio.sleep(5) # 等待数据写入
        cookies = await context.cookies()
        ck_dict = {c['name']: c['value'] for c in cookies}
        
        pt_key = ck_dict.get('pt_key')
        pt_pin = ck_dict.get('pt_pin') or ck_dict.get('pin')

        if pt_key:
            res = f"pt_key={pt_key};pt_pin={pt_pin};"
            log(f"🎉 登录成功: {pt_pin}")
            requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", 
                         data={"chat_id": TG_CHAT_ID, "text": f"✅ <b>QQ 登录成功</b>\n\n<code>{res}</code>", "parse_mode": "HTML"})
        else:
            log("⚠️ 未发现 pt_key，可能扫码被拦截或超时。")
            await page.screenshot(path="final_state.png")
            send_tg_photo("final_state.png", "⚠️ <b>登录结束但未提取到 pt_key</b>")

        await browser.close()

if __name__ == "__main__":
    if TG_TOKEN and TG_CHAT_ID:
        asyncio.run(run_qq_login())
    else:
        log("❌ 缺失 TG 环境变量")
