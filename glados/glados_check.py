#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import requests
import base64
from nacl import encoding, public
from playwright.sync_api import sync_playwright

# ===== 配置 =====
REPO = os.getenv("GITHUB_REPOSITORY")
REPO_TOKEN = os.getenv("REPO_TOKEN")
TG_TOKEN = os.getenv("TG_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")

STORAGE_FILE = "glados_storage.json"

# ===== 工具 =====
def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")

def die(msg):
    raise RuntimeError(msg)

# ===== Secret 更新器 =====
class SecretUpdater:
    def __init__(self, name):
        self.name = name
        log(f"🔐 SecretUpdater 初始化: {name}")

    def update(self, value):
        if not REPO or not REPO_TOKEN:
            log("⚠ 未配置 REPO 或 REPO_TOKEN，跳过 Secret 回写")
            return

        headers = {
            "Authorization": f"token {REPO_TOKEN}",
            "Accept": "application/vnd.github.v3+json"
        }

        r = requests.get(f"https://api.github.com/repos/{REPO}/actions/secrets/public-key",
                         headers=headers, timeout=30)
        r.raise_for_status()
        key = r.json()

        pk = public.PublicKey(key["key"].encode(), encoding.Base64Encoder())
        encrypted = public.SealedBox(pk).encrypt(value.encode())

        r2 = requests.put(
            f"https://api.github.com/repos/{REPO}/actions/secrets/{self.name}",
            headers=headers,
            json={
                "encrypted_value": base64.b64encode(encrypted).decode(),
                "key_id": key["key_id"]
            },
            timeout=30
        )
        log(f"✅ Secret 回写完成，HTTP {r2.status_code}")

# ===== Cookie / Storage =====
def save_storage_state(context):
    context.storage_state(path=STORAGE_FILE)
    log(f"💾 保存 storage_state")

def load_storage_state(browser):
    if os.path.exists(STORAGE_FILE):
        log("♻️ 尝试使用缓存 session")
        context = browser.new_context(storage_state=STORAGE_FILE)
        return context
    return None

def extract_cookies(context):
    cookies = context.cookies()
    ck = {}
    for c in cookies:
        if c["name"] in ("koa:sess", "koa:sess.sig"):
            ck[c["name"]] = c["value"]
    if not ck:
        die("❌ 未获取到 GLaDOS session cookies")
    return ck

# ===== 签到 =====
def glados_checkin(cookies):
    url = "https://glados.cloud/api/user/checkin"
    headers = {
        "accept": "application/json, text/plain, */*",
        "content-type": "application/json;charset=UTF-8",
        "user-agent": "Mozilla/5.0"
    }
    resp = requests.post(url, headers=headers, cookies=cookies, json={"token":"glados.cloud"}, timeout=20)
    resp.raise_for_status()
    return resp.json()

def parse_checkin_result(data):
    lst = data.get("list", [])
    for item in lst:
        if item.get("business", "").startswith("system:checkin"):
            date = item["business"].split(":")[-1]
            gain = int(float(item["change"]))
            balance = int(float(item["balance"]))
            return f"checkin:{date} | 获得 {gain} | 总积分 {balance}"
    return data.get("message", "未知结果")

# ===== TG 推送 =====
def send_tg(text):
    if not TG_TOKEN or not TG_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id":TG_CHAT_ID,"text":f"🎉 GLaDOS 签到结果\n{text}"})

# ===== 主流程 =====
def run():
    log("STEP 1: 启动 Playwright")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        context = load_storage_state(browser)
        if context:
            log("✅ 使用缓存登录成功")
        else:
            log("🆕 新建 session")
            context = browser.new_context()
            page = context.new_page()
            page.goto("https://glados.cloud/console", timeout=30000)

            # 登录流程
            log("🔐 执行登录")
            # TODO: 填入你的登录步骤，如输入邮箱 + Telegram 验证码
            # 这里假设 login 成功，等待验证码后完成
            log("📡 开始轮询 Telegram 验证码")
            # 轮询 TG 获取 /code 并填入页面
            # page.fill(...) / page.click(...)

            # 登录完成
            log("✅ 登录成功")
            save_storage_state(context)

        # Secret 回写
        storage_json = open(STORAGE_FILE, "r", encoding="utf-8").read()
        SecretUpdater("GLADOS_LOCAL").update(storage_json)

        # 提取 cookies
        cookies = extract_cookies(context)

        # 执行签到
        log("🚀 执行签到")
        result = glados_checkin(cookies)
        result_str = parse_checkin_result(result)
        log(f"📊 {result_str}")

        # 发送 TG
        send_tg(result_str)

        browser.close()

if __name__ == "__main__":
    run()
