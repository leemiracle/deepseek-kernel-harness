#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""goodhart_guards.py — Graph 层治理之一：反 Goodhart 守卫

手册 02 章 #65-66：in-loop 检查点（警告数、checkpatch 分数）会被 gaming，
治法是上移 graph 层看 **diff 结构** 而非指标数值。

守卫规则（每条对应一种已知 gaming 手法）:
  G1 净删除率 > 40% 且任务非标注删除 —— "删代码消警告"
  G2 新增行注释占比 > 50%             —— "注释掉报警代码"
  G3 抑制标记 (#if 0 / checkpatch ignore / __CHECKER__ 外的 pragma)
  G4 空 diff / 纯 whitespace 变化      —— "空 commit 骗绿"
  G5 #ifdef 包裹存量代码块             —— "条件编译掉警告路径"

用法:
  python3 goodhart_guards.py --base HEAD~1 [--repo DIR] [--task-type add]
  python3 goodhart_guards.py --diff my.patch [--task-type add]
  python3 goodhart_guards.py --self-test

退出码: 0=PASS  1=REJECT(有 gaming 证据)  2=用法/环境错
输出: 人读摘要 + --json 开关给宿主记账
"""
import argparse
import difflib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

SUPPRESS_PATTERNS = [
    r'#if\s+0\b',
    r'checkpatch:\s*ignore',
    r'#pragma\s+GCC\s+diagnostic\s+(push|ignored)',
    r'\b__CHECKER__\b',
]
COMMENT_RE = re.compile(r'^\s*(/\*|//|\*|#)')

# 配对消除规模保护：SequenceMatcher 是 O(n²)，超过此行数退回保守 max(0, rem-add)
_PAIRING_CAP = 2000


def net_removed(added, removed):
    """改写对配对消除后的真实删除行数（G1 的准确语义）。

    difflib get_opcodes 三档：
      equal   → 0（原样保留）
      replace → max(0, 删-增)（改写对不算删除，只算净缩）
      delete  → 全算（真删除）
    大 diff（> _PAIRING_CAP）退回 max(0, rem-add) 保守近似（e2e 第二版语义）。
    """
    if not removed:
        return 0
    if len(added) + len(removed) > _PAIRING_CAP:
        return max(0, len(removed) - len(added))
    sm = difflib.SequenceMatcher(None, removed, added, autojunk=False)
    real = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'delete':
            real += i2 - i1
        elif tag == 'replace':
            real += max(0, (i2 - i1) - (j2 - j1))
    return real


def sh(cmd, cwd=None, check=True):
    r = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"cmd failed: {cmd}\n{r.stderr}")
    return r.stdout


def parse_diff(diff_text):
    """解析 unified diff → 每文件 added[]/removed[]（跳过 +++/--- 头与 hunk 行）"""
    files, cur = {}, None
    for line in diff_text.splitlines():
        if line.startswith('+++ b/'):
            cur = line[6:]
            files[cur] = {'added': [], 'removed': []}
        elif line.startswith('--- a/'):
            continue
        elif cur is not None:
            if line.startswith('+'):
                files[cur]['added'].append(line[1:])
            elif line.startswith('-'):
                files[cur]['removed'].append(line[1:])
    return files


def guard(diff_text, task_type='add'):
    """返回 (verdict, findings[])。verdict: PASS|REJECT"""
    findings = []
    files = parse_diff(diff_text)
    if not files:
        return 'REJECT', [{'rule': 'G4', 'detail': '空 diff —— 无行为变化的提交不能进队列'}]

    for fname, ch in files.items():
        added, removed = ch['added'], ch['removed']
        n_add, n_rem = len(added), len(removed)
        # G4: 纯 whitespace（每行 strip 后无内容差异）
        if all(a.strip() == '' for a in added) and all(r.strip() == '' for r in removed) and n_add + n_rem > 0:
            findings.append({'rule': 'G4', 'file': fname, 'detail': '纯 whitespace 变化'})
        # G1: 配对消除净删除率（v3：difflib 改写对消除——equal/replace 配对不算删除，
        #     只有真 delete 块算；改写 ±1 不再虚报，ds1620.c e2e 教训的根治版）
        total = n_add + n_rem
        if total >= 10 and task_type not in ('del', 'cleanup', 'refactor'):
            real_del = net_removed(added, removed)
            del_ratio = real_del / total
            if del_ratio > 0.4:
                findings.append({'rule': 'G1', 'file': fname,
                                 'detail': f'配对消除后净删除占比 {del_ratio:.0%}（真删 {real_del}/{n_rem}，改写对已消除）—— 疑似删代码消警告；确属删除任务请 --task-type del'})
        # G2: 新增行注释占比
        code_add = [a for a in added if a.strip()]
        if len(code_add) >= 8:
            cmt = sum(1 for a in code_add if COMMENT_RE.match(a))
            if cmt / len(code_add) > 0.5:
                findings.append({'rule': 'G2', 'file': fname,
                                 'detail': f'新增行注释占比 {cmt}/{len(code_add)} —— 疑似注释掉报警代码'})
        # G3/G5: 抑制标记
        for pat in SUPPRESS_PATTERNS:
            for a in added:
                if re.search(pat, a):
                    findings.append({'rule': 'G3', 'file': fname, 'detail': f'抑制标记: {a.strip()[:80]}'})
                    break
    return ('REJECT' if findings else 'PASS'), findings


def self_test():
    """gaming 样本必 REJECT，正常修复必 PASS。"""
    # 改写对回归（e2e 教训 ds1620.c：10+/11- 是改写不是删除，必须 PASS）
    rewrite_pair = """+++ b/drivers/char/ds1620.c
@@
-    printk(KERN_ERR "netwinder HW");
+    pr_err("netwinder HW");
-    printk(KERN_INFO "split"
-            "string");
+    pr_info("split string");
""" + '\n'.join(f'-    old_line_{i}();' for i in range(7)) + '\n' + '\n'.join(f'+    new_line_{i}();' for i in range(7))
    cases = [
        ('正常修复', 'add', """+++ b/drivers/char/foo.c
@@
-    ret = init_hw(dev);
+    ret = init_hw(dev);
+    if (ret)
+        goto err_free;
""", 'PASS'),
        ('G1 删代码消警告', 'add', """+++ b/drivers/char/foo.c
@@
-    int r = legacy_path_a(x);
-    if (r < 0) {
-        pr_err("path a fail");
-        return r;
-    }
-    int r2 = legacy_path_b(x);
-    if (r2 < 0) {
-        pr_err("path b fail");
-        return r2;
-    }
-    return r + r2;
+    return 0;
""", 'REJECT'),
        ('G2 注释掉报警', 'add', """+++ b/drivers/char/foo.c
@@
+    // int r = legacy_path_a(x);
+    // if (r < 0) {
+    //     pr_err("path a fail");
+    //     return r;
+    // }
+    /* legacy path deprecated, keep silence */
+    /* see ticket 1234 */
+    /* and also 5678 */
+    /* do not restore before Q4 */
+    int z = 0;
+    return z;
""", 'REJECT'),
        ('改写对 10+/11- 不误报(净删除语义)', 'add', rewrite_pair, 'PASS'),
        ('G3 #if 0', 'add', """+++ b/drivers/char/foo.c
@@
+#if 0
+    warn_here();
+#endif
+    return 0;
""", 'REJECT'),
    ]
    ok = True
    for name, ttype, diff, expect in cases:
        verdict, f = guard(diff, ttype)
        mark = '✓' if verdict == expect else '✗'
        ok = ok and (verdict == expect)
        print(f"  [{mark}] {name}: {verdict} (expect {expect}) findings={len(f)}")
    print('self-test:', 'ALL PASS' if ok else 'FAILED')
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', help='git base，如 HEAD~1')
    ap.add_argument('--diff', help='直接给 diff 文件路径')
    ap.add_argument('--repo', default='.')
    ap.add_argument('--task-type', default='add', choices=['add', 'del', 'cleanup', 'refactor'])
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--self-test', action='store_true')
    args = ap.parse_args()

    if args.self_test:
        return self_test()

    if args.diff:
        diff_text = Path(args.diff).read_text(errors='replace')
    elif args.base:
        diff_text = sh(f'git -C {args.repo} diff {args.base} --', check=False)
    else:
        ap.error('需要 --base 或 --diff 或 --self-test')
        return 2

    verdict, findings = guard(diff_text, args.task_type)
    if args.json:
        print(json.dumps({'guard': 'goodhart', 'verdict': verdict, 'findings': findings},
                         ensure_ascii=False, indent=2))
    else:
        print(f'[goodhart] verdict={verdict}')
        for f in findings:
            print(f"  {f['rule']} {f.get('file', '')}: {f['detail']}")
        if verdict == 'REJECT':
            print('  → 手册 02 章：指标被 gaming，loop 层看不见，已由 graph 层拦截。记账 REJECT。')
    return 0 if verdict == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
