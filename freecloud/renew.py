import os
import requests
from cloakbrowser import launch

# --- 从 GitHub Secrets / 系统变量读取配置 ---
def get_env_config():
    return {
        "tg_token": os.getenv("TG_BOT_TOKEN"),
        "tg_chat_id": os.getenv("TG_CHAT_ID"),
        "email": "yxl5102@gmail.com",#os.getenv("LOGIN_EMAIL"),
        "password": "you1987925",#os.getenv("LOGIN_PASSWORD"),
        "proxy": "http://jz.hndz.qzz.io:19873",#os.getenv("PROXY_URL"),
        "url": "https://freecloud.ltd/login"
    }

def send_tg_photo(image_bytes, caption, config):
    if not config["tg_token"]:
        return
    url = f"https://api.telegram.org/bot{config['tg_token']}/sendPhoto"
    files = {'photo': ('ss.png', image_bytes, 'image/png')}
    data = {'chat_id': config['tg_chat_id'], 'caption': caption}
    try:
        # 如果需要 TG 代理（通常 GitHub Actions 访问 TG 不需要额外代理）
        requests.post(url, files=files, data=data, timeout=15)
    except Exception as e:
        print(f"TG 发送失败: {e}")

def run_task():
    cfg = get_env_config()
    browser = launch(
        proxy=cfg["proxy"],
        geoip=True,
        headless=True,
        humanize=True,
        # 针对 Linux 环境的稳定性优化
        args=["--no-sandbox", "--disable-setuid-sandbox"]
    )
    
    page = browser.new_page()
    try:
        # 1. 访问并增加超时时间
        print("正在打开页面...")
        page.goto(cfg["url"], wait_until="networkidle", timeout=60000)
        
        # 2. 检查并处理 Cloudflare 盾 (等待最多 15 秒)
        # 如果页面标题包含 "Just a moment" 或 "Cloudflare"，多等一会儿
        if "Just a moment" in page.title() or "Cloudflare" in page.title():
            print("检测到 Cloudflare 验证，等待中...")
            page.wait_for_timeout(10000) 
        
        send_tg_photo(page.screenshot(), "📍 页面加载检查", cfg)

        # 3. 使用更稳健的等待方式定位元素
        print("尝试定位输入框...")
        # 等待邮箱输入框出现，最多等 20 秒
        email_selector = 'input[type="text"], input[type="email"], input[placeholder*="邮箱"]'
        page.wait_for_selector(email_selector, state="visible", timeout=20000)
        
        # 4. 执行输入
        page.type(email_selector, cfg["email"], delay=120)
        
        # 定位并输入密码
        pass_selector = 'input[type="password"]'
        page.type(pass_selector, cfg["password"], delay=150)
        
        send_tg_photo(page.screenshot(), "✍️ 已填入信息", cfg)

        # 5. 点击登录按钮
        # 有些站点的登录按钮是 div 或者 span 模拟的，尝试多种定位
        login_btn_selector = 'button[type="submit"], .login-button, button:has-text("登录")'
        page.wait_for_selector(login_btn_selector, state="visible")
        page.click(login_btn_selector)
        
        # 6. 等待登录结果
        page.wait_for_timeout(5000)
        send_tg_photo(page.screenshot(), f"🚀 登录后状态\nURL: {page.url}", cfg)

    except Exception as e:
        print(f"执行失败: {str(e)}")
        # 失败时必须截图，通过 TG 里的图你可以看到是卡在了验证码还是没找到框
        try:
            send_tg_photo(page.screenshot(), f"❌ 运行异常: {str(e)}", cfg)
        except:
            pass
    finally:
        browser.close()

if __name__ == "__main__":
    run_task()
