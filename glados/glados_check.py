import os
import json
import time
import requests
from playwright.sync_api import sync_playwright

# ---------- 配置与常量 ----------
LOGIN_URL = "https://glados.cloud/login"
CONSOLE_URL = "https://glados.cloud/console"
POINTS_API = "https://glados.cloud/api/user/points"
CHECKIN_API = "https://glados.cloud/api/user/checkin"

EMAIL = os.environ["GLADOS_EMAIL"]
TG_TOKEN = os.environ["TG_BOT_TOKEN"]
TG_CHAT_ID = os.environ["TG_CHAT_ID"]
REPO_TOKEN = os.environ["REPO_TOKEN"]

def die(msg):
    print(f"[FATAL] {msg}")
    tg_send(msg)
    raise RuntimeError(msg)

def tg_send(text):
    print(f"[STEP] 📤 尝试发送 Telegram 消息")
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage" # 修正了变量名错误
    resp = requests.post(url, json={
        "chat_id": TG_CHAT_ID,
        "text": text
    }, timeout=10)

    print(f"[STEP] 📬 TG HTTP 状态码: {resp.status_code}")
    if resp.status_code != 200:
        print(f"[ERROR] TG 返回内容: {resp.text}")

def tg_wait_code(timeout=300):
    print(f"[STEP] 📡 开始轮询 Telegram 验证码")
    tg_send(
        "📨 GLaDOS 登录验证码已发送\n"
        "请回复指令：\n"
        "/code 123456"
    )

    offset = None
    start = time.time()

    while time.time() - start < timeout:
        try:
            resp = requests.get(
                f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates",
                params={"offset": offset, "timeout": 10},
                timeout=15
            ).json()

            for item in resp.get("result", []):
                offset = item["update_id"] + 1
                msg = item.get("message", {}).get("text", "")

                if msg.startswith("/code"):
                    code = msg.replace("/code", "").strip()
                    if code.isdigit():
                        print(f"[STEP] ✅ 收到验证码: {code}")
                        return code
        except Exception as e:
            print(f"[ERROR] 获取 TG 更新失败: {e}")

        time.sleep(5)

    die("⛔ Telegram 验证码等待超时")

def update_secret(name, value):
    print(f"[STEP] 更新 GitHub Secret: {name}")
    tg_send(f"🔐 更新 GitHub Secret：{name}")
    api = f"https://api.github.com/repos/{os.environ['GITHUB_REPOSITORY']}/actions/secrets/{name}"
    headers = {
        "Authorization": f"token {REPO_TOKEN}",
        "Accept": "application/vnd.github+json"
    }
    r = requests.put(
        api,
        headers=headers,
        json={"encrypted_value": value, "key_id": "dummy"}
    )
    print(f"[RESULT] Secret 更新状态码: {r.status_code}")

def check_session_by_points(page):
    print("[STEP] 使用 /api/user/points 校验 session")
    try:
        result = page.evaluate(
            f"""async () => {{
                const r = await fetch("{POINTS_API}", {{
                    method: "GET",
                    credentials: "include"
                }});
                if (!r.ok) return null;
                return await r.json();
            }}"""
        )
        if result and isinstance(result, dict) and result.get('code') == 0:
            print(f"[OK] session 有效，points 返回成功")
            return True
        print(f"[RESULT] session 无效: {result}")
        return False
    except Exception as e:
        print(f"[ERROR] points 校验异常: {e}")
        return False

def save_screenshot(page, name):
    print(f"[STEP] 保存截图: {name}")
    path = f"/tmp/{name}.png"
    page.screenshot(path=path, full_page=True)
    with open(path, "rb") as f:
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto",
            data={"chat_id": TG_CHAT_ID},
            files={"photo": f}
        )
    print(f"[OK] 截图已发送 TG: {name}")

def login_flow(page):
    print("[STEP] 打开登录页面")
    page.goto(LOGIN_URL)

    print("[STEP] 输入邮箱")
    page.fill("#email", EMAIL)

    tg_send("⚠️ 即将发送邮箱验证码")
    print("[STEP] 点击 Get Code")
    page.click("button:has-text('Get Code')")

    code = tg_wait_code()

    print(f"[STEP] 输入验证码: {code}")
    page.fill("#mailcode", code)

    print("[STEP] 点击 Login")
    page.click("button[type=submit]")

    print("[WAIT] 等待登录完成")
    page.wait_for_load_state("networkidle")
    time.sleep(5)

def do_checkin(page):
    print("[STEP] 执行签到请求")
    page.evaluate(
        """() => fetch("https://glados.cloud/api/user/checkin", {
            method: "POST",
            credentials: "include",
            headers: {"content-type": "application/json"},
            body: JSON.stringify({token: "glados.cloud"})
        })"""
    )
    print("[OK] 签到请求已发送")

def run():
    print("====== GLaDOS 自动签到开始 ======")
    with sync_playwright() as p:
        # --- 准备启动参数 ---
        launch_args = {
            "headless": True,
            "args": [
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--exclude-switches=enable-automation",
            ]
        }

        # --- 读取存储状态 ---
        storage = None
        local_raw = os.environ.get("GLADOS_LOCAL")
        if local_raw:
            try:
                storage = json.loads(local_raw)
                print("[INFO] 检测到 GLADOS_LOCAL，载入 storage_state")
            except Exception as e:
                print(f"[ERROR] 解析 GLADOS_LOCAL 失败: {e}")

        # --- 启动浏览器与上下文 (完全按照你给的参考格式) ---
        browser = p.chromium.launch(**launch_args)
        context = browser.new_context(
            storage_state=storage,
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 Chrome/128.0.0.0"
        )
        
        page = context.new_page()
        # ------------------------------------------

        if storage:
            print("[INFO] 尝试复用 session")
            page.goto(CONSOLE_URL)
            page.wait_for_load_state("networkidle", timeout=60000)
            time.sleep(5)
            
            if "login" in page.url.lower():
                print(f"当前 url:{page.url}")
                save_screenshot(page, "session_failed")
            
            if check_session_by_points(page):
                tg_send("✅ 使用已有 session 成功")
            else:
                tg_send("❌ session 无效，重新登录")
                login_flow(page)
        else:
            print("[INFO] 未检测到 GLADOS_LOCAL")
            tg_send("❌ 无 session，执行登录")
            login_flow(page)

        print("[STEP] 最终 session 校验")
        if not check_session_by_points(page):
            save_screenshot(page, "login_failed")
            die("❌ 登录失败，points 校验未通过")

        save_screenshot(page, "login_success")

        # --- 获取并保存最新的 storage_state (包含 Cookie 和 LocalStorage) ---
        print("[STEP] 读取完整 storage_state")
        new_storage_state = context.storage_state()
        update_secret("GLADOS_LOCAL", json.dumps(new_storage_state))

        do_checkin(page)
        tg_send("🎉 GLaDOS 签到完成")

        browser.close()
        print("====== GLaDOS 自动签到结束 ======")

if __name__ == "__main__":
    run()
