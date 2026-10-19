"""Apply a supplied caption to the selected accounts' current unrecorded MP4s.

This is a one-time local edit, never a permanent publishing default.
"""
import argparse
import os
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import fb_upload as upload
from add_fb_accounts import locked

ROOT = Path(__file__).resolve().parent


def atomic_caption(path, text):
    fd, name = tempfile.mkstemp(prefix=".caption-", suffix=".tmp", dir=str(path.parent))
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text + "\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def apply(accounts, text):
    text = text.strip()
    if not text:
        raise ValueError("统一文案不能为空。")
    if not accounts or len(set(accounts)) != len(accounts):
        raise ValueError("请指定不重复的账号编号。")
    configuration = upload.read_json(ROOT / "upload_config.json", {})
    state = upload.read_json(ROOT / "logs" / "publish_state.json", {})
    entries = []
    for account in accounts:
        matches = [r for r in configuration.get("targets", []) if r.get("account") == account]
        if len(matches) != 1:
            raise ValueError(account + " 必须有唯一的已配置目标，未修改文案。")
        entry = matches[0]
        upload.validate_entry(entry)
        entries.append(entry)
    changes = []
    counts = {a: 0 for a in accounts}
    for entry in entries:
        folder = ROOT / "videos" / entry["account"] / entry["target"] / "inbox"
        if not folder.is_dir():
            print("没有待发布目录，跳过：", entry["account"])
            continue
        excluded = {s.lower() for s in entry.get("excluded_files", [])}
        for video in sorted(folder.iterdir()):
            if not video.is_file() or video.suffix.lower() != ".mp4":
                continue
            video.resolve().relative_to(ROOT.resolve())
            if video.name.lower() in excluded or video.stat().st_size == 0:
                print("空文件或排除文件，跳过：", entry["account"], video.name)
                continue
            if datetime.now().timestamp() - video.stat().st_mtime < 60:
                raise ValueError("视频刚更新，请复制完成一分钟后重试：" + str(video))
            before = video.stat()
            key = upload.job_key(entry, video)
            after = video.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise ValueError("视频正在变化，请等待复制完成：" + str(video))
            if key in state:
                print("已有发布/任务记录，保留原文案：", entry["account"], video.name)
                continue
            caption = video.with_suffix(".txt")
            caption.resolve().relative_to(ROOT.resolve())
            if caption.exists() and not caption.is_file():
                raise ValueError("文案路径不是文件：" + str(caption))
            counts[entry["account"]] += 1
            expected = (text + "\n").encode("utf-8")
            if caption.is_file() and caption.read_bytes() == expected:
                continue
            changes.append(caption)
    if not changes:
        print("没有需要修改的文案；未上传或发布。")
        return counts
    backup = ROOT / "backups" / ("common-caption-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
    backup.mkdir(parents=True, exist_ok=False)
    existing = {path for path in changes if path.exists()}
    for path in existing:
        saved = backup / path.relative_to(ROOT)
        saved.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, saved)
    upload.save_json(backup / "changes.json", {
        "created": datetime.now().astimezone().isoformat(),
        "files": [{"path": str(p.relative_to(ROOT)), "had_caption": p in existing} for p in changes],
    })
    written = []
    try:
        for path in changes:
            atomic_caption(path, text)
            written.append(path)
    except Exception:
        for path in reversed(written):
            if path in existing:
                shutil.copy2(backup / path.relative_to(ROOT), path)
            else:
                path.unlink()
        raise
    for account in accounts:
        print(account, "匹配待发布视频：", counts[account])
    print("已生成/更新同名 TXT：", len(changes), "份；原文案备份：", backup)
    print("只处理当前 inbox；未上传、发布或修改定时设置。请等一分钟再运行 prepare。")
    return counts


def main():
    parser = argparse.ArgumentParser(description="为本轮待发布视频批量生成统一的同名 TXT")
    parser.add_argument("--accounts", required=True)
    parser.add_argument("--text-file", type=Path, required=True)
    args = parser.parse_args()
    text = args.text_file.read_text(encoding="utf-8-sig")
    with locked():
        apply([a.strip() for a in args.accounts.split(",") if a.strip()], text)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        raise SystemExit(main())
    except Exception as error:
        print("STOP：", error)
        raise SystemExit(1)
