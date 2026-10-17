#!/usr/bin/env python3
"""
=============================================================================
TataDana Git Management Helper
=============================================================================
Helper mandiri berbasis Python (Dulwich) untuk mengelola repositori Git
tanpa ketergantungan wajib pada git.exe di system PATH.

Penggunaan:
    python scripts/git_helper.py status
    python scripts/git_helper.py log
    python scripts/git_helper.py commit -m "pesan commit"
    python scripts/git_helper.py set-remote <url_remote_github>
=============================================================================
"""

import sys
import argparse
from dulwich import porcelain

def show_status():
    repo = porcelain.open_repo('.')
    status = porcelain.status(repo)
    print("=======================================================")
    print("STATUS REPOSITORI GIT TATADANA")
    print("=======================================================")
    print(f"Staged files   : {len(status.staged.get('add', [])) + len(status.staged.get('modify', []))} file")
    print(f"Unstaged files : {len(status.unstaged)} file")
    print(f"Untracked files: {len(status.untracked)} file")
    if status.untracked:
        for u in status.untracked[:10]:
            print(f"  ? {u}")
    print("=======================================================")

def show_log():
    repo = porcelain.open_repo('.')
    print("=======================================================")
    print("RIWAYAT COMMIT GIT")
    print("=======================================================")
    porcelain.log(repo, max_entries=5)
    print("=======================================================")

def do_commit(message: str):
    repo = porcelain.open_repo('.')
    relpaths, _ = porcelain.add('.')
    commit_id = porcelain.commit(
        repo,
        message=message.encode('utf-8'),
        author=b'TataDana Developer <dev@tatadana.id>',
        committer=b'TataDana Developer <dev@tatadana.id>'
    )
    print(f"[SUKSES] Commit berhasil dibuat: {commit_id.decode()}")

def set_remote(remote_url: str, remote_name: str = "origin"):
    repo = porcelain.open_repo('.')
    porcelain.remote_add(repo, remote_name.encode(), remote_url.encode())
    print(f"[SUKSES] Remote '{remote_name}' berhasil ditambahkan: {remote_url}")

def main():
    parser = argparse.ArgumentParser(description="TataDana Git Helper")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("status", help="Tampilkan status working tree")
    subparsers.add_parser("log", help="Tampilkan log riwayat commit")

    commit_p = subparsers.add_parser("commit", help="Add semua perubahan dan buat commit")
    commit_p.add_argument("-m", "--message", required=True, help="Pesan commit")

    remote_p = subparsers.add_parser("set-remote", help="Tambah remote GitHub")
    remote_p.add_argument("url", help="URL repositori GitHub (contoh: https://github.com/user/tatadana.git)")
    remote_p.add_argument("--name", default="origin", help="Nama remote (default: origin)")

    args = parser.parse_args()

    if args.command == "status":
        show_status()
    elif args.command == "log":
        show_log()
    elif args.command == "commit":
        do_commit(args.message)
    elif args.command == "set-remote":
        set_remote(args.url, args.name)
    else:
        show_status()

if __name__ == "__main__":
    main()
