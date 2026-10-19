"""Reserve new local Chrome profiles and register additional posting targets.

No login secrets are read. Registration never enables or publishes a target.
"""
import argparse
import copy
import json
import os
import shutil
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import fb_upload as upload

ROOT = Path(__file__).resolve().parent
SLOTS = tuple("fb%02d" % number for number in range(8, 14))
MANIFEST = "new_accounts_pending.json"
SHORTCUT_FOLDER = "新增账号登录"
SCHEMA = "additional-fb-accounts-v1"


@contextmanager
def locked():
    logs = ROOT / "logs"
    logs.mkdir(exist_ok=True)
    owned = []
    token = str(os.getpid()).encode("ascii")
    try:
        for name in ("batch.lock", "upload.lock"):
            path = logs / name
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                raise RuntimeError("仍有上传任务或遗留锁，请先核对：" + str(path)) from None
            owned.append(path)
            with os.fdopen(fd, "wb") as handle:
                handle.write(token)
        yield
    finally:
        for path in reversed(owned):
            if path.exists() and path.read_bytes() == token:
                path.unlink()


def local_documents():
    config_path = ROOT / "upload_config.json"
    registry_path = ROOT / "account_registry.json"
    if not config_path.is_file() or not registry_path.is_file():
        raise ValueError("请把本工具放在原 E:\\FB-AutoUpload 安装目录，缺少配置或账号对应表。")
    config = upload.read_json(config_path, None)
    registry = upload.read_json(registry_path, None)
    for document, key in ((config, "targets"), (registry, "accounts")):
        if not isinstance(document, dict) or not isinstance(document.get(key), list):
            raise ValueError("原配置或账号对应表格式异常，未覆盖。")
        if any(not isinstance(row, dict) for row in document[key]):
            raise ValueError("原配置包含无效账号条目，未覆盖。")
    manifest = upload.read_json(ROOT / MANIFEST, {"schema": SCHEMA, "slots": {}})
    if (not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA
            or not isinstance(manifest.get("slots"), dict)):
        raise ValueError("新增账号登记文件格式异常，未覆盖。")
    for account, row in manifest["slots"].items():
        if account not in SLOTS or not isinstance(row, dict) or row.get("state") not in {"pending", "registered"}:
            raise ValueError("新增账号登记文件有未知条目，已停止。")
    return config, registry, manifest


def parse_accounts(value):
    accounts = value.split(",")
    if not accounts or len(set(accounts)) != len(accounts) or any(a not in SLOTS for a in accounts):
        raise ValueError("本次新增范围为 fb08～fb13，请使用不重复的逗号分隔编号。")
    return accounts


def reserve(accounts):
    config, registry, manifest = local_documents()
    existing = {row.get("account") for row in config["targets"] + registry["accounts"]}
    # Check every slot before making any changes. Existing unclaimed profiles
    # are never adopted, cleared, or silently reused.
    for account in accounts:
        if account in existing:
            raise ValueError(account + " 已在原配置中登记，未覆盖。")
        if account not in manifest["slots"]:
            for path in (ROOT / "profiles" / account, ROOT / "videos" / account,
                         ROOT / SHORTCUT_FOLDER / (account + " 登录.lnk")):
                if path.exists():
                    raise ValueError("存在未由本工具登记的账号资料，未覆盖：" + str(path))
        elif manifest["slots"][account]["state"] != "pending":
            raise ValueError(account + " 已完成登记，未重复创建。")
    for account in accounts:
        manifest["slots"].setdefault(account, {"state": "pending"})
    # Save ownership before mkdir, so an interrupted first run can resume.
    upload.save_json(ROOT / MANIFEST, manifest)
    for account in accounts:
        (ROOT / "profiles" / account).mkdir(parents=True, exist_ok=True)


def find_chrome():
    for base in (os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)"),
                 os.environ.get("LOCALAPPDATA")):
        if base:
            candidate = Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe"
            if candidate.is_file():
                return candidate
    found = shutil.which("chrome.exe")
    if found:
        return Path(found)
    raise ValueError("没有找到已安装的 Google Chrome，请先安装后重试。")


def shortcut_items(accounts, chrome):
    return [{"path": str(ROOT / SHORTCUT_FOLDER / (account + " 登录.lnk")),
             "chrome": str(chrome), "working": str(ROOT),
             "description": account + " 独立 Facebook 登录",
             "arguments": subprocess.list2cmdline([
                 "--user-data-dir=" + str(ROOT / "profiles" / account),
                 "--profile-directory=Default", "--no-first-run", "--no-default-browser-check",
                 "--new-window", "https://www.facebook.com/?locale=en_US"])} for account in accounts]


def write_shortcuts(items):
    # Data travels through stdin as JSON, never as interpolated PowerShell code.
    script = r"""
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$items = [Console]::In.ReadToEnd() | ConvertFrom-Json
$shell = New-Object -ComObject WScript.Shell
foreach ($item in $items) {
    $shortcut = $shell.CreateShortcut([string]$item.path)
    $shortcut.TargetPath = [string]$item.chrome
    $shortcut.Arguments = [string]$item.arguments
    $shortcut.WorkingDirectory = [string]$item.working
    $shortcut.Description = [string]$item.description
    $shortcut.Save()
}
"""
    subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                   input=json.dumps(items, ensure_ascii=False).encode("utf-8"), check=True,
                   timeout=60)


