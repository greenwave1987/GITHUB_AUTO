import asyncio
import os
import time
import requests
import sys
from playwright.async_api import async_playwright

sys.stdout.reconfigure(line_buffering=True)

TG_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")
PROXY_URL = os.getenv("PROXY_URL")

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

async def run_jd_login():
    async with async_playwright() as p:
        # 配置启动参数
        launch_args = {"headless": True}
        if PROXY_URL:
            # 强制 Playwright 内部所有流量走代理，忽略系统分流
            launch_args["proxy"] = {"server": PROXY_URL}
            log(f"🚀 已强制全量代理: {PROXY_URL}")

        browser = await p.chromium.launch(**launch_args)
        
        # 模拟移动端环境（京东对移动端扫码更友好）
        context = await browser.new_context(
            viewport={'width': 375, 'height': 667},
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 13_2_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.0.3 Mobile/15E148 Safari/604.1",
            is_mobile=True
        )
        
        # 设置全局超时
        page = await context.new_page()
        page.set_default_timeout(90000)

        # --- 关键优化：拦截图片和 CSS，节省内网穿透带宽 ---
        async def block_aggressively(route):
            if route.request.resource_type in ["image", "media", "font", "stylesheet"]:
                await route.abort()
            else:
                await route.continue_()
        
        await page.route("**/*", block_aggressively)

        log("🌐 正在通过代理访问京东登录页...")
        try:
            # 使用 'commit' 模式：只要服务器开始返回内容就继续，不等待图片加载
            await page.goto("https://passport.jd.com/new/login.aspx", wait_until="commit", timeout=90000)
            log("✅ 页面响应已开始...")
            
            # 稍微等一下二维码生成所需的 JS 运行
            await asyncio.sleep(5)
            
            # 手动解除截图时对图片的拦截，或者只截取二维码区域
            # 如果二维码显示不出来，可能是因为被刚才的拦截逻辑杀掉了
            # 我们只需要确保 qr.m.jd.com 的图片通过即可
        except Exception as e:
            log(f"❌ 访问超时: {e}")
            await page.screenshot(path="timeout_err.png")
            # 发送截图看看此时页面长什么样
            await browser.close()
            return

        # 3. 截取二维码
        qr_selector = "#passport-main-qrcode-img"
        try:
            await page.wait_for_selector(qr_selector, timeout=20000)
            log("📸 捕捉到二维码，发送至 TG...")
            await page.locator(qr_selector).screenshot(path="qrcode.png")
            # 发送 TG 代码省略...
        except:
            log("❌ 未能发现二维码元素")

        # 后续扫码监听逻辑同前...
        await browser.close()

if __name__ == "__main__":
    asyncio.run(run_jd_login())
