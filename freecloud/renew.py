#上一版本能点击成功过验证
import os
import requests
import time
import re
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
    url = f"https://api.telegram.org/bot{config['tg_token']}/"
    try:
        if image:
            requests.post(url + "sendPhoto", files={'photo': ('s.png', image)}, 
                          data={'chat_id': config['tg_chat_id'], 'caption': caption}, timeout=20)
        else:
            requests.post(url + "sendMessage", data={'chat_id': config['tg_chat_id'], 'text': caption}, timeout=10)
    except: pass

def solve_turnstile(page, cfg):
    """穿透逻辑：监测到'账号登录'按钮即停止点击"""
    LOGIN_TAB = 'a:has-text("账号登录")'
    
    print(f"🎯 开始验证码穿透，监测目标: (211, 340)")
    for i in range(12):
        # 1. 核心监测：如果“账号登录”按钮出现了，说明已经过盾，直接退出循环
        if page.locator(LOGIN_TAB).is_visible():
            print("✨ 检测到【账号登录】按钮，过盾成功，停止点击。")
            return True
        
        # 3. 执行物理点击
        send_tg(cfg, f"🎯 第{i+1}.1次执行过盾", page.screenshot())
        page.mouse.click(211, 340, delay=150)
        print(f"🖱️ 第 {i+1} 次点击执行中...")
        time.sleep(3)
        send_tg(cfg, f"🎯 第{i+1}.2次执行过盾", page.screenshot())
        time.sleep(30)
        
    return page.locator(LOGIN_TAB).is_visible()

def perform_login(page, cfg):
    """表单登录逻辑"""
    try:
        print("📝 开始填写登录表单...")
        # 1. 点击“账号登录”标签确保表单激活
        page.click('a:has-text("账号登录")')
        page.wait_for_timeout(1000)

        # 2. 输入账号
        page.fill('input[name="username"]', cfg["email"])
        send_tg(cfg, "✍️ 表单填写完毕，准备提交", page.screenshot())
        # 3. 输入密码
        page.fill('input[name="password"]', cfg["password"])
        send_tg(cfg, "✍️ 表单填写完毕，准备提交", page.screenshot())

        # 4. 处理数学验证码
        captcha_input = page.locator('input[name="math_captcha"]')
        placeholder = captcha_input.get_attribute("placeholder")
        print(f"🔢 验证码题目: {placeholder}")
        
        # 解析提取数字和运算符，例如 "4 + 9 = ?" -> "4 + 9"
        math_match = re.search(r'(\d+\s*[\+\-\*]\s*\d+)', placeholder)
        if math_match:
            result = str(eval(math_match.group(1)))
            print(f"✅ 计算答案: {result}")
            captcha_input.fill(result)
        send_tg(cfg, "✍️ 表单填写完毕，准备提交", page.screenshot())
        # 5. 点击登录
        send_tg(cfg, "✍️ 表单填写完毕，准备提交", page.screenshot())
        page.click('button:contains("点击登录")')
        send_tg(cfg, "✍️ 表单填写完毕，准备提交", page.screenshot())
        # 6. 等待结果
        page.wait_for_timeout(8000)
        final_url = page.url
        print(f"🚀 登录后跳转 URL: {final_url}")
        send_tg(cfg, f"🏁 任务结束\n当前标题: {page.title()}\nURL: {final_url}", page.screenshot())
        
    except Exception as e:
        print(f"❌ 登录过程异常: {e}")
        send_tg(cfg, f"❌ 登录异常: {str(e)[:100]}", page.screenshot())

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
    page.set_viewport_size({"width": 1280, "height": 720})

    try:
        print(f"🚀 访问目标: {cfg['url']}")
        page.goto(cfg["url"], wait_until="domcontentloaded")
        time.sleep(5)

        # 穿透并登录
        if solve_turnstile(page, cfg):
            perform_login(page, cfg)
        else:
            print("❌ 未能通过验证码检测")
            send_tg(cfg, "⚠️ 穿透失败", page.screenshot())

    finally:
        browser.close()

if __name__ == "__main__":
    run_task()