def prepare(accounts):
    if sys.platform != "win32":
        raise RuntimeError("登录入口需在安装上传程序的 Windows 电脑上创建。")
    chrome = find_chrome()
    with locked():
        reserve(accounts)
        folder = ROOT / SHORTCUT_FOLDER
        folder.mkdir(exist_ok=True)
        write_shortcuts(shortcut_items(accounts, chrome))
    os.startfile(str(folder))
    print("已创建独立登录入口：", ", ".join(accounts))
    print("请逐个双击快捷方式，在 Facebook 页面正常登录；无需登录 Google/Chrome 同步。")
    print("记下每个编号对应的主页名称、主页链接、个人主页或公共主页类型。")
    print("公共主页请切换到要发布的 Page；每个窗口检查完后关闭，再登录下一个。")
    print("这里只创建登录入口，账号尚未加入发布配置。")


def registration_plan(config, registry, manifest, mappings):
    config, registry, manifest = copy.deepcopy((config, registry, manifest))
    if not isinstance(mappings, dict) or not isinstance(mappings.get("accounts"), list) or not mappings["accounts"]:
        raise ValueError("对应表应包含非空 accounts 列表。")
    seen = set()
    for supplied in mappings["accounts"]:
        if not isinstance(supplied, dict) or set(supplied) != {"account", "type", "name", "url"}:
            raise ValueError("每项只填写 account、type、name、url，不要填写密码或 Cookie。")
        if any(not isinstance(supplied[k], str) for k in supplied):
            raise ValueError("账号对应表的四个字段必须为文字。")
        row = {k: v.strip() for k, v in supplied.items()}
        account = row["account"]
        if account not in SLOTS or account in seen:
            raise ValueError("只能登记不重复的 fb08～fb13 新账号。")
        seen.add(account)
        slot = manifest["slots"].get(account)
        if not slot or not (ROOT / "profiles" / account).is_dir():
            raise ValueError(account + " 尚未创建独立登录资料，请先运行 prepare。")
        row["target"] = "personal" if row["type"] == "personal" else "page01"
        if row["type"] == "personal":
            row["workflow"] = "personal_recording_v1"
        upload.validate_entry(row)
        identity = upload.target_key(row["url"])
        for other in config["targets"] + registry["accounts"]:
            if other.get("account") != account and upload.target_key(other.get("url", "")) == identity:
                raise ValueError(account + " 的目标主页已登记在其他账号，未重复添加。")
        current = [r for r in config["targets"] if r.get("account") == account]
        known = [r for r in registry["accounts"] if r.get("account") == account]
        if current or known:
            if (slot["state"] != "registered" or len(current) != 1 or len(known) != 1
                    or slot.get("mapping") != supplied):
                raise ValueError(account + " 与已有登记冲突，未覆盖。")
            if any(any(r.get(k) != row.get(k) for k in ("account", "type", "target", "name", "url"))
                   for r in current + known):
                raise ValueError(account + " 原配置已变化，请先核对。")
            continue  # Idempotence must preserve later prepare/enabled settings.
        row.update({"enabled": False, "ai_label": True, "excluded_files": []})
        config["targets"].append(row)
        item = {k: row[k] for k in ("account", "type", "target", "name", "url")}
        item.update({"profile": "profiles/" + account,
                     "inbox": "videos/" + account + "/" + row["target"] + "/inbox",
                     "workflow": "personal_recording_v1" if row["type"] == "personal" else "page_flow_configured"})
        registry["accounts"].append(item)
        slot.update({"state": "registered", "mapping": supplied})
    return config, registry, manifest


def register(path):
    mappings = upload.read_json(path, None)
    with locked():
        original = local_documents()
        planned = registration_plan(*original, mappings)
        if original != planned:
            backup = ROOT / "backups" / ("add-accounts-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
            backup.mkdir(parents=True, exist_ok=False)
            paths = [ROOT / "upload_config.json", ROOT / "account_registry.json", ROOT / MANIFEST]
            for file in paths:
                shutil.copy2(file, backup / file.name)
            for row in mappings["accounts"]:
                target = "personal" if row["type"].strip() == "personal" else "page01"
                for folder in ("inbox", "completed", "failed"):
                    (ROOT / "videos" / row["account"].strip() / target / folder).mkdir(parents=True, exist_ok=True)
            try:
                for file, document in zip(paths, planned):
                    upload.save_json(file, document)
            except Exception:
                # Restore all three byte-for-byte; retain backup for recovery.
                for file in paths:
                    shutil.copy2(backup / file.name, file)
                raise
            print("已备份原配置：", backup)
    print("账号已登记；新增目标保持未启用，需逐个检查身份并 prepare 后再启用。")
    print("未上传或发布视频；未设置定时任务，未修改已有发布记录。")


def main():
    parser = argparse.ArgumentParser(description="新增 fb08～fb13 独立 Facebook 登录与目标配置")
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--accounts", default=",".join(SLOTS))
    reg = sub.add_parser("register")
    reg.add_argument("--mapping", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(parse_accounts(args.accounts))
    else:
        register(args.mapping)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        raise SystemExit(main())
    except Exception as error:
        print("STOP：", error)
        raise SystemExit(1)
