import os, time, json, base64, re, requests
from playwright.sync_api import sync_playwright, TimeoutError

GLADOS_EMAIL = os.getenv("GLADOS_EMAIL")
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")
REPO_TOKEN = os.getenv("REPO_TOKEN")
GLADOS_LOCAL = os.getenv("GLADOS_LOCAL")

REPO = os.getenv("GITHUB_REPOSITORY")


def log(msg):
    print(msg, flush=True)


def die(msg):
    raise RuntimeError(msg)


# ---------------- TG ----------------
def tg_send(text):
    requests.post(
        f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
        json={"chat_id": TG_CHAT_ID, "text": text},
        timeout=10
    )


def tg_wait_code(timeout=180):
    tg_send("📩 已发送邮箱验证码，请回复：/code 123456")
    offset = None
    start = time.time()
    while time.time() - start < timeout:
        r = requests.get(
            f"https://api.telegram.org/bot{TG_BOT_TOKEN}/getUpdates",
            params={"timeout": 10, "offset": offset},
            timeout=15
        ).json()
        for u in r.get("result", []):
            offset = u["update_id"] + 1
            text = u.get("message", {}).get("text", "")
            m = re.search(r"/code\s+(\d{6})", text)
            if m:
                return m.group(1)
        time.sleep(3)
    die("❌ 超时未收到验证码")


# ---------------- GitHub Secret ----------------
def github_public_key():
    r = requests.get(
        f"https://api.github.com/repos/{REPO}/actions/secrets/public-key",
        headers={"Authorization": f"token {REPO_TOKEN}"},
        timeout=10
    )
    r.raise_for_status()
    return r.json()


def update_secret(name, value):
    key = github_public_key()
    import nacl.encoding, nacl.public
    pk = nacl.public.PublicKey(key["key"].encode(), nacl.encoding.Base64Encoder())
    sealed = nacl.public.SealedBox(pk).encrypt(value.encode())
    enc = base64.b64encode(sealed).decode()
    r = requests.put(
        f"https://api.github.com/repos/{REPO}/actions/secrets/{name}",
        headers={"Authorization": f"token {REPO_TOKEN}"},
        json={"encrypted_value": enc, "key_id": key["key_id"]},
        timeout=10
    )
    if r.status_code not in (201, 204):
        die(f"❌ Secret 回写失败 {r.status_code} {r.text}")
    log("✅ Secret 回写完成")


# ---------------- Playwright ----------------
def inject_storage(context, b64):
    try:
        raw = base64.b64decode(b64).decode()
        state = json.loads(raw)
        context.add_cookies(state.get("cookies", []))
        return True
    except Exception:
        return False


def has_valid_cookie(context):
    cookies = context.cookies()
    return any("koa:sess" in c["name"] for c in cookies)


def click_send_code(page, retries=5):
    for attempt in range(retries):
        log(f"🔎 尝试点击发送验证码按钮，第 {attempt+1}/{retries} 次")
        # 先在主页面查找
        btns = page.locator("button:has-text('Send Code'), button:has-text('发送验证码'), button:has-text('发送')")
        if btns.count() > 0:
            try:
                btns.first.click(timeout=5000)
                log("✅ 点击发送验证码按钮成功")
                return
            except TimeoutError:
                pass
        # 再尝试 iframe
        for f in page.frames:
            btns = f.locator("button:has-text('Send Code'), button:has-text('发送验证码'), button:has-text('发送')")
            if btns.count() > 0:
                try:
                    btns.first.click(timeout=5000)
                    log("✅ iframe 内点击发送验证码按钮成功")
                    return
                except TimeoutError:
                    continue
        # 等待 2 秒后重试
        time.sleep(2)
    die("❌ 找不到发送验证码按钮")



# ---------------- Checkin ----------------
def checkin_by_cookie(context):
    cookies = context.cookies()
    sess = next((c for c in cookies if c["name"] == "koa:sess"), None)
    sig = next((c for c in cookies if c["name"] == "koa:sess.sig"), None)
    if not sess or not sig:
        die("❌ 未获取到 session cookie")

    headers = {
        "content-type": "application/json",
        "cookie": f"koa:sess={sess['value']}; koa:sess.sig={sig['value']}"
    }
    r = requests.post(
        "https://glados.cloud/api/user/checkin",
        headers=headers,
        json={"token": "glados.cloud"},
        timeout=15
    )
    data = r.json()
    msg = data.get("message", "")
    line = next((x for x in data.get("list", []) if "checkin:" in x["business"]), None)
    if line:
        date = line["business"].split(":")[-1]
        gain = int(float(line["change"]))
        total = int(float(line["balance"]))
        return f"checkin:{date} | 获得 {gain} | 总积分 {total}"
    return msg


# ---------------- MAIN ----------------
def run():
    log("STEP 1: 启动 Playwright")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()

        if GLADOS_LOCAL and inject_storage(context, GLADOS_LOCAL):
            log("♻️ 注入 Secret session")

        page = context.new_page()
        page.goto("https://glados.cloud/console", timeout=60000)
        page.wait_for_timeout(3000)

        if not has_valid_cookie(context):
            log("🔐 session 无效，执行登录")
            page.goto("https://glados.cloud/login", timeout=60000)
            page.wait_for_load_state("networkidle")

            page.fill("input[type=email]", GLADOS_EMAIL)
            click_send_code(page)
            code = tg_wait_code()
            page.fill("input[type=text]", code)
            page.keyboard.press("Enter")

            page.wait_for_timeout(5000)
            page.screenshot(path="login_result.png")
            tg_send("📸 登录结果截图已生成")

            if not has_valid_cookie(context):
                die("❌ 登录失败，未获得 cookie")

        state = context.storage_state()
        raw = json.dumps(state, ensure_ascii=False)
        print("📦 明码 storage_state ↓↓↓")
        print(raw)

        update_secret("GLADOS_LOCAL", base64.b64encode(raw.encode()).decode())

        result = checkin_by_cookie(context)
        tg_send(f"✅ 签到完成\n{result}")

        browser.close()


if __name__ == "__main__":
    run()
