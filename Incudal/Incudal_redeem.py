import os
import json
import requests

BASE_URL = "https://incudal.com"
TIMEOUT = 15
RESULT_FILE = os.path.join(os.getcwd(), "result.txt")

def append_line(line):
    with open(RESULT_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line, flush=True)

def build_session():
    raw = os.environ.get("USER_SESSION")
    if not raw:
        raise RuntimeError("❌ USER_SESSION 未设置")
    data = json.loads(raw)
    s = requests.Session()
    s.headers.update({
        "authorization": data["auth_token"],
        "user-agent": "Mozilla/5.0",
        "accept": "application/json"
    })
    for c in data.get("cookies", []):
        s.cookies.set(c["name"], c["value"], domain=c.get("domain"))
    return s

def safe_json(r):
    try:
        return r.json()
    except:
        return {}

def decode_redeem(code_type, code_value):
    type_map = {
        "c": {"name": "CPU", "unit": "%"},
        "r": {"name": "内存", "unit": "MB"},
        "d": {"name": "硬盘", "unit": "MB"},
        "t": {"name": "流量", "unit": "GB"}
    }

    info = type_map.get(code_type)
    if not info:
        return "未知资源"

    return f"{info['name']} +{code_value}{info['unit']}"

def get_instances(session):
    try:
        r = session.get(f"{BASE_URL}/api/instances", timeout=TIMEOUT)
        r.raise_for_status()
        return r.json().get("instances", [])
    except Exception as e:
        append_line(f"❌ 获取实例失败: {e}")
        return []

def redeem(session, code, instance_id):
    try:
        append_line(f"🚀 开始兑换实例 {instance_id}：")
        r = session.post(
            f"{BASE_URL}/api/checkin/redeem",
            json={"redeemCode": code, "instanceId": instance_id},
            timeout=TIMEOUT
        )
        data = safe_json(r)
        print(data)
        code_data = data.get("todayCode") if isinstance(data.get("todayCode"), dict) else data

        if r.status_code == 200 and code_data and "codeType" in code_data:
            result = f"✅ {instance_id}: {decode_redeem(code_data['codeType'], code_data['codeValue'])}"
            append_line(result)
            return result
        result = f"❌ {instance_id}: {data['error']}"
        append_line(result)
        return result
    except Exception as e:
        result = f"❌ {instance_id}: 异常 {e}"
        append_line(result)
        return result

def main():
    # 清空 result.txt
    open(RESULT_FILE, "w", encoding="utf-8").close()

    try:
        session = build_session()
        codes = [x.strip() for x in os.environ.get("REDEEM_TEXT", "").splitlines() if x.strip()]
        if not codes:
            append_line("❌ 未获取到兑换码，退出")
            return

        instances = get_instances(session)
        if not instances:
            append_line("❌ 没有实例可兑换")
            return

        for code in codes:
            append_line(f"🎟 兑换码 {code} 开始")
            for ins in instances:
                redeem(session, code, ins["id"])

    except Exception as e:
        append_line(f"❌ 脚本异常: {e}")

    append_line("✅ 全部兑换完成")

if __name__ == "__main__":
    main()
