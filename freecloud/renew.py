import requests
from cloakbrowser import launch
import io

# --- 配置区 ---
TG_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")

def send_tg_photo(image_bytes, caption):
    """通过 TG Bot 发送二进制流图片"""
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto"
    files = {'photo': ('screenshot.png', image_bytes, 'image/png')}
    data = {'chat_id': TG_CHAT_ID, 'caption': caption}
    try:
        response = requests.post(url, files=files, data=data)
        return response.json()
    except Exception as e:
        print(f"发送 TG 失败: {e}")

# --- 自动化逻辑 ---
browser = launch(
    proxy="http://your-residential-proxy:port",
    geoip=True,
    headless=False,
    humanize=True,
)

def run_task():
    page = browser.new_page()
    
    try:
        # 步骤 1: 访问页面
        page.goto("https://freecloud.ltd/login", wait_until="networkidle")
        # 捕获截图并转为字节流发送
        shot = page.screenshot() 
        send_tg_photo(shot, "Step 1: 已到达登录页面")

        # 步骤 2: 输入账号
        page.type('input[placeholder*="邮箱"]', "your_email@example.com", delay=100)
        page.type('input[placeholder*="密码"]', "your_password", delay=150)
        shot = page.screenshot()
        send_tg_photo(shot, "Step 2: 账号密码输入完毕")

        # 步骤 3: 点击登录
        login_btn = page.query_selector('button[type="submit"]')
        if login_btn:
            login_btn.click()
            # 登录跳转通常需要时间，等待 3-5 秒
            page.wait_for_timeout(5000) 
            
        # 步骤 4: 结果反馈
        shot = page.screenshot()
        send_tg_photo(shot, f"Step 3: 登录点击后状态 \n当前URL: {page.url}")

    except Exception as e:
        # 错误时截图告警
        error_shot = page.screenshot()
        send_tg_photo(error_shot, f"❌ 运行出错: {str(e)}")
    finally:
        browser.close()

if __name__ == "__main__":
    run_task()
