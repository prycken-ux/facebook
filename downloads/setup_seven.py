"""Merge the user's seven account mappings without resetting local state."""
import copy
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

import fb_upload as upload

ROOT = Path(__file__).resolve().parent


def load_mappings(path):
    rows = upload.read_json(path, {}).get("accounts", [])
    if not isinstance(rows, list) or not rows:
        raise ValueError("请先创建 accounts_to_add.json，填写账号与目标的对应关系。")
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or not re.fullmatch(r"fb[0-9]{2}", row.get("account", "")):
            raise ValueError("账号编号应为 fb01 这样的格式。")
        if row["account"] in seen:
            raise ValueError("同一账号在本次导入中重复出现：" + row["account"])
        seen.add(row["account"])
        if row.get("type") not in {"page", "personal"} or not row.get("name", "").strip():
            raise ValueError("每个账号必须填写 type（page 或 personal）及 name。")
        upload.target_key(row.get("url", ""))
    return rows


def merged_config(existing, mappings):
    result = copy.deepcopy(existing)
    targets = result.setdefault("targets", [])
    for mapping in mappings:
        if mapping["type"] != "page":
            continue
        current = [row for row in targets if row.get("account") == mapping["account"] and row.get("target") == "page01"]
        if len(current) > 1:
            raise ValueError(mapping["account"] + " 有重复的 page01 配置，请先整理。")
        if current:
            row = current[0]
            same_target = (row.get("type") == "page" and row.get("name") == mapping["name"]
                           and upload.target_key(row.get("url", "")) == upload.target_key(mapping["url"]))
            if not same_target:
                row["enabled"] = False
                row.pop("prepared_at", None)
        else:
            row = {"account": mapping["account"], "target": "page01", "enabled": False,
                   "ai_label": True, "excluded_files": []}
            targets.append(row)
        row.update({key: mapping[key] for key in ("type", "name", "url")})
        upload.validate_entry(row)
    return result


def apply(mappings):
    config_path = ROOT / "upload_config.json"
    registry_path = ROOT / "account_registry.json"
    config = merged_config(upload.read_json(config_path, {"targets": []}), mappings)
    registry = upload.read_json(registry_path, {"accounts": []})
    rows = {row["account"]: row for row in registry.get("accounts", [])}
    personal_ids = {row["account"] for row in mappings if row["type"] == "personal"}
    # If an older configuration assigned a Page task to an account now mapped to
    # personal posting, retain that entry but stop it until the user reconciles it.
    for row in config["targets"]:
        if row.get("account") in personal_ids:
            row["enabled"] = False
            row.pop("prepared_at", None)
    for mapping in mappings:
        target = "page01" if mapping["type"] == "page" else "personal"
        folder = ROOT / "videos" / mapping["account"] / target
        for name in ("inbox", "completed", "failed"):
            (folder / name).mkdir(parents=True, exist_ok=True)
        item = dict(rows.get(mapping["account"], {}))
        item.update(mapping)
        item.update({"target": target, "profile": "profiles/" + mapping["account"],
                     "inbox": "videos/" + mapping["account"] + "/" + target + "/inbox",
                     "workflow": "page_flow_configured" if mapping["type"] == "page" else "pending_personal_recording"})
        rows[mapping["account"]] = item
    registry["accounts"] = list(rows.values())
    backup = ROOT / "backups" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup.mkdir(parents=True, exist_ok=False)
    for path in (config_path, registry_path):
        if path.exists():
            shutil.copy2(path, backup / path.name)
    upload.save_json(config_path, config)
    upload.save_json(registry_path, registry)
    text = ["账号对应表（不包含密码或 Cookie）", "公共主页已登记；新增目标尚未启用发布。个人主页仍待录制验证。", ""]
    for mapping in mappings:
        item = rows[mapping["account"]]
        kind = "公共主页" if mapping["type"] == "page" else "个人主页（待录制）"
        text.extend([mapping["account"] + " | " + kind + " | " + mapping["name"],
                     mapping["url"], str(ROOT / item["inbox"]), ""])
        print(mapping["account"], kind, mapping["name"])
        if not (ROOT / "profiles" / mapping["account"]).is_dir():
            print("注意：尚未发现该账号的浏览器资料，需要先登录。")
    (ROOT / "账号对应表.txt").write_text("\n".join(text), encoding="utf-8-sig")
    print("配置完成。旧配置备份：", backup)
    print("未上传或发布视频；profiles、logs/publish_state.json 和已有视频保持原样。")
    print("先为公共主页准备视频，再执行 batch_upload.py prepare --accounts=fb01,fb02,fb05,fb06")


def main():
    mappings = load_mappings(ROOT / "accounts_to_add.json")
    logs = ROOT / "logs"
    logs.mkdir(exist_ok=True)
    acquired = []
    try:
        for name in ("batch.lock", "upload.lock"):
            path = logs / name
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                raise RuntimeError("仍有上传任务或遗留锁文件，请先核对：" + str(path))
            acquired.append(path)
            with os.fdopen(fd, "w") as file:
                file.write(str(os.getpid()))
        apply(mappings)
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
