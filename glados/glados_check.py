#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, time, json, base64, requests
from nacl import public, encoding
from playwright.sync_api import sync_playwright

# -------------------------------
# 配置
# -------------------------------
GLADOS_EMAIL = os.getenv("GLADOS_EMAIL")
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")
REPO = os.getenv("REPO")
REPO_TOKEN = os.getenv("REPO_TOKEN")
SECRET_NAME = "GLADOS_LOCAL"

# -------------------------------
# 错误退出
# -------------------------------
def die(msg):
    raise RuntimeError(msg)

# -------------------------------
# TG 消息
# -------------------------------
def send_tg(text):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        print("⚠ TG 配置缺失，跳过发送")
        return
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    data = {"chat_id": TG_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try:
        r = requests.post(url, data=data, timeout=15)
        print(f"📬 TG 返回: {r.status_code}")
    except Exception as e:
        print(f"⚠ TG 发送异常: {e}")

def send_tg_screenshot(page, caption="GLaDOS 页面"):
    screenshot_path = "/tmp/glados_page.png"
    page.screenshot(path=screenshot_path, full_page=True)
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        print("⚠ TG 配置缺失，跳过截图发送")
        return
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendPhoto"
    with open(screenshot_path, "rb") as f:
        files = {"photo": f}
        data = {"chat_id": TG_CHAT_ID, "caption": caption}
        r = requests.post(url, data=data, files=files)
        print(f"📷 TG 截图发送返回: {r.status_code}")

# -------------------------------
# GitHub Secret 更新
# -------------------------------
class SecretUpdater:
    def __init__(self, name):
        self.name = name
        print(f"🔐 SecretUpdater 初始化: {name}")

    def update(self, value):
        if not REPO or not REPO_TOKEN:
            print("⚠ 未配置 REPO / REPO_TOKEN，跳过 Secret 更新")
            return
        headers = {"Authorization": f"token {REPO_TOKEN}", "Accept": "application/vnd.github.v3+json"}
        # 获取公钥
        r = requests.get(f"https://api.github.com/repos/{REPO}/actions/secrets/public-key", headers=headers, timeout=30)
        r.raise_for_status()
        key = r.json()
        # 加密
        pk = public.PublicKey(key["key"].encode(), encoding.Base64Encoder())
        encrypted = public.SealedBox(pk).encrypt(value.encode())
        # 提交 Secret
        r2 = requests.put(
            f"https://api.github.com/repos/{REPO}/actions/secrets/{self.name}",
            headers=headers,
            json={"encrypted_value": base64.b64encode(encrypted).decode(), "key_id": key["key_id"]},
            timeout=30
        )
        if r2.status_code not in (201, 204):
            die(f"❌ Secret 回写失败: {r2.status_code} {r2.text}")
        print("✅ Secret 更新完成")

# -------------------------------
# 判断 session 有效
# -------------------------------
def is_session_valid(context):
    cookies = context.cookies()
    for c in cookies:
        if c.get("name") == "koa:sess":
            return True
    return False

# -------------------------------
# 轮询 TG 获取验证码
# -------------------------------
def poll_tg_code():
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/getUpdates"
    print("📡 开始轮询 TG 验证码")
    for _ in range(60):
        r = requests.get(url, timeout=15).json()
        for result in r.get("result", []):
            msg = result.get("message", {}).get("text", "")
            if msg.startswith("/code "):
                code = msg.split(" ")[1]
                print(f"✅ 收到验证码: {code}")
                return code
        time.sleep(5)
    die("❌ 未收到验证码")

# -------------------------------
# 提取签到信息
# -------------------------------
def extract_checkin(resp_json):
    checkin = next((i for i in resp_json.get("list", []) if i["business"].startswith("system:checkin:")), None)
    if not checkin:
        return "⚠ 无签到记录"
    asset = float(checkin["change"])
    balance = float(checkin["balance"])
    date = checkin["business"].split(":")[2]
    return f"{date} | 获得 {asset:g} | 总积分 {balance:g}"

# -------------------------------
# 主流程
# -------------------------------
def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        # 尝试使用 Secret 注入 storage_state
        secret = os.getenv("GLADOS_LOCAL")
        if secret:
            try:
                state = json.loads(secret)
                context.add_cookies(state.get("cookies", []))
                for origin in state.get("origins", []):
                    for item in origin.get("localStorage", []):
                        page.evaluate(f"localStorage.setItem('{item['name']}', '{item['value']}')")
                print("♻️ 使用 Secret 注入 session")
            except Exception as e:
                print(f"⚠ Secret 注入失败: {e}")

        page.goto("https://glados.cloud/console", timeout=30000)
        time.sleep(3)

        # 判断 session
        if not is_session_valid(context):
            print("🔐 session 无效，执行登录")
            send_tg("⚠ GLaDOS 需要邮箱验证码，请先点击发送到邮箱")
            page.fill("input[type=email]", GLADOS_EMAIL)
            page.click("button:has-text('Send')")

            code = poll_tg_code()
            page.fill("input[type=text]", code)
            page.click("button:has-text('Login')")
            time.sleep(3)

            if not is_session_valid(context):
                send_tg_screenshot(page, "❌ 登录失败页面")
                die("❌ 登录失败，未获得 cookie")
            else:
                print("✅ 登录成功")
                send_tg_screenshot(page, "✅ 登录成功页面")

        # 保存最新 storage_state
        state = context.storage_state()
        print("📦 获取到的明码 storage_state ↓↓↓")
        print(json.dumps(state, ensure_ascii=False, indent=2))
        SecretUpdater(SECRET_NAME).update(json.dumps(state, ensure_ascii=False))

        # 执行签到
        resp = page.evaluate("""
            async () => {
                const r = await fetch("https://glados.cloud/api/user/checkin", {
                    method:"POST",
                    headers: {
                        "accept":"application/json, text/plain, */*",
                        "content-type":"application/json;charset=UTF-8"
                    },
                    body: JSON.stringify({token:"glados.cloud"}),
                    credentials:"include"
                });
                return r.json();
            }
        """)
        info = extract_checkin(resp)
        send_tg(f"🚀 GLaDOS 签到结果:\n{info}")

        browser.close()

if __name__ == "__main__":
    run()
