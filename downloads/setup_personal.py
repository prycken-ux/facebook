"""Enable the recorded personal workflow using the user's existing local registry."""
import copy
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

import fb_upload as upload

ROOT = Path(__file__).resolve().parent


def merge(existing, registry):
    result = copy.deepcopy(existing)
    entries = result.setdefault("targets", [])
    personal = [row for row in registry.get("accounts", []) if row.get("type") == "personal"]
    if not personal:
        raise ValueError("account_registry.json 中没有个人主页，请先登记账号对应关系。")
    seen = set()
    for mapping in personal:
        account = mapping["account"]
        if account in seen:
            raise ValueError("个人账号重复登记：" + account)
        seen.add(account)
        matches = [row for row in entries if row.get("account") == account]
        if len(matches) > 1 or any(row.get("type") != "personal" or row.get("target") != "personal" for row in matches):
            raise ValueError(account + " 仍有其他目标配置，请先核对，未覆盖原配置。")
        if matches:
            row = matches[0]
            same = (row.get("name") == mapping["name"] and
                    upload.target_key(row["url"]) == upload.target_key(mapping["url"]) and
                    row.get("workflow") == "personal_recording_v1")
            if not same:
                row["enabled"] = False
                row.pop("prepared_at", None)
        else:
            row = {"account": account, "target": "personal", "enabled": False,
                   "ai_label": True, "excluded_files": []}
            entries.append(row)
        row.update({"type": "personal", "name": mapping["name"], "url": mapping["url"],
                    "workflow": "personal_recording_v1"})
        upload.validate_entry(row)
    return result, personal


def apply():
    config_path = ROOT / "upload_config.json"
    registry_path = ROOT / "account_registry.json"
    registry = upload.read_json(registry_path, {"accounts": []})
    config, personal = merge(upload.read_json(config_path, {"targets": []}), registry)
    for row in personal:
        if not (ROOT / "profiles" / row["account"]).is_dir():
            raise ValueError("没有该账号的登录资料：" + row["account"])
    backup = ROOT / "backups" / ("personal-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
    backup.mkdir(parents=True, exist_ok=False)
    for path in (config_path, registry_path):
        if path.exists():
            shutil.copy2(path, backup / path.name)
    for row in personal:
        row.update({"workflow": "personal_recording_v1", "target": "personal",
                    "inbox": "videos/" + row["account"] + "/personal/inbox"})
        folder = ROOT / "videos" / row["account"] / "personal"
        for name in ("inbox", "completed", "failed"):
            (folder / name).mkdir(parents=True, exist_ok=True)
        print(row["account"], row["name"], row["url"])
        print("待发布文件夹：", folder / "inbox")
    upload.save_json(config_path, config)
    upload.save_json(registry_path, registry)
    print("个人主页流程登记完成；新增目标尚未启用发布。旧配置备份：", backup)
    print("没有上传或发布；公共主页配置、登录资料、发布记录和已有视频保持原样。")


def main():
    logs = ROOT / "logs"
    logs.mkdir(exist_ok=True)
    acquired = []
    try:
        for name in ("batch.lock", "upload.lock"):
            path = logs / name
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                raise RuntimeError("仍有任务或遗留锁，请先核对：" + str(path)) from None
            acquired.append(path)
            with os.fdopen(fd, "w") as handle:
                handle.write(str(os.getpid()))
        apply()
        return 0
    finally:
        for path in reversed(acquired):
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        raise SystemExit(main())
    except Exception as error:
        print("STOP：", error)
        raise SystemExit(1)
