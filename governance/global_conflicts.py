#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""global_conflicts.py — Graph 层治理之二：治"向上盲区"

手册 02 章 #65-66：局部节点（单会话 agent 只编译自己改的子系统）看不见全局冲突。
kernel 开发的经典事故：
  - 改 include/ 头文件，只跑了本驱动的 k_build → 下游 37 个目录编译坏
  - 改 Kconfig，只验 defconfig → allmodconfig 下选配组合崩
  - 改 scripts/ 或 Makefile，影响面是全树

治法（graph 层 = 有全树视角的规则引擎）:
  对 diff 的每个文件按路径分类 → 生成"影响面声明 + 必须补的重验命令"。
  宿主把 required_rechecks 逐条跑完才许入补丁队列 —— 单会话自己"觉得没问题"不算数。

用法:
  python3 global_conflicts.py --base HEAD~1 [--repo DIR] [--ks KERNEL_SRC]
  python3 global_conflicts.py --files include/linux/foo.h,drivers/char/foo.c
  python3 global_conflicts.py --self-test

退出码: 0=无需补验  1=有盲区须补验(required_rechecks 非空)  2=用法错
"""
import argparse
import json
import subprocess
import sys

# 路径前缀 → (影响面等级, 必须补的重验)
RULES = [
    ('include/', {
        'level': 'TREE-WIDE',
        'why': '头文件改动影响所有 include 者；本子系统 L3 过 ≠ 全树过',
        'recheck': [
            'grep -rl <HEADER_BASENAME> --include="*.c" $KERNEL_SRC | head -40  # 引用面清单',
            'make O=$KOUT allmodconfig && make -j$(nproc) O=$KOUT W=1 M=<引用面抽样的3个目录>',
        ]}),
    ('Kconfig', {
        'level': 'CONFIG-MATRIX',
        'why': 'Kconfig 改动改变选配组合，单一 .config 证明不了',
        'recheck': [
            'make O=$KOUT.allyes allyesconfig && make -j$(nproc) O=$KOUT.allyes M=<本子系统>',
            'make O=$KOUT.allmod allmodconfig && make -j$(nproc) O=$KOUT.allmod M=<本子系统>',
        ]}),
    ('scripts/', {
        'level': 'TOOLCHAIN',
        'why': '构建系统/脚本改动影响每一次构建',
        'recheck': ['make O=$KOUT clean 紧接全量 k_build.sh（消除增量构建的缓存侥幸）']}),
    ('Makefile', {
        'level': 'SUBSYSTEM',
        'why': '构建规则改动影响本子系统全部目标',
        'recheck': ['make O=$KOUT M=<所在目录> clean 后重跑 k_build.sh']}),
    ('Documentation/', {
        'level': 'DOC-ONLY',
        'why': '纯文档，无需重编（但 checkpatch 的 doc 警告仍须过）',
        'recheck': []}),
]


def classify(path):
    """单文件 → 匹配的规则（取最长前缀命中；无命中=普通 .c/.o 级改动）"""
    best = None
    for prefix, rule in RULES:
        if (path == prefix.rstrip('/') or path.startswith(prefix) or path.endswith('/' + prefix)
                or path.split('/')[-1] == prefix):
            if best is None or len(prefix) > len(best[0]):
                best = (prefix, rule)
    return best


def analyze(paths, ks='.'):
    findings, rechecks = [], []
    for p in paths:
        m = classify(p)
        if not m:
            continue
        prefix, rule = m
        findings.append({'file': p, 'level': rule['level'], 'why': rule['why']})
        for rc in rule['recheck']:
            rc2 = rc.replace('<HEADER_BASENAME>', p.split('/')[-1])
            if rc2 not in rechecks:
                rechecks.append(rc2)
    return findings, rechecks


def self_test():
    cases = [
        ('drivers/char/foo.c', 0),          # 普通驱动：无盲区
        ('include/linux/netdevice.h', 1),   # 头文件：必补全树抽样
        ('drivers/net/Kconfig', 1),         # Kconfig：必补 config 矩阵
        ('Documentation/gpu/foo.rst', 0),   # 纯文档：recheck 空
        ('scripts/Makefile.build', 1),      # 构建系统：全量重验
    ]
    ok = True
    for path, expect_n_recheck in cases:
        f, r = analyze([path])
        got = 1 if r else 0
        mark = '✓' if got == expect_n_recheck else '✗'
        ok = ok and got == expect_n_recheck
        lvl = f[0]['level'] if f else '—'
        print(f"  [{mark}] {path}: level={lvl} rechecks={len(r)}")
    # 组合 case：头文件+驱动同时改，recheck 合并去重
    f, r = analyze(['include/linux/foo.h', 'drivers/char/foo.c', 'include/linux/bar.h'])
    dup = len(r) != len(set(r))
    ok = ok and not dup and len(r) >= 2
    print(f"  [{'✓' if not dup and len(r)>=2 else '✗'}] 组合去重: {len(r)} 条（无重复={not dup}）")
    print('self-test:', 'ALL PASS' if ok else 'FAILED')
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', help='git base')
    ap.add_argument('--files', help='逗号分隔文件列表（相对内核树）')
    ap.add_argument('--repo', default='.')
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--self-test', action='store_true')
    args = ap.parse_args()

    if args.self_test:
        return self_test()

    if args.files:
        paths = [x.strip() for x in args.files.split(',') if x.strip()]
    elif args.base:
        out = subprocess.run(f'git -C {args.repo} diff --name-only {args.base}',
                             shell=True, capture_output=True, text=True).stdout
        paths = [x for x in out.splitlines() if x.strip()]
    else:
        ap.error('需要 --files 或 --base 或 --self-test')
        return 2

    findings, rechecks = analyze(paths)
    if args.json:
        print(json.dumps({'guard': 'blindspot', 'verdict': 'CLEAN' if not rechecks else 'RECHECK-REQUIRED',
                          'findings': findings, 'required_rechecks': rechecks},
                         ensure_ascii=False, indent=2))
    else:
        print(f'[blindspot] verdict={"CLEAN" if not rechecks else "RECHECK-REQUIRED"}')
        for f in findings:
            print(f"  {f['file']} [{f['level']}] {f['why']}")
        for r in rechecks:
            print(f'  → 补验: {r}')
        if rechecks:
            print('  → 手册 02 章：局部节点看不见的全局冲突，必须 graph 层补验后才准入队。')
    return 1 if rechecks else 0


if __name__ == '__main__':
    sys.exit(main())
