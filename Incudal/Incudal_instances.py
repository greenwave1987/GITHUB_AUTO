import os
import json
import time
import random
import string
import logging
import sys
from datetime import datetime
import re
import requests

# ==================== 基础配置 ====================
username = os.environ.get('GH_USERNAME')
BASE_URL = "https://incudal.com"
SSH_KEY_ID = {"greenwave1987":536,"jdtaxi":1015}

# ==================== 日志 ====================

def setup_logger(log_file="incudal_create.log"):
    logger = logging.getLogger("incudal")
    logger.setLevel(logging.INFO)

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(fmt)

    logger.addHandler(sh)
    logger.addHandler(fh)

    return logger


logger = setup_logger()

# ==================== Telegram ====================

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")

def tg_notify(text):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": TG_CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            },
            timeout=10
        )
    except Exception:
        pass

# ==================== Session 构建 ====================

def build_session():
    raw = os.getenv("USER_SESSION")
    if not raw:
        raise RuntimeError("❌ 未设置 USER_SESSION 环境变量")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"❌ USER_SESSION 不是合法 JSON: {e}")

    auth_token = data.get("auth_token")
    cookies = data.get("cookies")

    if not auth_token or not cookies:
        raise RuntimeError("❌ USER_SESSION 必须包含 auth_token 和 cookies")

    session = requests.Session()
    session.headers.update({
        "accept": "application/json, text/plain, */*",
        "user-agent": "Mozilla/5.0 Chrome/143.0",
        "referer": f"{BASE_URL}instances/create",
        "origin": BASE_URL,
        "authorization":auth_token
    })

    for c in cookies or []:
        session.cookies.set(
            c["name"],
            c["value"],
            domain=c.get("domain"),
            path=c.get("path", "/")
        )
    return session

# ==================== 工具函数 ====================

def random_instance_name(prefix="ss"):
    date = datetime.now().strftime("%Y%m%d")
    rand = "".join(random.choices(string.ascii_lowercase + string.digits, k=4))
    return f"{prefix}-{date}-{rand}"

# ==================== API ====================

def get_packages(session):
    r = session.get(f"{BASE_URL}/api/packages", timeout=15)
    r.raise_for_status()
    return r.json().get("packages", [])

def create_instance_with_retry(session, package, retries=3):
    pid = package["id"]
    cpu = package["cpu_max"]
    memory = package["memory_max"]
    disk = package["disk_max"]
    pname = package["name"]

    for attempt in range(1, retries + 1):
        name = random_instance_name()
        logger.info(f"[PKG {pid}] 第 {attempt}/{retries} 次尝试 | name={name}")

        payload = {
            "name": name,
            "packageId": pid,
            "image": "images:alpine/3.20/cloud",
            "cpu": cpu,
            "memory": memory,
            "disk": disk,
            "sshKeyId": SSH_KEY_ID[username]
        }

        r = session.post(
            f"{BASE_URL}/api/instances",
            json=payload,
            timeout=20
        )

        # 成功
        if r.status_code in (200, 201):
            logger.info(f"✅ 创建成功 | {name}")
            tg_notify(
                f"🎉 <b>Incudal 创建成功</b>\n"
                f"📦 套餐：{pname}\n"
                f"🆔 packageId：{pid}\n"
                f"🖥 name：{name}"
            )
            return True

        # 可重试失败
        if r.status_code == 503:
            try:
                data = r.json()
                if data.get("code") == "HOST_RESOURCES_INSUFFICIENT":
                    logger.warning(f"[PKG {pid}] 资源不足，换 name 重试")
                    time.sleep(1)
                    continue
            except Exception:
                pass

        # 不可重试
        logger.error(f"[PKG {pid}] 不可重试错误 {r.status_code}: {r.text}")
        tg_notify(
            f"❌ <b>Incudal 创建失败</b>\n"
            f"📦 套餐：{pname}\n"
            f"🆔 packageId：{pid}\n"
            f"📄 HTTP：{r.status_code}"
        )
        return False

    logger.error(f"[PKG {pid}] 达到最大重试次数")
    return False

# ==================== 主流程 ====================

def main():
    session = build_session()
    packages = get_packages(session)

    logger.info(f"获取到 {len(packages)} 个 package")

    for pkg in packages:
        if "美国" in pkg['name'] :
            logger.info(f"➡️ 尝试 packageId={pkg['id']} ({pkg['name']})")
            if create_instance_with_retry(session, pkg, retries=3):
                logger.info("🎉 脚本结束（已成功创建实例）")
                
        else:
            logger.info(f"🚫 跳过 packageId={pkg['id']} ({pkg['name']})")
    
            

    logger.error("🚫 所有 package 均创建失败")
    current_hour = time.localtime().tm_hour

    if current_hour % 6 == 0:
        tg_notify("🚫 <b>Incudal</b>\n所有 package 均创建失败")

# ==================== 入口 ====================

if __name__ == "__main__":
    main()
