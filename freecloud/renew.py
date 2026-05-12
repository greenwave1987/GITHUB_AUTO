import os
import requests
from cloakbrowser import launch

# --- 从 GitHub Secrets / 系统变量读取配置 ---
def get_env_config():
    return {
        "tg_token": os.getenv("TG_BOT_TOKEN"),
        "tg_chat_id": os.getenv("TG_CHAT_ID"),
        "email": "yxl5102@gmail.com"#os.getenv("LOGIN_EMAIL"),
        "password": "you1987925"#os.getenv("LOGIN_PASSWORD"),
        "proxy": "https://jz.hndz.qzz.io:19873"#os.getenv("PROXY_URL"),
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
    
    # 基础校验
    if not cfg["email"] or not cfg["proxy"]:
        print("错误: 缺少必要的环境变量 (EMAIL 或 PROXY)")
        return

    # 启动 CloakBrowser
    browser = launch(
        proxy=cfg["proxy"],
        geoip=True,
        headless=True,  # GitHub 必须为 True
        humanize=True,
    )
    
    page = browser.new_page()
    try:
        # 1. 访问页面
        page.goto(cfg["url"], wait_until="networkidle")
        send_tg_photo(page.screenshot(), "📍 页面已加载", cfg)

        # 2. 模拟真人输入
        page.type('input[placeholder*="邮箱"]', cfg["email"], delay=120)
        page.type('input[placeholder*="密码"]', cfg["password"], delay=150)
        
        # 3. 点击登录
        login_btn = page.query_selector('button[type="submit"]')
        if login_btn:
            login_btn.click()
            page.wait_for_timeout(5000) # 等待登录后的跳转
            
        # 4. 最终截图反馈
        send_tg_photo(page.screenshot(), f"🚀 登录尝试完成\n当前URL: {page.url}", cfg)

    except Exception as e:
        print(f"运行出错: {e}")
        if 'page' in locals():
            send_tg_photo(page.screenshot(), f"❌ 运行异常: {str(e)}", cfg)
    finally:
        browser.close()

if __name__ == "__main__":
    run_task()
