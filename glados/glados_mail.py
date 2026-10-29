#!/usr/bin/env python3
# glados_mail.py
"""
GLaDOS 验证码收取模块（可被任意 Python 项目 import）。

用法：
    from glados_mail import fetch_glados_code

    code = fetch_glados_code("a@126.com", "授权码")
    print(code)   # 6 位字符串，或 None

    # 也可手动指定服务器
    code = fetch_glados_code("x@corp.com", "pwd", host="mail.corp.com")
"""
from __future__ import annotations

import email
import imaplib
import re
import time
import html as htmllib
from email.header import decode_header
from typing import Optional

try:
    from imap_tools import MailBox
except ImportError:  # imap-tools 非必需（网易分支只用标准库）
    MailBox = None


# ============ IMAP 主机自动解析 ============
_IMAP_HOST_MAP = {
    # 腾讯
    "qq.com": "imap.qq.com",
    "foxmail.com": "imap.qq.com",
    # 网易
    "163.com": "imap.163.com",
    "126.com": "imap.126.com",
    "yeah.net": "imap.yeah.net",
    # Google
    "gmail.com": "imap.gmail.com",
    "googlemail.com": "imap.gmail.com",
    # 常见其他
    "outlook.com": "outlook.office365.com",
    "hotmail.com": "outlook.office365.com",
    "live.com": "outlook.office365.com",
    "yahoo.com": "imap.mail.yahoo.com",
    "icloud.com": "imap.mail.me.com",
    "sina.com": "imap.sina.com",
    "sohu.com": "imap.sohu.com",
    "aliyun.com": "imap.aliyun.com",
}


def resolve_imap_host(user: str) -> str:
    """根据邮箱地址推断 IMAP 服务器；未知域名回退到 imap.<domain>。"""
    if not user or "@" not in user:
        raise ValueError(f"无效的邮箱地址: {user!r}")
    domain = user.rsplit("@", 1)[1].strip().lower()

    if domain in _IMAP_HOST_MAP:
        return _IMAP_HOST_MAP[domain]

    for suffix, host in _IMAP_HOST_MAP.items():
        if domain.endswith("." + suffix) or domain == suffix:
            return host

    return f"imap.{domain}"


def _is_netease(host: str) -> bool:
    return any(x in host.lower() for x in ("163.com", "126.com", "yeah.net"))


def _is_gmail(host: str) -> bool:
    return "gmail" in host.lower()


# ============ 验证码提取（纯函数） ============
def strip_html(raw_html: str) -> str:
    if not raw_html:
        return ""
    plain = re.sub(r"<[^>]+>", " ", raw_html)
    plain = htmllib.unescape(plain)
    return re.sub(r"[ \t]+", " ", plain)


def extract_glados_code(text: str, html: str) -> Optional[str]:
    """从纯文本/HTML 中提取 GLaDOS 6 位验证码。"""
    m = re.search(r"verification\s+code\s+is\s*[:\s]*\n*\s*(\d{6})", text or "", re.I)
    if m:
        return m.group(1)
    for line in (text or "").splitlines():
        if re.fullmatch(r"\d{6}", line.strip()):
            return line.strip()
    plain = strip_html(html)
    m = re.search(r"verification\s+code\s+is\s*[:\s]*(\d{6})", plain, re.I)
    if m:
        return m.group(1)
    m = re.search(r"\b(\d{6})\b", plain)
    if m:
        return m.group(1)
    return None


def is_glados_mail(from_: str, subject: str, text: str, html: str) -> bool:
    blob = " ".join([from_ or "", subject or "", text or "", html or ""]).lower()
    if "glados" not in blob:
        return False
    if ("authentication code" in (subject or "").lower()
            or "verification code" in blob
            or "authentication code" in blob):
        return True
    return False


# ============ 网易 126/163：imaplib + ID ============
imaplib.Commands["ID"] = ("AUTH",)


def _decode_mime_header(value: str) -> str:
    if not value:
        return ""
    out = []
    for data, enc in decode_header(value):
        if isinstance(data, bytes):
            out.append(data.decode(enc or "utf-8", errors="ignore"))
        else:
            out.append(data)
    return "".join(out)


def _extract_body(msg) -> tuple[str, str]:
    text_parts, html_parts = [], []
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition") or "")
            if "attachment" in disp.lower():
                continue
            if ctype not in ("text/plain", "text/html"):
                continue
            try:
                payload = part.get_payload(decode=True)
                if payload is None:
                    continue
                charset = part.get_content_charset() or "utf-8"
                decoded = payload.decode(charset, errors="ignore")
                (text_parts if ctype == "text/plain" else html_parts).append(decoded)
            except Exception:
                continue
    else:
        try:
            payload = msg.get_payload(decode=True)
            if payload is not None:
                charset = msg.get_content_charset() or "utf-8"
                text_parts.append(payload.decode(charset, errors="ignore"))
        except Exception:
            pass
    return "\n".join(text_parts), "\n".join(html_parts)


