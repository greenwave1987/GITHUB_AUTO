import os
import json
import time
import base64
import requests
from playwright.sync_api import sync_playwright

GLADOS_CONSOLE = "https://glados.cloud/console"
GLADOS_LOGIN = "https://glados.cloud/login"
CHECKIN_API = "https://glados.cloud/api/user/checkin"


def log(msg):
    print(msg, flush=True)


def die(msg):
    raise RuntimeError(msg)


# ======================
# GitHub Secret 更新器
# ======================
class SecretUpdater:
    def __init__(self):
        self.repo = os.getenv("GITHUB_REPOSITORY")
        self.token = os.getenv("REPO_TOKEN")
        if not self.repo or not self.token:
            die("❌ 缺少 REPO_TOKEN 或 GITHUB_REPOSITORY")

        self.api = f"https://api.github.com/repos/{self.repo}/actions/secrets/GLADOS_LOCAL"
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
        }
        log("🔐 SecretUpdater 初始化完成")

    def update(self, plain_state: dict):
        raw = json.dumps(plain_state, ensure_ascii=False)
        encoded = base64.b64encode(raw.encode()).decode()

        resp = requests.put(
            self.api,
            headers=self.headers,
            json={"encrypted_value": encoded, "key_id": "dummy"},
        )

        if resp.status_code not in (201, 204):
            die(f"❌ Secret 回写失败: {resp.status_code} {resp.text}")

        log("✅ Secret 回写完成，HTTP 204")


# ======================
# Session 工具函数
# ======================
def load_secret_session():
    raw = os.getenv("GLADOS_LOCAL")
    if not raw:
        return None
    try:
        decoded = base64.b64decode(raw).decode()
        return json.loads(decoded)
    except Exception:
        return None


def has_valid_cookie(context):
    cookies = context.cookies()
    for c in cookies:
        if c["domain"].endswith("glados.cloud") and c["name"].startswith("koa:sess"):
            return True
    return False


def extract_glados_cookies(context):
    cookies = context.cookies()
    jar = {}
    for c in cookies:
        if c["domain"].endswith("glados.cloud"):
            jar[c["name"]] = c["value"]
    if not jar:
        die("❌ 未获取到 GLaDOS cookie")
    return jar


# ======================
# Telegram 验证码
# ======================
def wait_tg_code():
    token = os.getenv("TG_BOT_TOKEN")
    chat_id = os.getenv("TG_CHAT_ID")
    if not token or not chat_id:
        die("❌ 缺少 TG 配置")

    offset = None
    for _ in range(30):
        r = requests.get(
            f"https://api.telegram.org/bot{token}/getUpdates",
            params={"offset": offset, "timeout": 5},
        ).json()

        for u in r.get("result", []):
            offset = u["update_id"] + 1
            text = u.get("message", {}).get("text", "")
            if text.startswith("/code"):
                return text.split()[-1]

        log("⌛ 未收到验证码，5 秒后重试")
        time.sleep(5)

    die("❌ Telegram 未收到验证码")


# ======================
# 签到
# ======================
def checkin(cookie_jar):
    resp = requests.post(
        CHECKIN_API,
        headers={"Content-Type": "application/json"},
        cookies=cookie_jar,
        json={"token": "glados.cloud"},
        timeout=10,
    )

    data = resp.json()

    if "list" in data:
        for item in data["list"]:
            if item["business"].startswith("system:checkin"):
                date = item["business"].split(":")[-1]
                gain = int(float(item["change"]))
                balance = int(float(item["balance"]))
                return f"checkin:{date} | 获得 {gain} | 总积分 {balance}"

    return data.get("message", "未知结果")


# ======================
# 主流程
# ======================
def run():
    log("STEP 1: 启动 Playwright")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()

        # 注入 session
        secret_state = load_secret_session()
        if secret_state:
            log("♻️ 使用 Secret 注入 session")
            context.add_cookies(secret_state.get("cookies", []))
            for o in secret_state.get("origins", []):
                context.add_init_script(
                    f"""
                    Object.entries({json.dumps({i['name']: i['value'] for i in o['localStorage']})})
                    .forEach(([k,v])=>localStorage.setItem(k,v));
                    """
                )

        page = context.new_page()
        page.goto(GLADOS_CONSOLE, wait_until="networkidle")

        # 判断 session
        if not has_valid_cookie(context):
            log("🔐 session 无效，执行登录")
            page.goto(GLADOS_LOGIN, wait_until="networkidle")

            page.wait_for_selector("input[type=email]", timeout=15000)
            page.fill("input[type=email]", os.getenv("GLADOS_EMAIL"))
            page.click("button")

            code = wait_tg_code()
            page.fill("input[type=text]", code)
            page.click("button")

            page.wait_for_load_state("networkidle")

            if not has_valid_cookie(context):
                die("❌ 登录失败，未获得 cookie")

        log("✅ session 有效")

        # 保存 storage_state
        state = context.storage_state()
        log("📦 获取到的明码 storage_state ↓↓↓")
        print(json.dumps(state, indent=2, ensure_ascii=False))

        SecretUpdater().update(state)

        # 签到
        log("🚀 执行签到")
        cookies = extract_glados_cookies(context)
        result = checkin(cookies)
        log(f"🎉 签到结果: {result}")

        browser.close()


if __name__ == "__main__":
    run()
