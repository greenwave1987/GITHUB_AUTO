#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, sys, time, json, requests
from base64 import b64encode
from nacl import public, encoding
from playwright.sync_api import sync_playwright

# ===== 配置 =====
REPO = os.getenv("GITHUB_REPOSITORY")
REPO_TOKEN = os.getenv("REPO_TOKEN")
STORAGE_FILE = "glados_storage.json"
TG_BOT = os.getenv("TG_BOT")       # Telegram Bot Token
TG_CHAT_ID = os.getenv("TG_CHAT_ID")  # Telegram Chat ID

# ===== 工具函数 =====
def die(msg):
    print(msg)
    raise RuntimeError(msg)

# ===== Secret 回写 =====
class SecretUpdater:
    def __init__(self, name):
        self.name = name
        print(f"🔐 SecretUpdater 初始化: {name}")

    def update(self, value):
        if not REPO or not REPO_TOKEN:
            print("⚠ 未配置 REPO 或 REPO_TOKEN，跳过 Secret 更新")
            return
        headers = {
            "Authorization": f"token {REPO_TOKEN}",
            "Accept": "application/vnd.github.v3+json"
        }
        r = requests.get(f"https://api.github.com/repos/{REPO}/actions/secrets/public-key", headers=headers, timeout=30)
        r.raise_for_status()
        key = r.json()
        pk = public.PublicKey(key["key"].encode(), encoding.Base64Encoder())
        encrypted = public.SealedBox(pk).encrypt(value.encode())
        r = requests.put(
            f"https://api.github.com/repos/{REPO}/actions/secrets/{self.name}",
            headers=headers,
            json={
                "encrypted_value": b64encode(encrypted).decode(),
                "key_id": key["key_id"]
            },
            timeout=30
        )
        print(f"✅ Secret 更新完成，HTTP {r.status_code}")

# ===== Telegram 发送消息 =====
def send_tg(msg):
    if not TG_BOT or not TG_CHAT_ID:
        print("⚠ TG Bot 未配置，跳过推送")
        return
    url = f"https://api.telegram.org/bot{TG_BOT}/sendMessage"
    requests.post(url, data={"chat_id": TG_CHAT_ID, "text": msg})

# ===== 提取 cookies =====
def extract_cookies(context):
    cookies = context.cookies("https://glados.cloud")
    ck = {}
    for c in cookies:
        if c["name"] in ("koa:sess", "koa:sess.sig"):
            ck[c["name"]] = c["value"]
    if not ck:
        die("❌ 未获取到 GLaDOS session cookies")
    return ck

# ===== 提取签到信息 =====
def parse_checkin(resp_json):
    lst = resp_json.get("list", [])
    for item in lst:
        if "checkin:" in item.get("detail",""):
            date = item["detail"].split(":")[1].split("-")[0]
            gain = float(item["change"])
            total = float(item["balance"])
            return f"checkin:{date} | 获得 {int(gain)} | 总积分 {int(total)}"
    return resp_json.get("message", "未知签到结果")

# ===== GLaDOS 自动化 =====
def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = None
        # 尝试使用缓存
        if os.path.exists(STORAGE_FILE):
            print("♻️ 使用缓存 session")
            context = browser.new_context(storage_state=STORAGE_FILE)
        else:
            print("🆕 新建 session")
            context = browser.new_context()

        page = context.new_page()
        page.goto("https://glados.cloud/login")

        # ===== 登录流程 =====
        if not os.path.exists(STORAGE_FILE):
            print("🔐 执行登录")
            page.click("button:has-text('Send')")
            # 轮询 Telegram 验证码
            code = None
            for _ in range(60):
                r = requests.get(f"https://api.telegram.org/bot{TG_BOT}/getUpdates")
                for msg in r.json().get("result", []):
                    text = msg.get("message", {}).get("text","")
                    if text.startswith("/code "):
                        code = text.split(" ")[1].strip()
                        break
                if code:
                    break
                time.sleep(5)
            if not code:
                die("❌ 未收到验证码")
            print(f"✅ 收到验证码: {code}")
            page.fill("input[type=tel]", code)
            page.click("button:has-text('Login')")
            page.wait_for_timeout(2000)
            print("✅ 登录完成")
            # 保存 storage_state
            context.storage_state(path=STORAGE_FILE)
        else:
            print("✅ 使用缓存登录成功")

        # 打印 storage_state
        with open(STORAGE_FILE, "r", encoding="utf-8") as f:
            storage_json = json.load(f)
        print("💾 当前 storage_state:", json.dumps(storage_json, indent=2, ensure_ascii=False))

        # 更新 Secret
        secret = SecretUpdater("GLADOS_LOCAL")
        secret.update(json.dumps(storage_json))

        # ===== 提取 cookies =====
        cookies = extract_cookies(context)
        print("🍪 提取 cookies:", cookies)

        # ===== 执行签到 =====
        page.goto("https://glados.cloud/user/checkin")
        resp = page.evaluate("""
            async () => {
                const r = await fetch("https://glados.cloud/api/user/checkin", {
                    method:"POST",
                    headers: {
                        "accept":"application/json, text/plain, */*",
                        "content-type":"application/json;charset=UTF-8",
                        "cookie": document.cookie
                    },
                    body: JSON.stringify({token:"glados.cloud"})
                });
                return await r.json();
            }
        """)
        msg = parse_checkin(resp)
        print(f"🚀 签到结果: {msg}")
        send_tg(f"🟢 GLaDOS 签到结果: {msg}")

        context.close()
        browser.close()

if __name__ == "__main__":
    run()
