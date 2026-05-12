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
    
    # 增加更多防止崩溃的参数
    browser = launch(
        #proxy=cfg["proxy"],
        geoip=True,
        headless=True,
        humanize=True,
        args=[
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage", # 使用 /tmp 而非 /dev/shm，防止大页面崩溃
            "--disable-gpu",           # GitHub 环境不需要显卡加速
            "--no-first-run",
            "--no-zygote",
            "--single-process"         # 降低内存占用
        ]
    )
    
    page = browser.new_page()
    # 设置全局默认超时为 30 秒，防止无限挂起
    page.set_default_timeout(30000) 

    try:
        print("正在打开页面...")
        # 增加手动截图，确保即使失败也能看到最后一秒发生了什么
        page.goto(cfg["url"], wait_until="domcontentloaded", timeout=45000)
        
        # 立即截图一次，确认是否进了 Cloudflare
        send_tg_photo(page.screenshot(), "📸 页面初始加载状态", cfg)

        print("开始定位输入框...")
        # 缩短等待时间，如果 15 秒找不到就直接抛出异常截图
        email_selector = 'input[placeholder*="邮箱"], input[type="email"]'
        
        try:
            page.wait_for_selector(email_selector, state="visible", timeout=15000)
        except Exception:
            print("超时未找到输入框，尝试发送当前页面源码快照")
            send_tg_photo(page.screenshot(), "❌ 找不到输入框，可能卡在验证码", cfg)
            raise Exception("Selector Timeout")

        # 执行输入
        page.type(email_selector, cfg["email"], delay=100)
        page.type('input[type="password"]', cfg["password"], delay=100)
        
        # 点击登录
        page.click('button[type="submit"]')
        
        # 关键：给跳转留出时间
        page.wait_for_timeout(8000)
        send_tg_photo(page.screenshot(), "✅ 登录后最终状态", cfg)

    except Exception as e:
        print(f"执行过程中断: {e}")
        # 最后的保底截图
        try:
            send_tg_photo(page.screenshot(), f"⚠️ 崩溃前截图: {str(e)}", cfg)
        except:
            pass
    finally:
        browser.close()

if __name__ == "__main__":
    run_task()
