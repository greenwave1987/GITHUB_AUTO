import asyncio
import os
import time
import requests
import sys
from playwright.async_api import async_playwright

# 强制实时刷新日志，方便在 GitHub Actions 实时查看
sys.stdout.reconfigure(line_buffering=True)

# 环境变量配置
TG_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")
# 默认使用你提供的 SOCKS5 代理
PROXY_URL = os.getenv("PROXY_URL", "socks5://greenwave1987.iask.in:19873")

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

def send_tg_photo(photo_path, caption):
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto"
    try:
        with open(photo_path, 'rb') as f:
            requests.post(url, data={"chat_id": TG_CHAT_ID, "caption": caption, "parse_mode": "HTML"}, files={"photo": f}, timeout=30)
    except Exception as e:
        log(f"⚠️ TG 发送图片失败: {e}")

async def run_qq_login():
    async with async_playwright() as p:
        log("🚀 启动 Chromium...")
        launch_args = {"headless": True}
        if PROXY_URL:
            launch_args["proxy"] = {"server": PROXY_URL}
            log(f"🌐 代理节点: {PROXY_URL}")

        browser = await p.chromium.launch(**launch_args)
        # 设置 120 秒超长超时，应对内网穿透的延迟
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        context.set_default_timeout(120000)
        page = await context.new_page()

        # --- 1. 访问京东登录页 (抗延迟重试) ---
        success = False
        for attempt in range(1, 4):
            try:
                log(f"🌐 访问京东登录页 (第 {attempt} 次尝试)...")
                # wait_until="commit" 只要服务器有响应就立即开始，不等待渲染
                await page.goto("https://passport.jd.com/new/login.aspx", wait_until="commit", timeout=90000)
                success = True
                break
            except Exception as e:
                log(f"⚠️ 页面加载超时: {str(e)[:50]}，重试中...")
                await asyncio.sleep(5)

        if not success:
            log("❌ 多次尝试无法打开京东，任务终止。")
            await browser.close()
            return

        # --- 2. 强力触发点击与二维码探测循环 ---
        log("🔍 进入循环探测与点击模式...")
        qr_img_element = None
        iframe_selector = "#ptlogin_iframe"

        for i in range(1, 26): # 总计约 100 秒的探测周期
            curr_url = page.url
            
            # 如果 URL 已经包含 qq.com，说明跳转成功
            if "qq.com" in curr_url:
                try:
                    # 穿透 iframe 寻找二维码
                    frame = page.frame_locator(iframe_selector)
                    target_qr = frame.locator("#qrlogin_img")
                    if await target_qr.is_visible():
                        qr_img_element = target_qr
                        log("✅ 成功发现 QQ 二维码！")
                        break
                    
                    # 检查是否需要手动切换到二维码模式 (点击左下角图标)
                    switch_btn = frame.locator("#qr_switch_logo")
                    if await switch_btn.is_visible():
                        await switch_btn.click()
                        log("🖱️ 已手动切换至扫码模式")
                except:
                    pass
            else:
                # 仍在京东页面，每 3 次探测尝试通过 JS 强制点击一次 QQ 登录
                if i % 3 == 1:
                    log(f"🖱️ 第 {i} 次探测：JS 强力触发 QQ 登录按钮...")
                    try:
                        await page.evaluate("""() => {
                            const btn = document.querySelector('a.pdl[onclick*="qqLogin"]');
                            if (btn) btn.click();
                        }""")
                    except:
                        pass

            await asyncio.sleep(4)

        # --- 3. 扫码与结果提取 ---
        if qr_img_element:
            # 截图并发送到 TG
            await qr_img_element.screenshot(path="qq_qr.png")
            send_tg_photo("qq_qr.png", "🛡️ <b>京东 QQ 扫码登录</b>\n请在 2 分钟内完成扫码。")
            
            log("📡 实时监控登录跳转...")
            start_time = time.time()
            login_success = False
            
            while time.time() - start_time < 180:
                # 判定条件：URL 回到 jd.com 且包含成功特征
                if "jd.com" in page.url and ("home" in page.url or "index" in page.url or "myJd" in page.url):
                    log(f"🎊 检测到成功跳转至: {page.url}")
                    login_success = True
                    break
                await asyncio.sleep(4)

            if login_success:
                # --- 核心改进：深度等待 Cookie 同步 ---
                log("⏳ 等待 Cookie 写入持久化存储 (15s)...")
                await asyncio.sleep(15) 
                
                # 强制访问一次个人中心，激活 pt_key
                try:
                    log("🔄 正在激活登录态...")
                    await page.goto("https://home.m.jd.com/myJd/home.action", wait_until="domcontentloaded", timeout=60000)
                    await asyncio.sleep(5)
                except:
                    pass

                log("🔍 提取全量 Cookie...")
                all_cookies = await context.cookies()
                ck_dict = {c['name']: c['value'] for c in all_cookies}
                
                pt_key = ck_dict.get('pt_key')
                pt_pin = ck_dict.get('pt_pin') or ck_dict.get('pin')

                if pt_key:
                    cookie_str = f"pt_key={pt_key};pt_pin={pt_pin};"
                    log(f"🎉 登录成功！用户: {pt_pin}")
                    requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", 
                                 data={"chat_id": TG_CHAT_ID, "text": f"✅ <b>JD登录成功 (QQ)</b>\n\n<code>{cookie_str}</code>", "parse_mode": "HTML"})
                else:
                    log("❌ 未能在 Cookie 中找到 pt_key")
                    await page.screenshot(path="no_cookie.png")
                    send_tg_photo("no_cookie.png", "⚠️ <b>跳转成功但 Cookie 提取失败</b>\n请检查代理稳定性。")
            else:
                log("❌ 监控超时，用户未在规定时间内扫码。")
        else:
            log("❌ 最终未捕获到二维码，请检查 final_debug.png")
            await page.screenshot(path="final_debug.png")
            send_tg_photo("final_debug.png", "❌ <b>无法获取二维码</b>")

        await browser.close()
        log("🏁 任务结束")

if __name__ == "__main__":
    if TG_TOKEN and TG_CHAT_ID:
        asyncio.run(run_qq_login())
    else:
        log("❌ 环境变量错误：请检查 TG_BOT_TOKEN 和 TG_CHAT_ID")
