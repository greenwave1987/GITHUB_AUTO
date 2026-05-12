import os
import requests
from cloakbrowser import launch

def get_env_config():
    # 建议生产环境使用 os.getenv("KEY")
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
        # 强制不使用代理发送 TG 消息
        res = requests.post(
            url,
            files={'photo': ('ss.png', image_bytes, 'image/png')},
            data={'chat_id': config['tg_chat_id'], 'caption': caption},
            proxies={"http": None, "https": None},
            timeout=20
        )
        print(f"📡 TG 发送状态: {res.status_code}")
    except Exception as e:
        print(f"📡 TG 发送崩溃: {e}")

def run_task():
    cfg = get_env_config()
    proxy_url = cfg["proxy"]
    
    print("🛠️ 正在启动隐身浏览器...")
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
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ]
    )
    
    page = browser.new_page()
    # 抹除自动化特征
    page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

    try:
        print(f"🚀 正在打开: {cfg['url']}")
        page.goto(cfg["url"], wait_until="domcontentloaded", timeout=60000)
        
        # 给 Cloudflare 初始加载时间
        page.wait_for_timeout(10000)
        print(f"当前标题: {page.title()}")

        # --- 穿透 Cloudflare Turnstile ---
        if "Just a moment" in page.title():
            print("🛡️ 检测到 Shadow DOM 封闭验证框，启动坐标计算...")
            try:
                # 1. 定位宿主元素 (含有 template 的那个 div)
                # 你的源码显示它在 <template> 的父级 div 里
                host_selector = 'div:has(input[name="cf-turnstile-response"])'
                page.wait_for_selector(host_selector, timeout=15000)
                
                host_div = page.query_selector(host_selector)
                if host_div:
                    rect = host_div.bounding_box()
                    if rect:
                        # 2. 根据容器位置计算点击点
                        # Turnstile 的复选框通常在 300x65 容器的左侧
                        # 点击位置：x 轴向右偏 30-40 像素，y 轴垂直居中
                        click_x = rect['x'] + 35
                        click_y = rect['y'] + rect['height'] / 2
                        
                        print(f"🎯 物理坐标定位成功: ({click_x}, {click_y})")
                        
                        # 3. 模拟真人移动轨迹并点击
                        page.mouse.move(click_x, click_y, steps=20)
                        page.mouse.click(click_x, click_y)
                        
                        print("✅ 坐标指令已发送，等待 CF 验证响应...")
                        page.wait_for_timeout(15000)
            except Exception as e:
                print(f"❌ 坐标穿透失败: {e}")

        # 发送第一张截图看状态
        send_tg_photo(page.screenshot(), f"📸 页面状态: {page.title()}", cfg)

        # --- 登录逻辑 ---
        print("🔍 查找登录表单...")
        email_input = 'input[placeholder*="邮箱"], input[name="email"]'
        
        # 等待邮箱框出现
        page.wait_for_selector(email_input, state="visible", timeout=20000)
        
        print("✍️ 正在输入凭据...")
        page.type(email_input, cfg["email"], delay=120)
        page.type('input[type="password"]', cfg["password"], delay=150)
        
        # 准备提交
        send_tg_photo(page.screenshot(), "✍️ 信息已填入，准备登录", cfg)
        page.keyboard.press("Enter")
        
        # 等待登录成功后的跳转
        page.wait_for_timeout(10000)
        
        # 最终状态截图
        final_title = page.title()
        send_tg_photo(page.screenshot(), f"🚀 任务结束\n最终页面: {final_title}\nURL: {page.url}", cfg)

    except Exception as e:
        print(f"❌ 运行异常: {e}")
        try:
            send_tg_photo(page.screenshot(), f"⚠️ 崩溃瞬时截图: {str(e)}", cfg)
        except: pass
    finally:
        print("🔒 正在关闭浏览器...")
        browser.close()

if __name__ == "__main__":
    run_task()
