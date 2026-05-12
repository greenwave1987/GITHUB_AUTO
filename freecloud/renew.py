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

def send_tg(config, caption, image=None):
    """通用 TG 推送函数"""
    url = f"https://api.telegram.org/bot{config['tg_token']}/"
    try:
        if image:
            requests.post(url + "sendPhoto", files={'photo': ('s.png', image)}, 
                          data={'chat_id': config['tg_chat_id'], 'caption': caption}, timeout=20)
        else:
            requests.post(url + "sendMessage", data={'chat_id': config['tg_chat_id'], 'text': caption}, timeout=10)
    except: pass

def solve_turnstile(page, config):
    """针对坐标 (211, 340) 的循环点击逻辑"""
    # 监测验证是否成功的脚本
    CHECK_JS = "!!(document.querySelector('input[name=\"cf-turnstile-response\"]')?.value.length > 20)"
    
    print(f"🎯 开始目标点击: (211, 340)")
    for i in range(10):  # 最多尝试 10 次点击
        if page.evaluate(CHECK_JS):
            print("✅ 验证成功通过！")
            return True
        
        # 执行点击
        page.mouse.click(211, 340, delay=150)
        print(f"🖱️ 第 {i+1} 次点击已执行...")
        
        time.sleep(4)  # 每次点击后等待 CF 反应
        
        # 每 3 次点击发一次截图确认状态
        if (i + 1) % 3 == 0:
            send_tg(config, f"📸 点击中状态确认 (第{i+1}次)", page.screenshot())
            
    return page.evaluate(CHECK_JS)

def run_task():
    cfg = get_env_config()
    
    browser = launch(
        proxy=cfg["proxy"],
        headless=True,
        humanize=True,
        args=[
            "--no-sandbox",
            "--window-size=1280,720",
            "--force-device-scale-factor=1",
            f"--proxy-server={cfg['proxy']}"
        ]
    )
    
    page = browser.new_page()
    # 强制设定视口，确保坐标一致
    page.set_viewport_size({"width": 1280, "height": 720})

    try:
        print(f"🚀 访问目标: {cfg['url']}")
        page.goto(cfg["url"], wait_until="domcontentloaded")
        time.sleep(5)

        # 1. 穿透验证
        if solve_turnstile(page, cfg):
            print("🔓 穿透成功，准备登录...")
            time.sleep(2)
            
            # 2. 登录逻辑
            email_input = 'input[placeholder*="邮箱"]'
            if page.query_selector(email_input):
                page.type(email_input, cfg["email"], delay=100)
                page.type('input[type="password"]', cfg["password"], delay=100)
                page.keyboard.press("Enter")
                
                time.sleep(8)
                send_tg(cfg, "🚀 登录完成，查看最终状态", page.screenshot())
            else:
                print("❌ 穿透可能成功但未发现表单")
        else:
            print("❌ 循环点击后仍未通过验证")
            send_tg(cfg, "⚠️ 最终未通过验证", page.screenshot())

    except Exception as e:
        print(f"❌ 运行异常: {e}")
    finally:
        browser.close()

if __name__ == "__main__":
    run_task()
