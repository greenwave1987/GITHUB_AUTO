import os
import requests
import time
from cloakbrowser import launch

# --- 关键：修改 JS 脚本的定义方式 ---

# 1. 检查是否通过：去掉 return，直接写表达式
_SOLVED_JS = """
!!(document.querySelector('input[name="cf-turnstile-response"]')?.value.length > 20)
"""

# 2. 获取坐标：同样去掉 return，或者确保它是表达式
_COORDS_JS = """
(() => {
    var f = document.querySelector('iframe[src*="challenges"]');
    if (f) {
        var r = f.getBoundingClientRect();
        return {x: Math.round(r.x + 35), y: Math.round(r.y + r.height / 2)};
    }
    return null;
})()
"""

def solve_turnstile(page):
    print("🔍 正在破解 Cloudflare 验证码...")
    for attempt in range(5):
        # 检查是否已解决
        try:
            is_solved = page.evaluate(_SOLVED_JS)
            if is_solved:
                print("✅ 验证已绕过 (Solved)")
                return True
        except Exception as e:
            print(f"⚠️ 检查脚本运行出错: {e}")
        
        # 尝试获取坐标并点击
        try:
            coords = page.evaluate(_COORDS_JS)
            if coords:
                print(f"🎯 发现验证码坐标: {coords}，正在执行模拟点击...")
                page.mouse.move(coords['x'], coords['y'], steps=15)
                page.mouse.click(coords['x'], coords['y'], delay=150)
            else:
                print("❓ 未发现 iframe 元素，等待加载...")
        except Exception as e:
            print(f"⚠️ 坐标脚本运行出错: {e}")

        time.sleep(5)
    
    return page.evaluate(_SOLVED_JS)

# --- 其余 run_task 逻辑保持不变 ---

def run_task():
    cfg = {
        "tg_token": "8525533877:AAGJDqO5TmqtJatwW-tZoDcc8LPtLVVcD8Y",
        "tg_chat_id": 1966630851,
        "email": "yxl5102@gmail.com",
        "password": "you1987925",
        "proxy": "socks5://jz.hndz.qzz.io:19873",
        "url": "https://freecloud.ltd/login"
    }
    
    print("🛠️ 启动浏览器...")
    browser = launch(
        proxy=cfg["proxy"],
        geoip=False,
        headless=True,
        humanize=True,
        args=[
            "--no-sandbox",
            "--disable-gpu",
            f"--proxy-server={cfg['proxy']}",
            "--disable-blink-features=AutomationControlled"
        ]
    )
    
    page = browser.new_page()
    try:
        print(f"🌐 正在打开: {cfg['url']}")
        page.goto(cfg["url"], wait_until="domcontentloaded", timeout=60000)
        
        # 解决验证码
        solve_turnstile(page)
        
        # 截图发送到 TG 看看
        from io import BytesIO
        img = page.screenshot()
        url = f"https://api.telegram.org/bot{cfg['tg_token']}/sendPhoto"
        requests.post(url, files={'photo': ('s.png', img)}, data={'chat_id': cfg['tg_chat_id'], 'caption': f"状态: {page.title()}"})

        # 后续登录逻辑...
        # page.type(...)
        
    except Exception as e:
        print(f"❌ 运行异常: {e}")
    finally:
        browser.close()

if __name__ == "__main__":
    run_task()
