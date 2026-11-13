import sys
from pathlib import Path

def normalize_model(model):
    """検出された機種名を画角設定のキーへ変換"""
    s = str(model).upper().replace(" ", "").replace("-", "")

    if "S30PRO" in s:
        return "Seestar S30 Pro"
    if "S50PRO" in s:
        return "Seestar S50 Pro"
    return None

def discover_seestars():
    from seestarpy import connection
    import sys
    from pathlib import Path
    from seestarpy import auth

    if getattr(sys, "frozen", False):
        base_dir = Path(sys._MEIPASS)
    else:
        base_dir = Path(__file__).resolve().parent

    auth.set_key_path(str(base_dir / "seestar.pem"))
    print(base_dir / "seestar.pem")
    connection.discover()
    found = []

    for sn, info in connection.DISCOVERED.items():
        if not isinstance(info, dict):
            continue

        ip = info.get("ip")
        model = info.get("model", "")
        if not ip:
            continue

        label = f"{model} / {ip} / {sn}"
        found.append((label, ip, str(model)))

    return found

def transfer_plan(ip, data):
    from seestarpy import raw, connection, plan

    print(f"接続先: {ip}")

    response = raw.test_connection(ips=ip)
    if not isinstance(response, dict) or response.get("code") != 0:
        raise RuntimeError(f"Seestar接続失敗: {response}")

    print("Seestar接続確認 OK")

    if not data.get("list"):
        raise ValueError("PLANに撮影対象がありません")

    for target in data["list"]:
        ra, dec = target["target_ra_dec"]
        if not (0 <= ra < 24 and -90 <= dec <= 90):
            raise ValueError(f"座標が不正です: {target}")

    connection.DEFAULT_IP = ip
    target_ip = connection.current_ip()
    if target_ip != ip:
        raise RuntimeError(f"送信先IPが一致しません: {target_ip}")

    print(f"PLAN転送中... ({len(data['list'])}パネル)")
    result = plan.set_view_plan(data)
    print("PLAN転送応答:", result)

    if not isinstance(result, dict) or result.get("code") != 0:
        raise RuntimeError(f"PLAN転送失敗: {result}")

    return result
