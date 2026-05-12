import os
import requests
from cloakbrowser import launch

# --- 从 GitHub Secrets / 系统变量读取配置 ---
def get_env_config():
    return {
        "tg_token": "8525533877:AAGJDqO5TmqtJatwW-tZoDcc8LPtLVVcD8Y",#os.getenv("TG_BOT_TOKEN"),
        "tg_chat_id": 1966630851,#os.getenv("TG_CHAT_ID"),
        "email": "yxl5102@gmail.com",#os.getenv("LOGIN_EMAIL"),
        "password": "you1987925",#os.getenv("LOGIN_PASSWORD"),
        "proxy": "socks://jz.hndz.qzz.io:19873",#os.getenv("PROXY_URL"),
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
    proxy_url = cfg["proxy"]
    
    browser = launch(
        proxy=proxy_url,
        geoip=False,  # 既然报错，先关掉它防止初始化挂起
        headless=True,
        humanize=True,
        args=[
            "--no-sandbox",
            "--disable-gpu",
            # 关键：强制浏览器底层所有流量走代理
            f"--proxy-server={proxy_url}",
            # 移除自动化指纹
            "--disable-blink-features=AutomationControlled",
            # 伪装一个真实的 User-Agent
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ]
    )
    
    page = browser.new_page()
    try:
        print("🚀 正在发起请求...")
        # 增加超时到 60s，因为 Cloudflare 验证可能需要时间
        page.goto(cfg["url"], wait_until="load", timeout=60000)
        
        # 延迟 10 秒给 Cloudflare 盾或人机验证自动处理时间
        page.wait_for_timeout(10000)
        
        # 打印当前标题和 URL 帮助调试
        print(f"当前页面标题: {page.title()}")
        print(f"当前页面 URL: {page.url}")

        # 截图 1：查看是否卡在验证码
        send_tg_photo(page.screenshot(), f"📸 初始加载状态\n标题: {page.title()}", cfg)

        # 尝试处理常见的 Turnstile 验证码（如果有的话）
        # 这里的原理是利用 CloakBrowser 的 humanize 模拟点击页面中心或特定区域
        if "Just a moment" in page.title():
            print("检测到 Cloudflare 5秒盾，尝试模拟点击...")
            page.mouse.click(200, 200) # 尝试点击可能的验证框位置
            page.wait_for_timeout(10000)

        print("🔍 尝试查找输入框...")
        # 扩展选择器范围，并改用 'attached' 状态尝试捕获非显示元素
        email_selector = 'input[placeholder*="邮箱"], input[name="email"], input[type="text"]'
        
        try:
            # 先等待元素出现在 DOM 中
            page.wait_for_selector(email_selector, state="attached", timeout=15000)
            # 再等待它变为可见
            page.wait_for_selector(email_selector, state="visible", timeout=5000)
        except Exception as e:
            # 如果还是找不到，发送 HTML 源码片段到日志，分析到底加载了什么
            content = page.content()[:1000] # 只打印前 1000 字符
            print(f"页面源码片段: {content}")
            raise Exception("无法定位登录框，可能是被 CF 拦截或页面结构改变")

        # 执行后续登录逻辑...
        page.type(email_selector, cfg["email"], delay=150)
        page.type('input[type="password"]', cfg["password"], delay=150)
        page.keyboard.press("Enter") # 有时点击登录按钮无效，用回车更稳
        
        page.wait_for_timeout(10000)
        send_tg_photo(page.screenshot(), "✅ 登录尝试后截图", cfg)

    except Exception as e:
        print(f"❌ 运行异常: {e}")
        send_tg_photo(page.screenshot(), f"⚠️ 错误瞬时截图: {str(e)}", cfg)
    finally:
        browser.close()

if __name__ == "__main__":
    run_task()
