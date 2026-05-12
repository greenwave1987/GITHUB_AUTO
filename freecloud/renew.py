import os
import requests
import time
from cloakbrowser import launch

def get_env_config():
    # 提醒：生产环境请使用 os.getenv("KEY")
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

def solve_turnstile(page):
    """
    参考 SeleniumBase 逻辑：
    1. 检查 cf-turnstile-response 是否已生成
    2. JS 精确计算 iframe 坐标
    3. 模拟点击并循环校验
    """
    # 检查验证是否完成的 JS 脚本
    _SOLVED_JS = "return !!(document.querySelector('input[name=\"cf-turnstile-response\"]')?.value.length > 20)"
    
    # 获取 iframe 中心点坐标的 JS 脚本
    _COORDS_JS = """
    (function(){
        var f = document.querySelector('iframe[src*="challenges"]');
        if (f) {
            var r = f.getBoundingClientRect();
            return {x: Math.round(r.x + 35), y: Math.round(r.y + r.height / 2)};
        }
        return null;
    })()
    """

    print("🔍 正在破解 Cloudflare 验证码...")
    for attempt in range(5):
        # 1. 先看一眼是不是已经过了
        if page.evaluate(_SOLVED_JS):
            print("✅ 验证已绕过 (Solved)")
            return True
        
        # 2. 尝试获取物理坐标
        coords = page.evaluate(_COORDS_JS)
        if coords:
            print(f"🎯 发现验证码坐标: {coords}，正在执行模拟点击...")
            # 模拟真人移动并点击
            page.mouse.move(coords['x'], coords['y'], steps=15)
            page.mouse.click(coords['x'], coords['y'], delay=150)
        else:
            print("❓ 未发现 iframe 元素，可能正在加载中...")

        time.sleep(5) # 给 CF 处理跳转的时间
    
    return page.evaluate(_SOLVED_JS)

def run_task():
    cfg = get_env_config()
    proxy_url = cfg["proxy"]
    
    print("🛠️ 启动 UC 模式浏览器...")
    browser = launch(
        proxy=proxy_url,
        geoip=False,
        headless=True,
        humanize=True,
        args=[
            "--no-sandbox",
            "--disable-gpu",
            f"--proxy-server={proxy_url}",
            "--disable-blink-features=AutomationControlled",
            # 强制伪装指纹
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ]
    )
    
    page = browser.new_page()
    # 抹除 WebDriver 特征
    page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

    try:
        print(f"🌐 正在打开: {cfg['url']}")
        page.goto(cfg["url"], wait_until="domcontentloaded", timeout=60000)
        
        # 处理验证码
        if not solve_turnstile(page):
            print("❌ 验证码破解失败")
            send_tg_photo(page.screenshot(), "⚠️ 验证码破解失败截图", cfg)
        else:
            print("🎉 验证码破解成功，准备登录...")
            page.wait_for_timeout(3000)

        # 发送状态截图
        send_tg_photo(page.screenshot(), f"📸 当前页面状态: {page.title()}", cfg)

        # 定位登录框
        email_selector = 'input[placeholder*="邮箱"], input[name="email"]'
        page.wait_for_selector(email_selector, state="visible", timeout=15000)

        print("✍️ 正在输入凭据...")
        # 模拟真人输入
        page.type(email_selector, cfg["email"], delay=120)
        page.type('input[type="password"]', cfg["password"], delay=150)
        
        page.keyboard.press("Enter")
        print("🖱️ 提交登录...")
        
        # 等待跳转到用户中心
        page.wait_for_timeout(10000)
        
        if "/login" not in page.url:
            print("✅ 登录成功！")
            send_tg_photo(page.screenshot(), "🚀 登录成功截图", cfg)
            # 这里可以继续添加签到逻辑...
        else:
            print("❌ 登录可能失败，仍在登录页")
            send_tg_photo(page.screenshot(), "❌ 登录失败截图", cfg)

    except Exception as e:
        print(f"❌ 运行异常: {e}")
        try:
            send_tg_photo(page.screenshot(), f"⚠️ 崩溃瞬时截图: {str(e)[:100]}", cfg)
        except: pass
    finally:
        browser.close()

if __name__ == "__main__":
    run_task()
