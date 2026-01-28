import os
import sys
import time
import json
import base64
import requests
from nacl import public, encoding
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(line_buffering=True)

EMAIL = os.getenv("GLADOS_EMAIL")
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")
REPO = os.getenv("GITHUB_REPOSITORY")
REPO_TOKEN = os.getenv("REPO_TOKEN")
GLADOS_LOCAL = os.getenv("GLADOS_LOCAL")  # 可为空

def die(msg):
    raise RuntimeError(msg)

if not EMAIL:
    die("❌ 缺少 GLADOS_EMAIL")
if not TG_BOT_TOKEN:
    die("❌ 缺少 TG_BOT_TOKEN")
if not TG_CHAT_ID:
    die("❌ 缺少 TG_CHAT_ID")

class SecretUpdater:
    def __init__(self, name):
        self.name = name
        print(f"🔐 SecretUpdater 初始化: {name}")

    def update(self, value):
        print("📝 准备回写 GitHub Secret")
        if not REPO or not REPO_TOKEN:
            print("⚠ 未配置 GITHUB_REPOSITORY / REPO_TOKEN，跳过")
            return

        headers = {"Authorization": f"token {REPO_TOKEN}", "Accept": "application/vnd.github.v3+json"}
        r = requests.get(f"https://api.github.com/repos/{REPO}/actions/secrets/public-key", headers=headers, timeout=30)
        r.raise_for_status()
        key = r.json()

        pk = public.PublicKey(key["key"].encode(), encoding.Base64Encoder())
        encrypted = public.SealedBox(pk).encrypt(value.encode())

        r = requests.put(
            f"https://api.github.com/repos/{REPO}/actions/secrets/{self.name}",
            headers=headers,
            json={"encrypted_value": base64.b64encode(encrypted).decode(), "key_id": key["key_id"]},
            timeout=30
        )
        print(f"✅ Secret 更新完成，HTTP {r.status_code}")

class GLaDOSAuto:
    def log(self, msg):
        print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

    # ---------- Telegram ----------
    def tg_send(self, text):
        self.log("📤 尝试发送 Telegram 消息")
        resp = requests.post(f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
                             json={"chat_id": TG_CHAT_ID, "text": text}, timeout=10)
        self.log(f"📬 TG HTTP 状态码: {resp.status_code}")
        self.log(f"📬 TG 返回内容: {resp.text}")
        if resp.status_code != 200:
            die("❌ Telegram 消息发送失败")

    def tg_wait_code(self, timeout=300):
        self.log("📡 开始轮询 Telegram 验证码")
        self.tg_send("📨 GLaDOS 登录验证码已发送\n请回复指令：\n/code 123456")
        offset = None
        start_time = time.time()
        sent_time = int(time.time())
        while time.time() - start_time < timeout:
            resp = requests.get(f"https://api.telegram.org/bot{TG_BOT_TOKEN}/getUpdates",
                                params={"offset": offset, "timeout": 10}, timeout=15).json()
            self.log(f"📥 TG updates raw: {resp}")
            for item in resp.get("result", []):
                offset = item["update_id"] + 1
                msg = item.get("message", {})
                msg_time = msg.get("date", 0)
                text = msg.get("text", "")
                # 只取发送验证码请求后的新消息
                if text.startswith("/code") and msg_time >= sent_time:
                    code = text.replace("/code", "").strip()
                    if code.isdigit():
                        self.log(f"✅ 收到【新】验证码: {code}")
                        return code
            self.log("⌛ 未收到新验证码，5 秒后重试")
            time.sleep(5)
        die("⛔ Telegram 验证码等待超时")

    # ---------- GLaDOS 登录 & session ----------
    def run(self):
        self.log("STEP 1: 启动 Playwright")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            if GLADOS_LOCAL:
                try:
                    storage = json.loads(GLADOS_LOCAL)
                    self.log("♻️ 使用缓存 session")
                    context = browser.new_context(storage_state=storage)
                except Exception:
                    self.log("⚠ GLADOS_LOCAL 无效，新建 session")
                    context = browser.new_context()
            else:
                self.log("🆕 新建 session")
                context = browser.new_context()

            page = context.new_page()

            try:
                # 判断是否需要登录
                if not self.is_logged_in(page):
                    self.login(page)
                # 登录成功后保存最新 storage
                storage_state = page.context.storage_state()
                SecretUpdater("GLADOS_LOCAL").update(json.dumps(storage_state))

                # 执行签到
                self.checkin(page)
            finally:
                browser.close()

    def login(self, page):
        self.log("🔐 执行登录")
        page.goto("https://glados.cloud/login", timeout=60000)
        page.fill("input#email", EMAIL)
        page.click("button:has-text('Get Code')")
        time.sleep(2)
        code = self.tg_wait_code()
        page.fill("input#mailcode", code)
        page.click("button:has-text('Login')")
        time.sleep(3)
        if not self.is_logged_in(page):
            self.dump_debug(page, "login_failed")
            die("❌ 登录失败")

    def is_logged_in(self, page):
        try:
            token = page.evaluate("""() => localStorage.getItem("token")""")
            return bool(token)
        except Exception:
            return False

    def checkin(self, page):
        self.log("🚀 执行签到")
        token = page.evaluate("""() => localStorage.getItem("token")""")
        cookies = page.context.cookies()
        cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
        headers = {
            "accept": "application/json, text/plain, */*",
            "content-type": "application/json;charset=UTF-8",
            "cookie": cookie_str
        }
        resp = requests.post("https://glados.cloud/api/user/checkin",
                             headers=headers, json={"token": "glados.cloud"}, timeout=10)
        try:
            self.log(f"📊 签到返回: {resp.json()}")
        except Exception:
            self.log(f"📊 签到返回非 JSON: {resp.text}")

    def dump_debug(self, page, name):
        self.log(f"📸 Dump debug: {name}")
        with open(f"{name}.html", "w", encoding="utf-8") as f:
            f.write(page.content())
        page.screenshot(path=f"{name}.png")

if __name__ == "__main__":
    GLaDOSAuto().run()
