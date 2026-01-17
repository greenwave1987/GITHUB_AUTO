#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Leaflow Playwright + API 自动签到
依赖 engine 目录中的模块
"""
import os
import sys
import json
import time
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from engine.safe_print import enable_safe_print
enable_safe_print()

from engine.notify import send_notify
from engine.playwright_login import (
    open_browser,
    cookies_ok,
    login_and_get_cookies,
)
from engine.main import (
    perform_token_checkin,
    SecretUpdater
)

# ================= 基础配置 =================

LOGIN_URL = "https://leaflow.net/login"
DASHBOARD_URL = "https://leaflow.net/dashboard"
checkin_url = "https://checkin.leaflow.net"
main_site = "https://leaflow.net"
headers={
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1"
}
# ================= 账号 / Cookies =================

def load_accounts():
    raw = os.getenv("LEAFLOW_ACCOUNTS", "").strip()
    if not raw:
        raise RuntimeError("❌ 未设置 LEAFLOW_ACCOUNTS")

    accounts = {}
    for item in raw.split(","):
        email, pwd = item.split(":", 1)
        accounts[email.strip()] = pwd.strip()

    print(f"🔐 读取账号数: {len(accounts)}")
    return accounts


def load_cookies():
    raw = os.getenv("LEAFLOW_COOKIES")
    if not raw:
        print("ℹ️ 未检测到 cookies，首次运行")
        return {}

    try:
        cookies = json.loads(raw)
        print(f"🍪 已加载 cookies 账号数: {len(cookies)}")
        return cookies
    except Exception as e:
        print(f"❌ cookies JSON 解析失败: {e}")
        return {}
# ================= 获取余额和已消费金额 =================
def get_balance_info(page):
    # 访问页面
    page.goto("https://leaflow.net/balance")
    
    # 1. 定位并获取“当前余额”
    # 使用 title 属性定位是最精确的
    balance_locator = page.locator('p[title="点击显示完整格式"]')
    current_balance = balance_locator.text_content()
    
    # 2. 定位并获取“已消费金额”
    # 由于该元素没有 title，且类名与余额相同，可以使用文字特征或索引
    # 这里使用 nth(1) 如果它是页面第二个匹配该类名的 p 标签
    # 或者使用更稳健的方法：寻找不带 title 属性的那个 p 标签
    spent_locator = page.locator('p.text-3xl.font-bold:not([title])')
    spent_amount = spent_locator.text_content()
    
    print(f"当前余额: {current_balance.strip()}")
    print(f"已消费金额: {spent_amount.strip()}")
# ================= 单账号流程 =================

def process_account(email, password, cookies_map):
    print("=" * 60)
    print(f"👤 处理账号: {email}")

    pw, browser, ctx, page = open_browser()
    note = ""

    try:
        # ---------- cookies 尝试 ----------
        if email in cookies_map:
            print("🍪 尝试复用 cookies")
            ctx.add_cookies(cookies_map[email])

            if cookies_ok(page):
                print("✅ cookies 有效")
                note = "cookies复用"
                get_balance_info(page)
            else:
                print("♻ cookies 已失效")
                raise RuntimeError("cookies expired")
        else:
            raise RuntimeError("no cookies")

    except Exception:
        # ---------- 登录 ----------
        print("🔐 执行 Playwright 登录")
        cookies = login_and_get_cookies(page, email, password)
        cookies_map[email] = cookies
        note = "重新登录"

    finally:
        # 同步 cookies
        cookies_map[email] = ctx.cookies()
        browser.close()
        pw.stop()

    # ---------- API 签到 ----------
    print("📡 执行 API 签到")
    ok, msg = perform_token_checkin(cookies_map[email], email, checkin_url, main_site,headers)
    print(f"ℹ️ API 签到: {ok},{msg}")
    return ok, f"{note} | {msg}"


# ================= Main =================

def main():
    accounts = load_accounts()
    cookies_map = load_cookies()
    results = []

    for email, pwd in accounts.items():
        try:
            ok, msg = process_account(email, pwd, cookies_map)
            results.append(f"{'✅' if ok else '❌'} {email} — {msg}")
        except Exception as e:
            results.append(f"❌ {email} — {e}")

    # ---------- 回写 cookies ----------
    SecretUpdater("LEAFLOW_COOKIES").update(
        json.dumps(cookies_map, ensure_ascii=False)
    )

    # ---------- 通知 ----------
    send_notify(
        title="Leaflow 自动签到汇总",
        content="\n".join(results)
    )


if __name__ == "__main__":
    main()
