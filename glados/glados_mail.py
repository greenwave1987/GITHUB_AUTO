#!/usr/bin/env python3
# glados_mail.py
"""
GLaDOS 验证码收取模块（可被任意 Python 项目 import）。

用法：
    from glados_mail import fetch_glados_code

    # 默认：只看今日邮件，最多尝试 4 次，每次间隔 60 秒
    code = fetch_glados_code("a@126.com", "授权码")
    print(code)   # 5~6 位字符串，或 None

    # 也可手动指定服务器 / 关闭今日过滤 / 调整轮询
    code = fetch_glados_code(
        "x@corp.com", "pwd",
        host="mail.corp.com",
        today_only=False,
        poll_interval=30, max_attempts=6,
    )
"""
from __future__ import annotations

import email
import imaplib
import re
import time
import html as htmllib
from email.header import decode_header
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
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


# ============ 验证码提取（纯函数，支持 5~6 位） ============
def strip_html(raw_html: str) -> str:
    if not raw_html:
        return ""
    plain = re.sub(r"<[^>]+>", " ", raw_html)
    plain = htmllib.unescape(plain)
    return re.sub(r"[ \t]+", " ", plain)


def extract_glados_code(text: str, html: str) -> Optional[str]:
    """从纯文本/HTML 中提取 GLaDOS 5~6 位验证码。"""
    # 1) 关键词后允许换行/空白，匹配 5~6 位数字
    m = re.search(r"verification\s+code\s+is\s*[:\s]*\n*\s*(\d{5,6})", text or "", re.I)
    if m:
        return m.group(1)
    # 2) 独占一行的 5~6 位数字
    for line in (text or "").splitlines():
        s = line.strip()
        if re.fullmatch(r"\d{5,6}", s):
            return s
    # 3) HTML 剥标签后再匹配
    plain = strip_html(html)
    m = re.search(r"verification\s+code\s+is\s*[:\s]*(\d{5,6})", plain, re.I)
    if m:
        return m.group(1)
    # 4) 兜底：任意独立的 5~6 位数字
    m = re.search(r"\b(\d{5,6})\b", plain)
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


# ============ 邮件时间解析（排序用） ============
_EPOCH = datetime.fromtimestamp(0, tz=timezone.utc)


def _mail_datetime(msg) -> datetime:
    """解析邮件 Date 头；失败返回 epoch。"""
    try:
        raw = msg.get("Date")
        if not raw:
            return _EPOCH
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return _EPOCH


def _imap_tools_msg_datetime(msg) -> datetime:
    """imap-tools MailMessage.date -> datetime；失败返回 epoch。"""
    try:
        dt = msg.date
        if dt is None:
            return _EPOCH
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return _EPOCH


# ★ 新增：判断某封邮件是否属于"今日"（按本地时区）
def _is_today(dt: datetime) -> bool:
    if dt is None:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    now_local = datetime.now().astimezone()
    today_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    # 统一到本地时区比较
    return dt.astimezone(now_local.tzinfo) >= today_start_local


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
                  fetch_limit: int, verbose: bool,
                  today_only: bool = True) -> Optional[str]:
    def log(*a):
        if verbose:
            print(*a)

    mail = imaplib.IMAP4_SSL(host, 993)
    try:
        mail.login(user, password)

        # 关键：发送 IMAP ID，规避 "Unsafe Login"
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

        # ★ 关键：用 SINCE 只搜今日邮件（IMAP 规范要求 %d-%b-%Y 格式）
        if today_only:
            since = datetime.now().strftime("%d-%b-%Y")
            typ, data = mail.search(None, f"(SINCE {since})")
        else:
            typ, data = mail.search(None, "ALL")

        if typ != "OK" or not data or not data[0]:
            log("[INFO] 今日 INBOX 无邮件" if today_only else "[INFO] INBOX 无邮件")
            return None

        ids = data[0].split()[-fetch_limit:]

        # 先拉取，再按 Date 头倒序
        parsed = []
        for num in ids:
            typ, msg_data = mail.fetch(num, "(RFC822)")
            if typ != "OK" or not msg_data or not msg_data[0]:
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            dt = _mail_datetime(msg)
            # ★ 二次过滤：SINCE 只到"天"粒度，跨时区可能带入昨天，再判一次
            if today_only and not _is_today(dt):
                continue
            parsed.append((dt, msg))

        parsed.sort(key=lambda x: x[0], reverse=True)
        log(f"[INFO] {'今日' if today_only else 'INBOX'} 取 {len(parsed)} 封，已按时间倒序")

        for dt, msg in parsed:
            subject = _decode_mime_header(msg.get("Subject", ""))
            from_ = _decode_mime_header(msg.get("From", ""))
            text, html = _extract_body(msg)
            log(f"[DEBUG] date={dt.isoformat()} from={from_!r} "
                f"subject={subject!r} text_len={len(text)} html_len={len(html)}")

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
                     fetch_limit: int, verbose: bool,
                     today_only: bool = True) -> Optional[str]:
    if MailBox is None:
        raise RuntimeError("未安装 imap-tools，请先 pip install imap-tools")

    def log(*a):
        if verbose:
            print(*a)

    folders = (["[Gmail]/All Mail", "[Gmail]/所有邮件", "INBOX"]
               if _is_gmail(host) else ["INBOX"])

    # ★ 今日的 IMAP 日期串
    since_str = datetime.now().strftime("%d-%b-%Y") if today_only else None

    with MailBox(host).login(user, password) as mailbox:
        for folder in folders:
            try:
                mailbox.folder.set(folder)
            except Exception as e:
                log(f"[WARN] 切换文件夹 {folder!r} 失败: {e}")
                continue

            try:
                criteria = f"(SINCE {since_str})" if since_str else "ALL"
                msgs = list(mailbox.fetch(criteria, reverse=True, limit=fetch_limit))
            except Exception as e:
                log(f"[WARN] 拉取 {folder!r} 失败: {e}")
                continue

            # ★ 二次按邮件时间过滤今日 + 倒序
            if today_only:
                msgs = [m for m in msgs if _is_today(_imap_tools_msg_datetime(m))]
            msgs.sort(key=_imap_tools_msg_datetime, reverse=True)
            log(f"[INFO] 文件夹 {folder!r} {'今日' if today_only else ''}拉到 "
                f"{len(msgs)} 封，已按时间倒序")

            for msg in msgs:
                from_ = msg.from_ or ""
                subject = msg.subject or ""
                text = msg.text or ""
                html = msg.html or ""
                log(f"[DEBUG] date={_imap_tools_msg_datetime(msg).isoformat()} "
                    f"from={from_!r} subject={subject!r} "
                    f"text_len={len(text)} html_len={len(html)}")

                if not is_glados_mail(from_, subject, text, html):
                    continue
                code = extract_glados_code(text, html)
                if code:
                    return code
    return None


