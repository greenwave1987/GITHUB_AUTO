import os
import sys
import json
import time
import base64
import requests
from playwright.sync_api import sync_playwright

# ================== 基础配置 ==================
GLADOS_URL = "https://glados.cloud"
CONSOLE_URL = "https://glados.cloud/console"
CHECKIN_API = "https://glados.cloud/api/user/checkin"

SECRET_NAME = "GLADOS_LOCAL"
REPO_TOKEN = os.getenv("REPO_TOKEN")
GITHUB_REPO = os.getenv("GITHUB_REPOSITORY")

TG_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")

# ================== 工具函数 ==================
def log(msg):
    print(msg, flush=True)

def die(msg):
    raise RuntimeError(msg)

# ================== GitHub Secret ==================
class SecretUpdater:
    def __init__(self):
        if not REPO_TOKEN or not GITHUB_REPO:
            die("❌ 缺少 REPO_TOKEN 或 GITHUB_REPOSITORY")
        self.api = f"https://api.github.com/repos/{GITHUB_REPO}/actions/secrets/{SECRET_NAME}"
        self.headers = {
            "Authorization": f"Bearer {REPO_TOKEN}",
            "Accept": "application/vnd.github+json"
        }

    def get_public_key(self):
        r = requests.get(self.api + "/public-key", headers=self.headers)
        if r.status_code != 200:
            die("❌ 获取仓库公钥失败")
        return r.json()

    def update(self, plaintext: str):
        import nacl.encoding
        import nacl.public

        key = self.get_public_key()
        public_key = nacl.public.PublicKey(
            key["key"].encode(), nacl.encoding.Base64Encoder()
        )
        sealed_box = nacl.public.SealedBox(public_key)
        encrypted = sealed_box.encrypt(plaintext.encode())
        encrypted_value = base64.b64encode(encrypted).decode()

        payload = {
            "encrypted_value": encrypted_value,
            "key_id": key["key_id"]
        }

        r = requests.put(self.api, headers=self.headers, json=payload)
        if r.status_code not in (201, 204):
            die(f"❌ Secret 回写失败: {r.status_code} {r.text}")

        log("✅ Secret 回写完成")

# ================== Session 处理 ==================
def load_secret_state():
    raw = os.getenv(SECRET_NAME)
    if not raw:
        return None
    try:
        return json.loads(base64.b64decode(raw).decode())
    except Exception:
        return None

def save_secret_state(state: dict):
    plaintext = base64.b64encode(
        json.dumps(state, ensure_ascii=False).encode()
    ).decode()
    SecretUpdater().update(plaintext)

def extract_glados_cookies(context):
    cookies = context.cookies(GLADOS_URL)
    sess = None
    sig = None
    for c in cookies:
        if c["name"] == "koa:sess":
            sess = c
        elif c["name"] == "koa:sess.sig":
            sig = c
    if not sess or not sig:
        return None
    return [sess, sig]

def cookies_to_header(cookies):
    return "; ".join([f"{c['name']}={c['value']}" for c in cookies])

# ================== Telegram ==================
def tg_send(text):
    if not TG_TOKEN or not TG_CHAT_ID:
        return
    requests.post(
        f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
        json={"chat_id": TG_CHAT_ID, "text": text}
    )

# ================== 核心流程 ==================
def run():
    log("STEP 1: 启动 Playwright")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        state = load_secret_state()
        if state:
            log("♻️ 使用 Secret 注入 session")
            context = browser.new_context(storage_state=state)
        else:
            log("🆕 新建 session")
            context = browser.new_context()

        page = context.new_page()
        page.goto(CONSOLE_URL, wait_until="networkidle")

        cookies = extract_glados_cookies(context)

        # ===== cookie 无效 → 登录 =====
        if not cookies:
            log("🔐 session 无效，执行登录")
            page.goto(GLADOS_URL)

            page.fill("input[type=email]", os.getenv("GLADOS_EMAIL"))
            page.click("button:has-text('Send')")

            code = wait_tg_code()
            page.fill("input[type=text]", code)
            page.click("button:has-text('Login')")

            page.wait_for_load_state("networkidle")
            page.goto(CONSOLE_URL, wait_until="networkidle")

            cookies = extract_glados_cookies(context)
            if not cookies:
                die("❌ 登录后仍未获取到 cookie")

        log("✅ cookie 验证通过")

        # ===== 保存 storage_state =====
        state = context.storage_state()
        log("📦 获取到的明码 storage_state ↓↓↓")
        print(json.dumps(state, indent=2, ensure_ascii=False))

        save_secret_state(state)

        # ===== 签到 =====
        log("🚀 执行签到")
        headers = {
            "Content-Type": "application/json",
            "Cookie": cookies_to_header(cookies),
            "Accept": "application/json"
        }
        resp = requests.post(
            CHECKIN_API,
            headers=headers,
            json={"token": "glados.cloud"}
        ).json()

        log(f"📊 签到返回: {resp}")

        # ===== 提取结果 =====
        item = next(
            (i for i in resp.get("list", []) if i["business"].startswith("system:checkin")),
            None
        )

        if item:
            date = item["business"].split(":")[-1]
            gain = int(float(item["change"]))
            total = int(float(item["balance"]))
            msg = f"checkin:{date} | 获得 {gain} | 总积分 {total}"
        else:
            msg = resp.get("message", "未知结果")

        log(f"✅ {msg}")
        tg_send(f"🟢 GLaDOS 签到结果\n{msg}")

        browser.close()

# ================== TG 验证码 ==================
def wait_tg_code(timeout=180):
    log("📡 等待 Telegram 验证码")
    start = time.time()
    offset = None

    while time.time() - start < timeout:
        r = requests.get(
            f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates",
            params={"offset": offset, "timeout": 10}
        ).json()

        for u in r.get("result", []):
            offset = u["update_id"] + 1
            text = u.get("message", {}).get("text", "")
            if text.startswith("/code"):
                return text.split()[-1]

        time.sleep(5)

    die("❌ 获取验证码超时")

# ================== 启动 ==================
if __name__ == "__main__":
    run()