def _scan_netease(user: str, password: str, host: str,
                  fetch_limit: int, verbose: bool) -> Optional[str]:
    def log(*a):
        if verbose:
            print(*a)

    mail = imaplib.IMAP4_SSL(host, 993)
    try:
        mail.login(user, password)

        args = ("name", "GladosMailLib", "version", "1.0",
                "vendor", "myclient", "support-email", user)
        try:
            mail._simple_command("ID", '("' + '" "'.join(args) + '")')
        except Exception as e:
            log(f"[WARN] 发送 ID 命令失败: {e}")

        typ, dat = mail.select('"INBOX"', readonly=True)
        if typ != "OK":
            log(f"[WARN] 选择 INBOX 失败: {dat}")
            return None

        typ, data = mail.search(None, "ALL")
        if typ != "OK" or not data or not data[0]:
            log("[INFO] INBOX 无邮件")
            return None

        ids = data[0].split()[-fetch_limit:]
        log(f"[INFO] INBOX 取最近 {len(ids)} 封")

        for num in reversed(ids):
            typ, msg_data = mail.fetch(num, "(RFC822)")
            if typ != "OK" or not msg_data or not msg_data[0]:
                continue
            msg = email.message_from_bytes(msg_data[0][1])

            subject = _decode_mime_header(msg.get("Subject", ""))
            from_ = _decode_mime_header(msg.get("From", ""))
            text, html = _extract_body(msg)
            log(f"[DEBUG] from={from_!r} subject={subject!r} "
                f"text_len={len(text)} html_len={len(html)}")

            if not is_glados_mail(from_, subject, text, html):
                continue
            code = extract_glados_code(text, html)
            if code:
                return code
        return None
    finally:
        try:
            mail.logout()
        except Exception:
            pass


# ============ Gmail / QQ：imap-tools ============
def _scan_imap_tools(user: str, password: str, host: str,
                     fetch_limit: int, verbose: bool) -> Optional[str]:
    if MailBox is None:
        raise RuntimeError("未安装 imap-tools，请先 pip install imap-tools")

    def log(*a):
        if verbose:
            print(*a)

    folders = (["[Gmail]/All Mail", "[Gmail]/所有邮件", "INBOX"]
               if _is_gmail(host) else ["INBOX"])

    with MailBox(host).login(user, password) as mailbox:
        for folder in folders:
            try:
                mailbox.folder.set(folder)
            except Exception as e:
                log(f"[WARN] 切换文件夹 {folder!r} 失败: {e}")
                continue

            try:
                msgs = list(mailbox.fetch("ALL", reverse=True, limit=fetch_limit))
            except Exception as e:
                log(f"[WARN] 拉取 {folder!r} 失败: {e}")
                continue

            log(f"[INFO] 文件夹 {folder!r} 拉到 {len(msgs)} 封")
            for msg in msgs:
                from_ = msg.from_ or ""
                subject = msg.subject or ""
                text = msg.text or ""
                html = msg.html or ""
                log(f"[DEBUG] from={from_!r} subject={subject!r} "
                    f"text_len={len(text)} html_len={len(html)}")

                if not is_glados_mail(from_, subject, text, html):
                    continue
                code = extract_glados_code(text, html)
                if code:
                    return code
    return None


# ============ 公开 API ============
def scan_once(user: str, password: str, host: Optional[str] = None,
              fetch_limit: int = 20, verbose: bool = False) -> Optional[str]:
    """扫描一次，返回验证码或 None。host 省略时按邮箱域名自动推断。"""
    if not host:
        host = resolve_imap_host(user)
    if _is_netease(host):
        return _scan_netease(user, password, host, fetch_limit, verbose)
    return _scan_imap_tools(user, password, host, fetch_limit, verbose)


def fetch_glados_code(
    user: str,
    password: str,
    host: Optional[str] = None,
    *,
    max_wait: int = 120,
    poll_interval: int = 10,
    fetch_limit: int = 20,
    verbose: bool = False,
) -> Optional[str]:
    """
    轮询收取 GLaDOS 验证码。

    :param user: 邮箱完整地址
    :param password: 授权码 / 应用专用密码
    :param host: IMAP 服务器；省略则按邮箱域名自动推断
    :param max_wait: 最长等待秒数（0 表示只扫一次）
    :param poll_interval: 轮询间隔秒数
    :param fetch_limit: 每次取最近多少封邮件
    :param verbose: 是否打印调试日志
    :return: 6 位验证码字符串，超时返回 None
    """
    if not host:
        host = resolve_imap_host(user)
    if verbose:
        print(f"[INFO] 使用 IMAP 主机: {host}")

    deadline = time.time() + max_wait
    attempt = 0
    while True:
        attempt += 1
        if verbose:
            print(f"[INFO] 第 {attempt} 次扫描...")
        try:
            code = scan_once(user, password, host, fetch_limit, verbose)
        except Exception as e:
            if verbose:
                print(f"[ERROR] 扫描异常: {e}")
            code = None

        if code:
            if verbose:
                print(f"✅ 找到验证码: {code}")
            return code

        if time.time() >= deadline:
            if verbose:
                print("❌ 超时未找到验证码")
            return None
        time.sleep(poll_interval)
