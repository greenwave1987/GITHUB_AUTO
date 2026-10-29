import os
import sys
import time
from glados_mail import fetch_glados_code

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
from engine.main import ConfigReader


def mask_email(email: str) -> str:
    """对邮箱做脱敏处理，例如 abc***@gmail.com"""
    if not email or "@" not in email:
        return email or ""
    name, domain = email.split("@", 1)
    if len(name) <= 3:
        return name[0] + "***@" + domain
    return name[:3] + "***@" + domain


def run():
    env_name = os.environ.get("ENV_NAME", "default")
    print(f"🚀 {env_name} 自动化任务启动")

    config = ConfigReader()
    email_infos = config.get_value("EMAIL_INFO") or []

    host = os.environ.get("IMAP_HOST") or None
    max_wait = int(os.environ.get("MAX_WAIT_SECONDS", "120"))
    poll_interval = int(os.environ.get("POLL_INTERVAL", "10"))
    fetch_limit = int(os.environ.get("FETCH_LIMIT", "20"))

    for index, email_info in enumerate(email_infos, start=1):
        username = email_info.get("username")
        password = email_info.get("password")

        print(f"第 {index} 个账号：{mask_email(username)}")

        if not username or not password:
            print("  不存在用户名或密码，无法自动获取验证码！")
            continue

        code = fetch_glados_code(
            username,
            password,
            host,
            max_wait=max_wait,
            poll_interval=poll_interval,
            fetch_limit=fetch_limit,
            verbose=True,
        )

        if not code:
            print(f"  [{mask_email(username)}] 未能获取验证码，跳过")
        else:
            print(f"  获取到验证码 [{code}]！")
        print(f"等待 {10}s 后处理下一账号...")
        time.sleep(10)

if __name__ == "__main__":
    run()
