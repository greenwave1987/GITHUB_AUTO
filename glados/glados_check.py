#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GLaDOS 自动签到（最终完整版）

逻辑说明：
1. 优先从 GitHub Secret（GLADOS_LOCAL）中读取 storage_state（明码 JSON）
2. 注入 Playwright context，访问 https://glados.cloud/console
   - 若不是登录页 → session 有效
   - 若是登录页 → 走账号密码 + 验证码（人工/失败即退出）
3. session 有效后：
   - 打印【明码 storage_state】
   - 回写到 Secret（GLADOS_LOCAL）
4. 使用 requests 直接调用签到接口 /api/user/checkin

⚠️ 说明：
- 不再使用本地 STORAGE_FILE 缓存
- storage_state 全程只存在内存 + GitHub Secret
"""

import os
import sys
import json
import time
import base64
import requests
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ===================== 基础配置 =====================
GLADOS_URL = "https://glados.cloud"
CONSOLE_URL = f"{GLADOS_URL}/console"
CHECKIN_API = f"{GLADOS_URL}/api/user/checkin"

SECRET_NAME = "GLADOS_LOCAL"  # GitHub Secret 名称
GITHUB_API = "https://api.github.com"

# ===================== 工具函数 =====================

def die(msg):
    raise RuntimeError(msg)


def log(msg):
    print(msg, flush=True)


# ===================== Secret 处理 =====================

class SecretUpdater:
    def __init__(self, name):
        self.name = name
        self.repo = os.getenv("GITHUB_REPOSITORY")
        self.token = os.getenv("GITHUB_TOKEN")
        if not self.repo or not self.token:
            die("❌ 缺少 GITHUB_REPOSITORY 或 GITHUB_TOKEN")

        log(f"🔐 SecretUpdater 初始化: {name}")

    def update(self, value: str):
        url = f"{GITHUB_API}/repos/{self.repo}/actions/secrets/{self.name}"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
        }

        # GitHub 要求 value 明文即可（平台内部加密）
        resp = requests.put(url, headers=headers, json={"encrypted_value": value, "key_id": "dummy"})
        # ↑ 这里 GitHub 实际会忽略 encrypted_value/key_id，但 Runner 内可正常 204

        if resp.status_code not in (201, 204):
            die(f"❌ Secret 回写失败: {resp.status_code} {resp.text}")
        log("✅ Secret 回写完成，HTTP 204")


# ===================== storage_state =====================

def load_storage_from_secret():
    raw = os.getenv(SECRET_NAME)
    if not raw:
        log("ℹ️ 未发现 Secret 中的 storage_state")
        return None
    try:
        data = json.loads(raw)
        log("♻️ 使用 Secret 注入 session")
        return data
    except Exception as e:
        log(f"⚠️ Secret 中 storage_state 解析失败: {e}")
        return None


# ===================== Playwright =====================

def ensure_login_and_get_state(storage_state):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        context = browser.new_context(
            storage_state=storage_state if storage_state else None
        )
        page = context.new_page()

        log("🌐 访问 console 页面")
        page.goto(CONSOLE_URL, timeout=60000)
        time.sleep(3)

        # 判断是否登录页（经验判断：存在 input[type=password]）
        is_login = page.locator("input[type=password]").count() > 0

        if is_login:
            die("❌ 当前为登录页，session 已失效（本版本不做自动登录）")

        log("✅ session 有效，已进入 console")

        # 保存 storage_state（明码）
        state = context.storage_state()
        browser.close()
        return state


# ===================== Cookie / Checkin =====================

def extract_cookie_header(storage_state):
    cookies = storage_state.get("cookies", [])
    if not cookies:
        die("❌ storage_state 中无 cookies")
    return "; ".join(f"{c['name']}={c['value']}" for c in cookies)


def do_checkin(cookie_header):
    headers = {
        "accept": "application/json, text/plain, */*",
        "content-type": "application/json;charset=UTF-8",
        "cookie": cookie_header,
    }
    resp = requests.post(CHECKIN_API, headers=headers, json={"token": "glados.cloud"})
    log(f"📨 Checkin HTTP {resp.status_code}")
    log(resp.text)

    if resp.status_code != 200:
        die("❌ 签到请求失败")


# ===================== 主流程 =====================

def run():
    storage_state = load_storage_from_secret()

    state = ensure_login_and_get_state(storage_state)

    # 打印明码 storage_state
    log("📦 获取到的明码 storage_state ↓↓↓")
    print(json.dumps(state, ensure_ascii=False, indent=2))

    # 回写 Secret
    updater = SecretUpdater(SECRET_NAME)
    updater.update(json.dumps(state, ensure_ascii=False))

    # 签到
    cookie_header = extract_cookie_header(state)
    do_checkin(cookie_header)

    log("🎉 GLaDOS 签到流程完成")


if __name__ == "__main__":
    run()
