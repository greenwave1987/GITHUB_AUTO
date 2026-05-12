import os
import requests
import time
from cloakbrowser import launch

def get_env_config():
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
        requests.post(url, files={'photo': ('ss.png', image_bytes)}, 
                      data={'chat_id': config['tg_chat_id'], 'caption': caption},
                      proxies={"http": None, "https": None}, timeout=20)
    except: pass

def draw_click_marker(page, x, y, color="rgba(255, 0, 0, 0.7)"):
    """在页面上绘制一个红圈标记点击位置"""
    script = f"""
    (lambda() {{
        const div = document.createElement('div');
        div.className = 'debug-marker';
        div.style.position = 'absolute';
        div.style.left = '{x}px';
        div.style.top = '{y}px';
        div.style.width = '24px';
        div.style.height = '24px';
        div.style.backgroundColor = '{color}';
        div.style.border = '2px solid white';
        div.style.borderRadius = '50%';
        div.style.zIndex = '2147483647';
        div.style.pointerEvents = 'none';
        div.style.transform = 'translate(-50%, -50%)';
        div.style.boxShadow = '0 0 10px rgba(0,0,0,0.5)';
        document.body.appendChild(div);
    }})();
    """
    page.evaluate(script)

def run_task():
    cfg = get_env_config()
    
    # 强制窗口大小以便比例计算准确
    browser = launch(
        proxy=cfg["proxy"],
        geoip=False,
        headless=True,
        humanize=True,
        args=[
            "--no-sandbox",
            "--window-size=1280,720",
            "--force-device-scale-factor=1"
        ]
    )
    
    page = browser.new_page()
    page.set_viewport_size({"width": 1280, "height": 720})

    try:
        print(f"🚀 访问: {cfg['url']}")
        page.goto(cfg["url"], wait_until="domcontentloaded")
        page.wait_for_timeout(5000)

        # 检查是否过盾
        _SOLVED_JS = "!!(document.querySelector('input[name=\"cf-turnstile-response\"]')?.value.length > 20)"

        if "Just a moment" in page.title():
            print("🛡️ 检测到 Cloudflare，开始矩阵点击测试...")
            
            # 定义 5 个测试点 (中心点 + 四周)
            # 基于你的截图测算：X=13%, Y=28%
            base_x = 1280 * 0.13
            base_y = 720 * 0.28
            
            points = [
                (base_x, base_y),           # 理论中心
                (base_x + 30, base_y),      # 偏右
                (base_x - 30, base_y),      # 偏左
                (base_x, base_y + 30),      # 偏下
                (base_x, base_y - 30)       # 偏上
            ]

            for i, (px, py) in enumerate(points):
                print(f"📍 正在尝试点击坐标: ({px}, {py})")
                
                # 1. 模拟鼠标移动
                page.mouse.move(px, py, steps=10)
                # 2. 画出标记并截图（点击前画点）
                draw_click_marker(page, px, py)
                # 3. 物理点击
                page.mouse.click(px, py, delay=100)
                
                # 4. 每点一下发一张图，caption 标记第几次尝试
                send_tg_photo(page.screenshot(), f"🎯 点击尝试 #{i+1} | 坐标: ({px}, {py})", cfg)
                
                # 5. 检查是否点中了
                page.wait_for_timeout(3000)
                if page.evaluate(_SOLVED_JS):
                    print("✅ 验证通过！")
                    break
        
        # 尝试登录逻辑
        email_selector = 'input[placeholder*="邮箱"]'
        if page.query_selector(email_selector):
            print("✍️ 发现登录框，开始登录...")
            page.type(email_selector, cfg["email"], delay=100)
            page.type('input[type="password"]', cfg["password"], delay=100)
            page.keyboard.press("Enter")
            page.wait_for_timeout(5000)
            send_tg_photo(page.screenshot(), "🚀 登录后最终状态", cfg)
        else:
            print("❌ 仍未发现登录框，请检查坐标截图是否偏离")

    except Exception as e:
        print(f"❌ 异常: {e}")
    finally:
        browser.close()

if __name__ == "__main__":
    run_task()
