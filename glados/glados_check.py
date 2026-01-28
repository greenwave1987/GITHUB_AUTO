import os
import json
import time
import requests
from playwright.sync_api import sync_playwright

# ---------- 配置与常量 ----------
LOGIN_URL = "https://glados.cloud/login"
CONSOLE_URL = "https://glados.cloud/console/account"
POINTS_API = "https://glados.cloud/api/user/points"
CHECKIN_API = "https://glados.cloud/api/user/checkin"

# 支持多账号分割
EMAILS = os.environ["GLADOS_EMAIL"].split(",")
TG_TOKEN = os.environ["TG_BOT_TOKEN"]
TG_CHAT_ID = os.environ["TG_CHAT_ID"]
REPO_TOKEN = os.environ["REPO_TOKEN"]

def die(msg):
    print(f"[FATAL] {msg}")
    tg_send(msg)
    raise RuntimeError(msg)

def tg_send(text):
    print(f"[STEP] 📤 尝试发送 Telegram 消息")
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    resp = requests.post(url, json={
        "chat_id": TG_CHAT_ID,
        "text": text
    }, timeout=10)

    print(f"[STEP] 📬 TG HTTP 状态码: {resp.status_code}")
    if resp.status_code != 200:
        print(f"[ERROR] TG 返回内容: {resp.text}")

def tg_wait_code(email, timeout=300):
    print(f"[STEP] 📡 开始轮询 Telegram 验证码")
    tg_send(
        f"📨 GLaDOS 验证码已发送\n"
        f"账号: {email}\n"
        f"请回复指令：\n"
        f"/code 123456"
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

    die(f"⛔ {email} Telegram 验证码等待超时")

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

def login_flow(page, email):
    print(f"[STEP] 打开登录页面: {email}")
    page.goto(LOGIN_URL)

    print("[STEP] 输入邮箱")
    page.fill("#email", email)

    tg_send(f"⚠️ 账号 {email} 即将发送邮箱验证码")
    print("[STEP] 点击 Get Code")
    page.click("button:has-text('Get Code')")

    code = tg_wait_code(email)

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
    print("====== GLaDOS 多账户自动签到开始 ======")
    
    # 解析本地存储状态列表
    local_storage_list = []
    local_raw = os.environ.get("GLADOS_LOCAL")
    if local_raw:
        try:
            # 假设存储也是用特殊方式拼接的，这里按我们的逻辑用列表存储
            local_storage_list = json.loads(local_raw)
            if not isinstance(local_storage_list, list):
                local_storage_list = [local_storage_list]
        except:
            print("[INFO] GLADOS_LOCAL 格式非列表，尝试单账户兼容")
            try: local_storage_list = [json.loads(local_raw)]
            except: local_storage_list = []

    final_storage_list = []

    with sync_playwright() as p:
        launch_args = {
            "headless": True,
            "args": [
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--exclude-switches=enable-automation",
            ]
        }
        browser = p.chromium.launch(**launch_args)

        for index, email in enumerate(EMAILS):
            email = email.strip()
            print(f"\n>>> 正在处理第 {index+1} 个账号: {email}")
            
            # 获取对应的 storage
            current_storage = local_storage_list[index] if index < len(local_storage_list) else None

            context = browser.new_context(
                storage_state=current_storage,
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 Chrome/128.0.0.0"
            )
            page = context.new_page()

            # 登录与校验逻辑
            try:
                is_logged_in = False
                if current_storage:
                    print(f"[INFO] 尝试复用 {email} 的 session")
                    page.goto(CONSOLE_URL)
                    page.wait_for_load_state("networkidle", timeout=60000)
                    time.sleep(3)
                    if check_session_by_points(page):
                        tg_send(f"✅ 账号 {email} 复用 session 成功")
                        is_logged_in = True

                if not is_logged_in:
                    print(f"[INFO] {email} 需要重新登录")
                    login_flow(page, email)
                    if check_session_by_points(page):
                        tg_send(f"✅ 账号 {email} 登录成功")
                    else:
                        save_screenshot(page, f"fail_{email}")
                        print(f"❌ 账号 {email} 登录失败")
                        continue

                # 执行签到
                do_checkin(page)
                tg_send(f"🎉 账号 {email} 签到完成")
                
                # 保存当前账号的新状态
                final_storage_list.append(context.storage_state())

            except Exception as e:
                print(f"[ERROR] 处理账号 {email} 时出错: {e}")
            finally:
                context.close()

        browser.close()

    # 更新所有账号的 Secret 状态
    if final_storage_list:
        update_secret("GLADOS_LOCAL", json.dumps(final_storage_list))
    
    print("\n====== GLaDOS 自动签到结束 ======")

if __name__ == "__main__":
    run()
