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
        
        # 调高 context 默认超时
        context = await browser.new_context(viewport={'width': 1280, 'height': 800})
        context.set_default_timeout(90000) # 全局 90 秒超时
        
        page = await context.new_page()

        log("🌐 访问京东登录页 (宽松模式)...")
        try:
            # 修改点：改为 commit 模式，只要服务器响应就开始找按钮
            await page.goto("https://passport.jd.com/new/login.aspx", wait_until="commit", timeout=60000)
            log("✅ 页面已响应，等待 'QQ登录' 元素出现...")
        except Exception as e:
            log(f"❌ 访问京东超时: {e}")
            await browser.close()
            return

        # 1. 触发 QQ 登录弹窗
        qq_page = None
        try:
            # 精确选择器
            qq_btn_selector = 'a.pdl:has-text("QQ登录")'
            await page.wait_for_selector(qq_btn_selector, state="visible", timeout=30000)
            
            log("鼠标点击 QQ 登录按钮...")
            async with page.expect_popup() as popup_info:
                await page.click(qq_btn_selector)
            qq_page = await popup_info.value
            
            # 设置新页面的超时
            qq_page.set_default_timeout(60000)
            log(f"✅ 已捕获弹窗: {qq_page.url}")
        except Exception as e:
            log(f"❌ 弹窗触发失败: {e}")
            await page.screenshot(path="debug_main.png")
            send_tg_photo("debug_main.png", "❌ 无法进入 QQ 登录流程")
            await browser.close()
            return

        # 2. 在弹窗内寻找二维码
        log("🔍 正在 Iframe 中寻找二维码...")
        try:
            iframe_selector = "#ptlogin_iframe"
            await qq_page.wait_for_selector(iframe_selector, timeout=45000)
            
            frame = qq_page.frame_locator(iframe_selector)
            
            # 兼容多种可能的二维码图片选择器
            qr_img_selector = "#qrlogin_img"
            await frame.locator(qr_img_selector).wait_for(state="visible", timeout=30000)
            
            log("📸 成功捕获 QQ 二维码！")
            await frame.locator(qr_img_selector).screenshot(path="qq_qr.png")
            send_tg_photo("qq_qr.png", "🛡️ <b>京东 QQ 扫码</b>\n请尽快扫码完成登录")
            
        except Exception as e:
            log(f"❌ 获取二维码失败: {e}")
            await qq_page.screenshot(path="qq_error.png")
            send_tg_photo("qq_error.png", f"❌ QQ 页面加载异常: {str(e)[:100]}")
            await browser.close()
            return

        # 3. 监控扫码状态
        log("📡 正在监控扫码结果 (180s)...")
        start_time = time.time()
        while time.time() - start_time < 180:
            # 只要主页面 URL 跳转，说明登录完成
            if "jd.com" in page.url and "passport" not in page.url:
                log("🎊 检测到主页面跳转成功！")
                break
            if qq_page.is_closed():
                log("ℹ️ QQ 弹窗已关闭")
                break
            await asyncio.sleep(5)

        # 4. 提取 Cookie
        log("🔍 正在提取 pt_key...")
        await asyncio.sleep(5)
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
            log("⚠️ 未能提取到关键 Cookie")

        await browser.close()

if __name__ == "__main__":
    if TG_TOKEN and TG_CHAT_ID:
        asyncio.run(run_qq_login())
    else:
        log("❌ 缺失环境变量")
