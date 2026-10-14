"""Run configured local public Page tasks sequentially, with full preflight."""
import argparse
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import fb_upload as upload

ROOT = Path(__file__).resolve().parent


def select_targets(config, accounts, action, state):
    selected = []
    errors = []
    urls = set()
    for account in accounts:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", account):
            errors.append("账号编号无效：" + account)
            continue
        entries = [entry for entry in config.get("targets", []) if entry.get("account") == account]
        if not entries:
            errors.append(account + "：尚未配置目标主页")
            continue
        if not (ROOT / "profiles" / account).is_dir():
            errors.append(account + "：没有独立浏览器资料")
        for entry in entries:
            label = account + "/" + entry.get("target", "?")
            try:
                upload.validate_entry(entry)
                key = upload.target_key(entry["url"])
                if key in urls:
                    errors.append(label + "：同一个目标主页在本批次中重复配置")
                urls.add(key)
                if action in {"enable", "publish"} and not entry.get("prepared_at"):
                    errors.append(label + "：尚未完成 prepare 检查")
                if action == "publish" and not entry.get("enabled", False):
                    errors.append(label + "：尚未启用发布")
                if action in {"prepare", "publish"} and any(
                    row.get("account") == account and row.get("target") == entry["target"]
                    and row.get("status") in {"preparing", "posting", "needs_review"}
                    for row in state.values()
                ):
                    errors.append(label + "：有待核对的发布任务，先处理该记录")
                selected.append(entry)
            except (ValueError, KeyError) as error:
                errors.append(label + "：" + str(error))
    return selected, errors


def execute(entries, action):
    results = []
    for entry in entries:
        print("\n正在执行：", entry["account"], entry["target"], entry["name"], flush=True)
        command = [sys.executable, str(ROOT / "fb_upload.py"), action,
                   "--account", entry["account"], "--target", entry["target"]]
        # Inherit stdin/stdout so prepare can pause for local review.
        child = subprocess.run(command, cwd=str(ROOT), check=False)
        results.append({"account": entry["account"], "target": entry["target"],
                        "action": action, "exit_code": child.returncode,
                        "finished": datetime.now().astimezone().isoformat()})
        if child.returncode != 0:
            print("本批次已停止；未开始后面的账号。请核对当前账号结果，不要直接重复发布。", flush=True)
            break
    return results


def main():
    parser = argparse.ArgumentParser(description="公共主页批量准备或发布；每个目标每次最多一条")
    parser.add_argument("action", choices=["plan", "check-identity", "prepare", "enable", "publish"], nargs="?", default="plan")
    parser.add_argument("--accounts", required=True, help="例如 fb01,fb02,fb03")
    args = parser.parse_args()
    accounts = list(dict.fromkeys(value.strip() for value in args.accounts.split(",") if value.strip()))
    if not accounts:
        parser.error("至少指定一个账号编号")
    config = upload.read_json(ROOT / "upload_config.json", {"targets": []})
    state = upload.read_json(ROOT / "logs" / "publish_state.json", {})
    entries, errors = select_targets(config, accounts, args.action, state)
    for entry in entries:
        print(entry["account"], entry["target"], entry["name"], entry["url"])
    if errors:
        for error in errors:
            print("STOP：", error)
        print("预检查未通过；没有打开上传页面或点击发布。")
        return 1
    if args.action == "plan":
        print("配置检查通过；plan 不会上传或发布。")
        return 0
    logs = ROOT / "logs"
    logs.mkdir(exist_ok=True)
    lock = logs / "batch.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        print("已有批次正在运行或上次异常留下 batch.lock，请先核对。")
        return 2
    try:
        with os.fdopen(fd, "w") as file:
            file.write(str(os.getpid()))
        results = execute(entries, args.action)
        filename = "batch-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".json"
        upload.save_json(logs / filename, {"results": results})
        print("执行记录：", logs / filename)
        print("实际发布状态请查看 publish_state.json；返回 0 也可能表示没有新视频。")
        return 0 if all(row["exit_code"] == 0 for row in results) else 1
    finally:
        lock.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        raise SystemExit(main())
    except Exception as error:
        print("STOP：", error)
        raise SystemExit(1)
