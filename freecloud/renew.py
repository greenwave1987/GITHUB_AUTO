#带点击定位代码
import os
import requests
import time
from cloakbrowser import launch

def draw_and_screenshot(page, x, y, attempt_num, cfg):
    """
    使用更强力的注入方式：在点击位置直接画一个十字准心
    并在页面顶部通过控制台日志确认坐标
    """
    script = f"""
    (() => {{
        const id = 'debug-point-{attempt_num}';
        if (document.getElementById(id)) return;
        const dot = document.createElement('div');
        dot.id = id;
        dot.style.cssText = `
            position: absolute;
            left: {x}px;
            top: {y}px;
            width: 30px;
            height: 30px;
            border: 3px solid #ff0000;
            background-color: rgba(255, 255, 255, 0.5);
            border-radius: 50%;
            z-index: 2147483647;
            pointer-events: none;
            transform: translate(-50%, -50%);
            box-shadow: 0 0 10px black;
        `;
        // 关键：强制插入到 documentElement 而非 body，防止 body 没加载完
        document.documentElement.appendChild(dot);
    }})();
    """
    try:
        page.evaluate(script)
    except:
        pass
    
    # 每点一下，截一张图发一次，方便精准排查
    time.sleep(5) # 给渲染一点时间
    img = page.screenshot()
    url = f"https://api.telegram.org/bot{cfg['tg_token']}/sendPhoto"
    requests.post(url, files={'photo': (f'click_{attempt_num}.png', img)}, 
                  data={'chat_id': cfg['tg_chat_id'], 'caption': f"🎯 第 {attempt_num} 次尝试 | 坐标: ({x}, {y})"})

def solve_turnstile(page, cfg):
    print("🔍 开始高频坐标穿透测试...")
    _SOLVED_JS = "!!(document.querySelector('input[name=\"cf-turnstile-response\"]')?.value.length > 20)"
    
    # 强制设定视口，防止 xvfb 默认大小干扰
    page.set_viewport_size({"width": 1280, "height": 720})
    
    # 重新测算的比例：针对 FreeCloud 的 Turnstile 位置
    # 比例 1: X=13% (505/1280), Y=35% (252/720)
    # 根据你的截图红圈偏移量，重新校准后的坐标
    # 针对第二次截图反馈的精准修正
    points = [
        (211, 340), # 1. 理论中心 (根据红圈位置上移 50，右移 45)
        (241, 340), # 2. 偏右
        (181, 340), # 3. 偏左
        (211, 360), # 4. 偏下
        (211, 300),  # 5. 偏上
        (211, 340), # 1. 理论中心 (根据红圈位置上移 50，右移 45)
        (241, 340), # 2. 偏右
        (181, 340), # 3. 偏左
        (211, 360), # 4. 偏下
        (211, 300),  # 5. 偏上
        (211, 340), # 1. 理论中心 (根据红圈位置上移 50，右移 45)
        (211, 340), # 1. 理论中心 (根据红圈位置上移 50，右移 45)
        (211, 340), # 1. 理论中心 (根据红圈位置上移 50，右移 45)
        (211, 340), # 1. 理论中心 (根据红圈位置上移 50，右移 45)
        (211, 340), # 1. 理论中心 (根据红圈位置上移 50，右移 45)
        (211, 340) # 1. 理论中心 (根据红圈位置上移 50，右移 45)

    ]

    for i, (px, py) in enumerate(points):
        if page.evaluate(_SOLVED_JS):
            print("✅ 验证成功通过！")
            return True
        
        # 1. 模拟移动
        page.mouse.move(px, py, steps=10)
        # 2. 注入标记并截图（你会收到 5 张带红圈的图）
        draw_and_screenshot(page, px, py, i+1, cfg)
        # 3. 点击
        page.mouse.click(px, py, delay=150)
        
        time.sleep(10)
    
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

    print("🛠️ 启动浏览器...")
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
    try:
        print(f"🌐 访问: {cfg['url']}")
        page.goto(cfg["url"], wait_until="domcontentloaded")
        page.wait_for_timeout(5000)

        time.sleep(30)
        # 执行穿透
        solve_turnstile(page, cfg)
        
        # 再次确认是否进入登录页
        email_input = 'input[placeholder*="邮箱"]'
        if page.query_selector(email_input):
            print("✅ 成功穿透，正在填写表单...")
            page.type(email_input, cfg["email"], delay=100)
            page.type('input[type="password"]', cfg["password"], delay=100)
            page.keyboard.press("Enter")
            page.wait_for_timeout(8000)
            img = page.screenshot()
            requests.post(f"https://api.telegram.org/bot{cfg['tg_token']}/sendPhoto", 
                          files={'photo': ('final.png', img)}, data={'chat_id': cfg['tg_chat_id'], 'caption': "🚀 完成"})
        else:
            print("❌ 最终仍未定位到表单")

    finally:
        browser.close()

if __name__ == "__main__":
    run_task()
