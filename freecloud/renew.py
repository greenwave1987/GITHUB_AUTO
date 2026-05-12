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
            #"--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
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
            print("🛡️ 检测到验证盾，执行精准坐标校准...")
            try:
                # 1. 优先尝试直接锁定 iframe (即使在 Shadow DOM 内部，这个选择器通常也有效)
                iframe = page.query_selector('iframe[title*="Cloudflare"]') or \
                         page.query_selector('iframe[src*="challenges"]')
                
                if iframe:
                    rect = iframe.bounding_box()
                    print(f"📦 发现验证码盒模型: {rect}")
                    
                    # 2. 计算真正中心偏左的点击点
                    # 目标是点击那个小方框，它在 300 宽度的 iframe 里大约位于 x=30 到 x=50 处
                    click_x = rect['x'] + 40 
                    click_y = rect['y'] + rect['height'] / 2
                else:
                    # 3. 如果找不到 iframe，可能是因为 closed shadow root
                    # 我们点击屏幕正中心，这是 Cloudflare 默认放置验证码的位置
                    print("❓ 无法定位元素，执行屏幕中心保底策略...")
                    click_x = 1280 / 2
                    click_y = 651 / 2 - 50 # 稍微偏上一点

                print(f"🎯 修正后的点击坐标: ({click_x}, {click_y})")
                page.mouse.move(click_x, click_y, steps=25)
                page.mouse.click(click_x, click_y)
                
                # 点击后一定要看一眼截图
                page.wait_for_timeout(2000)
                send_tg_photo(page.screenshot(), "📸 点击瞬间记录", cfg)
                
                print("⏳ 等待跳转...")
                page.wait_for_timeout(13000)
                
            except Exception as ce:
                print(f"⚠️ 坐标计算异常: {ce}")

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
