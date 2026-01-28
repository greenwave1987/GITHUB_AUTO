import os
import re
import time
import json
import base64
import requests
from playwright.sync_api import sync_playwright


LOGIN_URL = "https://glados.cloud/login"
CHECKIN_API = "https://glados.cloud/api/user/checkin"
CODE_WAIT = 180


# ================= Telegram =================

class Telegram:
    def __init__(self):
        self.token = os.environ.get("TG_BOT_TOKEN")
        self.chat_id = os.environ.get("TG_CHAT_ID")
        self.ok = bool(self.token and self.chat_id)

    def send(self, msg):
        if not self.ok:
            return
        try:
            requests.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                data={"chat_id": self.chat_id, "text": msg},
                timeout=20
            )
        except:
            pass

    def wait_code(self, timeout=180):
        if not self.ok:
            return None

        offset = 0
        pattern = re.compile(r"^/code\s+(\d{4,8})$")
        end = time.time() + timeout

        while time.time() < end:
            try:
                r = requests.get(
                    f"https://api.telegram.org/bot{self.token}/getUpdates",
                    params={"timeout": 20, "offset": offset},
                    timeout=30
                )
                data = r.json()
                if not data.get("ok"):
                    continue

                for upd in data.get("result", []):
                    offset = upd["update_id"] + 1
                    msg = upd.get("message", {})
                    if str(msg.get("chat", {}).get("id")) != str(self.chat_id):
                        continue

                    text = (msg.get("text") or "").strip()
                    m = pattern.match(text)
                    if m:
                        return m.group(1)
            except:
                pass

            time.sleep(2)

        return None


# ================= GitHub Secret =================

class SecretUpdater:
    def __init__(self):
        self.token = os.environ.get("REPO_TOKEN")
        self.repo = os.environ.get("GITHUB_REPOSITORY")
        self.ok = bool(self.token and self.repo)

    def update(self, name, value):
        if not self.ok:
            return False

        try:
            from nacl import public, encoding

            headers = {
                "Authorization": f"token {self.token}",
                "Accept": "application/vnd.github+json"
            }

            r = requests.get(
                f"https://api.github.com/repos/{self.repo}/actions/secrets/public-key",
                headers=headers, timeout=20
            )
            key = r.json()
            pk = public.PublicKey(key["key"].encode(), encoding.Base64Encoder())
            encrypted = public.SealedBox(pk).encrypt(value.encode())

            r = requests.put(
                f"https://api.github.com/repos/{self.repo}/actions/secrets/{name}",
                headers=headers,
                json={
                    "encrypted_value": base64.b64encode(encrypted).decode(),
                    "key_id": key["key_id"]
                },
                timeout=20
            )
            return r.status_code in (201, 204)
        except:
            return False


# ================= 主逻辑 =================

class GLaDOSAuto:
    def __init__(self):
        self.email = os.environ.get("GLADOS_EMAIL")
        self.tg = Telegram()
        self.secret = SecretUpdater()

    def run(self):
        if not self.email:
            raise RuntimeError("缺少 GLADOS_EMAIL")

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled"
                ]
            )
            ctx = browser.new_context()
            page = ctx.new_page()

            # 反检测
            page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            """)

            # 1️⃣ 打开登录页
            page.goto(LOGIN_URL, timeout=60000)
            page.wait_for_selector("#email")

            # 2️⃣ 输入邮箱
            page.fill("#email", self.email)
            time.sleep(0.5)

            # 3️⃣ Get Code
            page.click('button:has-text("Get Code")')

            self.tg.send(
                "📧 <b>GLaDOS 登录</b>\n\n"
                "验证码已发送，请在 Telegram 发送：\n"
                "/code 123456"
            )

            # 4️⃣ 等验证码
            code = self.tg.wait_code(CODE_WAIT)
            if not code:
                raise RuntimeError("验证码超时")

            # 5️⃣ 输入验证码
            page.fill("#mailcode", code)
            time.sleep(0.5)

            # 6️⃣ Login
            page.click('button:has-text("Login")')
            page.wait_for_load_state("domcontentloaded")
            time.sleep(2)

            if "/login" in page.url:
                raise RuntimeError("登录失败")

            # 7️⃣ 读取 localStorage
            local_data = page.evaluate("""
            () => {
                let data = {};
                for (let i = 0; i < localStorage.length; i++) {
                    let k = localStorage.key(i);
                    data[k] = localStorage.getItem(k);
                }
                return data;
            }
            """)

            # 保存 localStorage
            self.secret.update("GLADOS_LOCALSTORAGE", json.dumps(local_data))
            self.tg.send("🔐 登录成功，localStorage 已保存")

            # 8️⃣ 签到（在浏览器上下文中 fetch）
            res = page.evaluate(f"""
            () => fetch("{CHECKIN_API}", {{
                method: "POST",
                credentials: "include",
                headers: {{
                    "content-type": "application/json;charset=UTF-8"
                }},
                body: JSON.stringify({{ token: "glados.cloud" }})
            }}).then(r => r.json())
            """)

            self.tg.send(f"✅ 签到结果:\n{json.dumps(res, indent=2)}")
            print("签到结果:", res)

            browser.close()


if __name__ == "__main__":
    GLaDOSAuto().run()
