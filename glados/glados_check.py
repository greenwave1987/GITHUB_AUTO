import os
import time
import sys
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

GLADOS_SECRET = "GLADOS_LOCAL"


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
        print("📝 回写 GitHub Secret")
        if not REPO or not REPO_TOKEN:
            print("⚠ 未配置 GITHUB_REPOSITORY / REPO_TOKEN，跳过")
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
            json={"encrypted_value": base64.b64encode(encrypted).decode(), "key_id": key["key_id"]},
            timeout=30
        )
        print(f"✅ Secret 更新完成，HTTP {r.status_code}")


class GLaDOSAuto:
    def log(self, msg):
        print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

    def tg_send(self, text):
        url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
        resp = requests.post(url, json={"chat_id": TG_CHAT_ID, "text": text}, timeout=10)
        self.log(f"📬 TG HTTP 状态码: {resp.status_code}")
        self.log(f"📬 TG 返回内容: {resp.text}")
        if resp.status_code != 200:
            die("❌ Telegram 消息发送失败")

    def tg_wait_code(self, timeout=300):
        self.log("📡 开始轮询 Telegram 验证码")
        self.tg_send(
            "📨 GLaDOS 登录验证码已发送\n请回复指令：\n/code 123456"
        )

        start = time.time()
        last_date = int(time.time())  # 只取当前时间之后的新消息

        while time.time() - start < timeout:
            resp = requests.get(
                f"https://api.telegram.org/bot{TG_BOT_TOKEN}/getUpdates",
                params={"timeout": 10}, timeout=15
            ).json()
            self.log(f"📥 TG updates raw: {resp}")

            for item in resp.get("result", []):
                msg = item.get("message", {})
                chat_id = msg.get("chat", {}).get("id")
                date = msg.get("date", 0)
                text = msg.get("text", "")

                if chat_id != int(TG_CHAT_ID):
                    continue

                if date <= last_date:
                    continue  # 跳过发送之前的消息

                if text.startswith("/code"):
                    code = text.replace("/code", "").strip()
                    if code.isdigit():
                        self.log(f"✅ 收到【新】验证码: {code}")
                        return code

            self.log("⌛ 未收到新验证码，5 秒后重试")
            time.sleep(5)

        die("⛔ Telegram 验证码等待超时")

    def dump_debug(self, page, name):
        self.log(f"📸 Dump debug: {name}")
        with open(f"{name}.html", "w", encoding="utf-8") as f:
            f.write(page.content())
        page.screenshot(path=f"{name}.png")

    def is_logged_in(self, page):
        token = page.evaluate("""() => localStorage.getItem("token")""")
        return token is not None

    def inject_local(self, page, storage_state):
        self.log("💾 注入缓存 session")
        page.context.add_init_script(f"""() => {{
            const state = {json.dumps(storage_state)};
            for (const [k, v] of Object.entries(state.origins[0].localStorage || {{}})) {{
                localStorage.setItem(k, v);
            }}
        }}""")

    def save_local(self, page):
        self.log("💾 保存 storage_state")
        storage_state = page.context.storage_state()
        SecretUpdater(GLADOS_SECRET).update(json.dumps(storage_state))
        return storage_state

    def login(self, page):
        self.log("🔐 执行登录")
        page.goto("https://glados.cloud/login", timeout=60000)
        page.fill("input#email", EMAIL)
        page.click("button:has-text('Get Code')")
        time.sleep(2)
        code = self.tg_wait_code()
        page.fill("input#mailcode", code)
        page.click("button:has-text('Login')")

        self.log("⏳ 等待登录完成")
        for i in range(30):
            token = page.evaluate("""() => localStorage.getItem("token")""")
            if token:
                self.log("✅ 登录成功")
                return
            time.sleep(1)

        self.dump_debug(page, "login_failed")
        die("❌ 登录失败：localStorage 未生成")

    def checkin(self, page):
        self.log("🚀 执行签到")
        token = page.evaluate("""() => localStorage.getItem("token")""")
        headers = {
            "accept": "application/json, text/plain, */*",
            "accept-language": "zh-CN,zh;q=0.9",
            "cache-control": "no-cache",
            "content-type": "application/json;charset=UTF-8",
            "pragma": "no-cache",
        }
        body = {"token": "glados.cloud"}
        resp = requests.post("https://glados.cloud/api/user/checkin", headers=headers, json=body)
        self.log(f"📊 签到返回: {resp.json()}")

    def run(self):
        self.log("STEP 1: 启动 Playwright")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            try:
                storage_state = None
                # 尝试读取缓存 Secret
                if REPO_TOKEN and REPO:
                    self.log("♻️ 尝试使用缓存 session")
                    try:
                        from base64 import b64decode
                        headers = {"Authorization": f"token {REPO_TOKEN}", "Accept": "application/vnd.github.v3+json"}
                        r = requests.get(f"https://api.github.com/repos/{REPO}/actions/secrets/{GLADOS_SECRET}", headers=headers)
                        if r.status_code == 200:
                            enc_secret = r.json().get("encrypted_value")
                            self.log("⚠ 注意：无法直接解密，默认重新登录")
                    except Exception:
                        pass

                self.login(page)
                storage_state = self.save_local(page)
                self.checkin(page)

            finally:
                browser.close()


if __name__ == "__main__":
    GLaDOSAuto().run()
