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
import os
import requests
import time
from cloakbrowser import launch

# --- 核心调试工具：在页面上画出点击点 ---
def draw_marker(page, x, y, color="red"):
    """在点击位置注入一个永久的小圆点，方便截图查看"""
    script = f"""
    (lambda() {{
        const marker = document.createElement('div');
        marker.style.position = 'absolute';
        marker.style.left = '{x}px';
        marker.style.top = '{y}px';
        marker.style.width = '12px';
        marker.style.height = '12px';
        marker.style.backgroundColor = '{color}';
        marker.style.borderRadius = '50%';
        marker.style.border = '2px solid white';
        marker.style.zIndex = '10000000';
        marker.style.pointerEvents = 'none';
        marker.style.transform = 'translate(-50%, -50%)';
        document.body.appendChild(marker);
    }})();
    """
    try:
        page.evaluate(script)
    except:
        pass

def solve_turnstile_visual(page, cfg):
    print("🔍 启动【可视化矩阵】穿透...")
    _SOLVED_JS = "!!(document.querySelector('input[name=\"cf-turnstile-response\"]')?.value.length > 20)"
    
    viewport = page.viewport_size
    # 调整后的中心点比例（针对 1280x720 修正）
    base_x = viewport['width'] * 0.13
    base_y = viewport['height'] * 0.32  # 稍微调低了一点 Y 轴

    # 定义矩阵偏移
    offsets = [(0, 0), (30, 0), (-30, 0), (0, 30), (0, -30)]

    for attempt in range(len(offsets)):
        if page.evaluate(_SOLVED_JS):
            print("✅ 验证已提前通过")
            return True

        curr_x = base_x + offsets[attempt][0]
        curr_y = base_y + offsets[attempt][1]
        
        # 1. 模拟真人移动
        page.mouse.move(curr_x, curr_y, steps=10)
        # 2. 画出标记（截图里能看到这些点）
        draw_marker(page, curr_x, curr_y, "red" if attempt > 0 else "blue")
        # 3. 执行点击
        page.mouse.click(curr_x, curr_y, delay=100)
        
        print(f"📍 尝试点击并标记: ({curr_x}, {curr_y})")
        page.wait_for_timeout(2000)

    # 关键：矩阵点完后，发一张带标记的截图到 TG
    print("📡 发送可视化调试截图...")
    send_tg_photo(page.screenshot(), f"📸 调试图：蓝色为中心，红色为矩阵点\n标题: {page.title()}", cfg)
    
    page.wait_for_timeout(5000)
    return page.evaluate(_SOLVED_JS)

def run_task():
    cfg = {
        "tg_token": "8525533877:AAGJDqO5TmqtJatwW-tZoDcc8LPtLVVcD8Y",
        "tg_chat_id": 1966630851,
        "email": "yxl5102@gmail.com",
        "password": "you1987925",
        "proxy": "socks5://jz.hndz.qzz.io:19873",
        "url": "https://freecloud.ltd/login"
    }

    browser = launch(
        proxy=cfg["proxy"],
        geoip=False,
        headless=True,
        humanize=True,
        args=[
            "--no-sandbox",
            "--disable-gpu",
            "--window-size=1280,720",
            "--force-device-scale-factor=1",
            f"--proxy-server={cfg['proxy']}"
        ]
    )
    
    page = browser.new_page()
    try:
        page.goto(cfg["url"], wait_until="domcontentloaded")
        page.wait_for_timeout(5000)

        # 执行可视化穿透
        if not solve_turnstile_visual(page, cfg):
            print("❌ 穿透失败，尝试刷新重来...")
            page.reload()
            page.wait_for_timeout(5000)
        
        # 登录流程
        email_selector = 'input[placeholder*="邮箱"]'
        if page.query_selector(email_selector):
            page.type(email_selector, cfg["email"], delay=100)
            page.type('input[type="password"]', cfg["password"], delay=100)
            page.keyboard.press("Enter")
            page.wait_for_timeout(8000)
            send_tg_photo(page.screenshot(), "🚀 最终任务结果", cfg)
        else:
            print("❌ 依旧未发现表单")

    finally:
        browser.close()

# (send_tg_photo 函数保持不变)

if __name__ == "__main__":
    run_task()
