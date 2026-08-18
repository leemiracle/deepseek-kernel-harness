#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patch_queue.py — Graph 层治理之三：治"冲突"（并行补丁互踩）

手册 02 章 #65-66：并行分支互相踩，in-loop 检查点原理上看不见（每个节点只看见自己的树）。
kernel 开发形态：两个 series 改同一文件 / series 基线漂移 / objtree 并行构建互踩。

治法：把 state/patch_ledger.jsonl 当作**全局账本队列**（graph 层共享状态）：
  claim    文件→series 占用表（互斥；先到先得，后来者收到明确的占用者与等待建议）
  precheck git apply --check 基线漂移检测（apply 不上 = 基线变了，须 rebase）
  release  series 完结释放占用
  status   打印占用表 + open series
（构建端的并行互踩由 tools/k_build.sh 的 flock 兜底 —— 补丁层与构建层各治一段。）

用法:
  python3 patch_queue.py claim S1 drivers/char/foo.c include/linux/foo.h
  python3 patch_queue.py precheck my.patch --repo /path/to/linux
  python3 patch_queue.py release S1
  python3 patch_queue.py status
  python3 patch_queue.py --self-test

退出码: 0=成功  1=冲突/占用  2=用法错
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

LEDGER = Path(__file__).resolve().parent.parent / 'state' / 'patch_ledger.jsonl'


def load_locks():
    """账本 → {file: series_id}（只统计未 release 的 claim，按时间序后者覆盖前者即最新态）"""
    locks = {}
    if not LEDGER.exists():
        return locks
    for line in LEDGER.read_text().splitlines():
        if not line.strip():
            continue
        e = json.loads(line)
        if e['event'] == 'claim':
            for f in e['files']:
                locks[f] = e['series']
        elif e['event'] == 'release':
            for f in e['files']:
                locks.pop(f, None)
    return locks


def append(event):
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with open(LEDGER, 'a') as fh:
        fh.write(json.dumps({'ts': time.strftime('%F %T'), **event}, ensure_ascii=False) + '\n')


def do_claim(series, files):
    locks = load_locks()
    clash = {f: locks[f] for f in files if f in locks and locks[f] != series}
    if clash:
        print(f'[queue] 冲突：以下文件已被其他 series 占用')
        for f, s in clash.items():
            print(f'  {f} ← {s}')
        print('  → 等对方 release，或与之合并 series。强行并行 = graph 层冲突事故。')
        append({'event': 'clash', 'series': series, 'files': sorted(clash)})
        return 1
    append({'event': 'claim', 'series': series, 'files': files})
    print(f'[queue] claim OK: {series} → {files}')
    return 0


def do_precheck(patch, repo='.'):
    if not Path(patch).exists():
        print(f'[queue] no such patch: {patch}')
        return 2
    r = subprocess.run(f'git -C {repo} apply --check {patch}', shell=True,
                       capture_output=True, text=True)
    drift = 'does not match' in (r.stdout + r.stderr) or 'patch does not apply' in (r.stdout + r.stderr)
    if r.returncode == 0:
        print('[queue] precheck OK: 基线未漂移，可 apply')
        append({'event': 'precheck', 'patch': patch, 'result': 'ok'})
        return 0
    print(f'[queue] precheck FAIL: {"基线漂移（须 rebase 到新 HEAD）" if drift else "补丁格式/路径问题"}')
    print((r.stderr or r.stdout).strip()[:500])
    append({'event': 'precheck', 'patch': patch, 'result': 'drift' if drift else 'bad'})
    return 1


def do_release(series):
    locks = load_locks()
    files = [f for f, s in locks.items() if s == series]
    append({'event': 'release', 'series': series, 'files': files})
    print(f'[queue] release: {series} ({len(files)} files freed)')
    return 0


def do_status():
    locks = load_locks()
    print(f'[queue] 账本: {LEDGER}')
    print(f'[queue] 占用表 ({len(locks)}):')
    for f, s in sorted(locks.items()):
        print(f'  {f} ← {s}')
    return 0


def self_test():
    global LEDGER
    # 用临时账本，不污染真实 state/
    import tempfile
    tmp = Path(tempfile.mkdtemp()) / 'test_ledger.jsonl'
    LEDGER = tmp
    ok = True

    r1 = do_claim('S1', ['drivers/char/foo.c', 'include/linux/foo.h'])
    r2 = do_claim('S2', ['drivers/char/foo.c'])               # 必冲突
    r3 = do_claim('S1', ['drivers/char/foo.c'])               # 幂等重占 OK
    r4 = do_claim('S2', ['drivers/net/bar.c'])                # 不同文件 OK
    do_release('S1')
    r5 = do_claim('S2', ['drivers/char/foo.c'])               # 释放后可占

    checks = [('S1 初占', r1, 0), ('S2 抢占必拒', r2, 1), ('S1 幂等', r3, 0),
              ('S2 异文件', r4, 0), ('释放后 S2 可占', r5, 0)]
    for name, got, want in checks:
        mark = '✓' if got == want else '✗'
        ok = ok and got == want
        print(f'  [{mark}] {name}: rc={got} (expect {want})')
    n_lines = len(tmp.read_text().splitlines())
    print(f'  账本事件数: {n_lines}（claim×4+clash×1+release×1 = 6 预期）')
    print('self-test:', 'ALL PASS' if ok else 'FAILED')
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', nargs='?', choices=['claim', 'precheck', 'release', 'status'],
                    help='claim <series> <files...> | precheck <patch> | release <series> | status')
    ap.add_argument('rest', nargs='*')
    ap.add_argument('--repo', default='.')
    ap.add_argument('--self-test', action='store_true')
    args = ap.parse_args()

    if args.self_test:
        return self_test()
    if args.cmd is None:
        ap.error('给个命令：claim/precheck/release/status（或 --self-test）')
        return 2
    if args.cmd == 'claim':
        if len(args.rest) < 2:
            ap.error('claim <series> <file...>')
            return 2
        return do_claim(args.rest[0], args.rest[1:])
    if args.cmd == 'precheck':
        if not args.rest:
            ap.error('precheck <patch.diff>')
            return 2
        return do_precheck(args.rest[0], args.repo)
    if args.cmd == 'release':
        if not args.rest:
            ap.error('release <series>')
            return 2
        return do_release(args.rest[0])
    return do_status()


if __name__ == '__main__':
    sys.exit(main())