# ============ 公开 API ============
def scan_once(user: str, password: str, host: Optional[str] = None,
              fetch_limit: int = 20, verbose: bool = False,
              today_only: bool = True) -> Optional[str]:
    """扫描一次，返回验证码或 None。host 省略时按邮箱域名自动推断。"""
    if not host:
        host = resolve_imap_host(user)
    if _is_netease(host):
        return _scan_netease(user, password, host, fetch_limit, verbose, today_only)
    return _scan_imap_tools(user, password, host, fetch_limit, verbose, today_only)


def fetch_glados_code(
    user: str,
    password: str,
    host: Optional[str] = None,
    *,
    poll_interval: int = 60,     # ★ 每次扫描间隔（秒）
    max_attempts: int = 4,       # ★ 最多扫描次数
    fetch_limit: int = 20,
    verbose: bool = False,
    today_only: bool = True,     # ★ 只匹配今日邮件
    max_wait: Optional[int] = None,  # ★ 兼容旧参数；None 则用 poll_interval*max_attempts
    first_scan_immediate: bool = False,  # ★ 首次是否立即扫（False=先等 60s）
) -> Optional[str]:
    """
    轮询收取 GLaDOS 验证码（只看今日邮件，5~6 位）。

    语义（默认 first_scan_immediate=False）：
        - 每次扫描前先等待 poll_interval 秒
        - 最多尝试 max_attempts 次（默认 4 次）
        - 全部失败返回 None

    若 first_scan_immediate=True：
        - 第 1 次立刻扫；之后每次间隔 poll_interval；共 max_attempts 次

    :param user: 邮箱完整地址
    :param password: 授权码 / 应用专用密码
    :param host: IMAP 服务器；省略则按邮箱域名自动推断
    :param poll_interval: 轮询间隔秒数（默认 60）
    :param max_attempts: 最多扫描次数（默认 4）
    :param fetch_limit: 每次取最近多少封邮件
    :param verbose: 是否打印调试日志
    :param today_only: 只匹配今天收到的邮件（默认 True）
    :param max_wait: 兼容旧参数；若给出则按总超时秒数截断
    :param first_scan_immediate: 首次是否立即扫描（默认 False）
    :return: 5~6 位验证码字符串，超时/全部失败返回 None
    """
    if not host:
        host = resolve_imap_host(user)
    if verbose:
        print(f"[INFO] IMAP 主机: {host}, today_only={today_only}, "
              f"max_attempts={max_attempts}, poll_interval={poll_interval}s, "
              f"first_scan_immediate={first_scan_immediate}")

    deadline = None
    if max_wait is not None and max_wait > 0:
        deadline = time.time() + max_wait

    for attempt in range(1, max_attempts + 1):
        # ★ 首次是否等待
        if attempt > 1 or not first_scan_immediate:
            if verbose:
                print(f"[INFO] 等待 {poll_interval}s 后第 {attempt} 次扫描...")
            time.sleep(poll_interval)

        if verbose:
            print(f"[INFO] 第 {attempt}/{max_attempts} 次扫描...")

        try:
            code = scan_once(
                user, password, host, fetch_limit, verbose,
                today_only=today_only,
            )
        except Exception as e:
            if verbose:
                print(f"[ERROR] 扫描异常: {e}")
            code = None

        if code:
            if verbose:
                print(f"✅ 找到验证码: {code}")
            return code

        if deadline is not None and time.time() >= deadline:
            if verbose:
                print("❌ 达到 max_wait 超时，停止")
            return None

    if verbose:
        print(f"❌ {max_attempts} 次扫描均未找到验证码，返回 None")
    return None
