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

        print("正在等待页面加载...")
        page.goto(cfg["url"], wait_until="load", timeout=60000)
        page.wait_for_timeout(5000) # 给 CF 盾加载的时间

        # --- 穿透 Cloudflare 核心逻辑 ---
        if "Just a moment" in page.title():
            print("检测到 Turnstile 验证，尝试穿透 iframe 内部...")
            try:
                # 1. 定位 Cloudflare 的 iframe (使用通配符匹配 src)
                # Cloudflare Turnstile 的 URL 通常包含 challenges.cloudflare.com
                cf_frame = page.frame_locator('iframe[src*="challenges.cloudflare.com"]')
                
                # 2. 在 iframe 内部定位那个 checkbox
                # 这里的 input[type="checkbox"] 是你提到的关键元素
                checkbox = cf_frame.locator('input[type="checkbox"]')
                
                # 3. 确保元素存在并执行点击
                # 使用 force=True 因为这类 checkbox 经常被原始 CSS 隐藏，实际显示的是美化后的 div/span
                checkbox.wait_for(state="attached", timeout=10000)
                
                # 尝试点击。如果直接点 input 不行，就点它的父级或者 body
                checkbox.click(force=True)
                print("✅ 已点击 iframe 内部的勾选框")
                
                # 4. 点击后必须给 Cloudflare 时间处理跳转
                page.wait_for_timeout(10000)
                
            except Exception as e:
                print(f"穿透尝试失败: {e}")
                # 如果找不到具体 input，尝试点击 iframe 区域的中心点 (保底方案)
                try:
                    iframe_element = page.query_selector('iframe[src*="challenges"]')
                    if iframe_element:
                        rect = iframe_element.bounding_box()
                        if rect:
                            page.mouse.click(rect['x'] + 30, rect['y'] + rect['height'] / 2)
                            print("🎯 执行了 iframe 区域盲点")
                            page.wait_for_timeout(8000)
                except:
                    pass

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
