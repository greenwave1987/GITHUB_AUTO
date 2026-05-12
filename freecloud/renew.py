import os
import requests
import time
from cloakbrowser import launch

def get_env_config():
    # 提醒：在 GitHub Actions 中建议改回 os.getenv
    return {
        "tg_token": "8525533877:AAGJDqO5TmqtJatwW-tZoDcc8LPtLVVcD8Y",
        "tg_chat_id": 1966630851,
        "email": "yxl5102@gmail.com",
        "password": "you1987925",
        "proxy": "socks5://jz.hndz.qzz.io:19873",
        "url": "https://freecloud.ltd/login"
    }

def send_tg_photo(image_bytes, caption, config):
    if not config["tg_token"]: return
    url = f"https://api.telegram.org/bot{config['tg_token']}/sendPhoto"
    try:
        requests.post(
            url,
            files={'photo': ('ss.png', image_bytes, 'image/png')},
            data={'chat_id': config['tg_chat_id'], 'caption': caption},
            proxies={"http": None, "https": None},
            timeout=20
        )
    except: pass

# --- 核心破解脚本 ---

# 校验验证是否通过
_SOLVED_JS = """
(() => {
    return !!(document.querySelector('input[name="cf-turnstile-response"]')?.value.length > 20);
})()
"""

# 穿透 Shadow DOM 寻找 iframe 的坐标
_COORDS_JS = """
(() => {
    function findIframe(root) {
        // 1. 在当前层级找
        let f = root.querySelector('iframe[src*="challenges"], iframe[title*="Cloudflare"]');
        if (f) return f;
        
        // 2. 递归查找 Shadow DOM
        const elements = root.querySelectorAll('*');
        for (let el of elements) {
            if (el.shadowRoot) {
                let found = findIframe(el.shadowRoot);
                if (found) return found;
            }
        }
        return null;
    }

    const iframe = findIframe(document);
    if (iframe) {
        const r = iframe.getBoundingClientRect();
        if (r.width > 0 && r.height > 0) {
            return {x: Math.round(r.x + 35), y: Math.round(r.y + r.height / 2)};
        }
    }
    return null;
})()
"""

def solve_turnstile(page):
    print("🔍 启动【矩阵覆盖】破解逻辑...")
    
    # 标准校验脚本
    _SOLVED_JS = "!!(document.querySelector('input[name=\"cf-turnstile-response\"]')?.value.length > 20)"

    for attempt in range(6):
        # 1. 检查是否已过
        if page.evaluate(_SOLVED_JS):
            print("✅ 验证已通过")
            return True

        # 2. 尝试利用 Playwright 原生 frame_locator (不依赖 JS 定位)
        try:
            # Turnstile 经常使用固定 title
            cf_frame = page.frame_locator('iframe[title*="Cloudflare"], iframe[src*="challenges"]')
            # 尝试点击 frame 内部的 body (Playwright 会自动计算坐标)
            cf_frame.locator('body').click(timeout=2000)
            print("🎯 原生 Frame 点击指令已发出")
        except:
            pass

        # 3. 矩阵点击逻辑：在 (13%, 28%) 附近 50 像素范围内点 9 个点
        print(f"📡 执行区域矩阵点击 (Attempt {attempt+1})...")
        viewport = page.viewport_size
        center_x = viewport['width'] * 0.13
        center_y = viewport['height'] * 0.28
        
        # 偏移矩阵：中心、上下左右、四个角
        offsets = [
            (0, 0), (20, 0), (-20, 0), (0, 20), (0, -20),
            (30, 30), (-30, -30), (30, -30), (-30, 30)
        ]
        
        for ox, oy in offsets:
            page.mouse.click(center_x + ox, center_y + oy, delay=50)
            # 如果点中了，页面通常会开始刷新或标题改变
            if page.evaluate(_SOLVED_JS):
                print("✨ 矩阵点击命中！验证通过")
                return True

        page.wait_for_timeout(4000)
    
    return page.evaluate(_SOLVED_JS)

def run_task():
    cfg = get_env_config()
    
    print("🛠️ 正在启动浏览器 (UC Mode)...")
    browser = launch(
        proxy=cfg["proxy"],
        geoip=False,
        headless=True,
        humanize=True,
        args=[
            "--no-sandbox",
            "--disable-gpu",
            "--window-size=1280,720",
            f"--proxy-server={cfg['proxy']}",
            "--disable-blink-features=AutomationControlled"
        ]
    )
    
    page = browser.new_page()
    page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

    try:
        print(f"🌐 正在访问: {cfg['url']}")
        page.goto(cfg["url"], wait_until="domcontentloaded", timeout=60000)
        
        # 初始截图
        page.wait_for_timeout(5000)
        send_tg_photo(page.screenshot(), "📸 初始加载状态", cfg)

        # 核心：过盾
        solve_turnstile(page)
        
        # 过盾后截图确认
        page.wait_for_timeout(3000)
        send_tg_photo(page.screenshot(), f"📸 过盾后页面: {page.title()}", cfg)

        # 检查是否成功
        email_selector = 'input[placeholder*="邮箱"], input[name="email"]'
        try:
            page.wait_for_selector(email_selector, state="visible", timeout=10000)
            print("✍️ 正在输入账号密码...")
            page.type(email_selector, cfg["email"], delay=120)
            page.type('input[type="password"]', cfg["password"], delay=150)
            
            page.keyboard.press("Enter")
            print("🖱️ 提交登录中...")
            
            page.wait_for_timeout(10000)
            send_tg_photo(page.screenshot(), f"🚀 最终任务状态\nURL: {page.url}", cfg)
        except:
            print("❌ 未能在页面中找到登录表单")

    except Exception as e:
        print(f"❌ 运行异常: {e}")
        send_tg_photo(page.screenshot(), f"⚠️ 出错截图: {str(e)[:50]}", cfg)
    finally:
        browser.close()

if __name__ == "__main__":
    run_task()
