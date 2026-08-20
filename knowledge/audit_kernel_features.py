#!/usr/bin/env python3
"""audit_kernel_features.py — x-kernel 已实现功能扫描器（问题发现入口）

产出：crate 清单 + docs 覆盖率 + 风险信号（TODO/FIXME/unwrap/unsafe 密度）
     + 近期 commit 变更域汇总 → 供 xkernel_feature_audit.md 迭代。

用法： python3 audit_kernel_features.py /path/to/x-kernel [--since <git-ref>]
零依赖（纯标准库）。
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


def sh(repo, *args):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=30)
    return r.stdout


def scan_crates(repo: Path):
    """workspace 成员 crate 扫描：docs 覆盖 + 风险信号密度"""
    rows = []
    for cargo in sorted(repo.rglob("Cargo.toml")):
        if "target" in cargo.parts:
            continue
        d = cargo.parent
        rs_files = [p for p in d.rglob("*.rs") if "target" not in p.parts]
        if not rs_files:
            continue
        text = "\n".join(p.read_text(errors="ignore") for p in rs_files)
        n_lines = text.count("\n")
        sig = {
            "crate_dir": str(d.relative_to(repo)),
            "rs_files": len(rs_files),
            "loc": n_lines,
            "todo_fixme": len(re.findall(r"\b(TODO|FIXME|XXX)\b", text)),
            "unwrap": len(re.findall(r"\.unwrap\(\)", text)),
            "unsafe_fn": len(re.findall(r"\bunsafe\s+fn\b", text)),
            "unsafe_block": len(re.findall(r"\bunsafe\s*\{", text)),
            "safety_notes": len(re.findall(r"//\s*SAFETY:", text)),
            "docs_design": (d / "docs" / "design.md").exists(),
            "docs_security": (d / "docs" / "security.md").exists(),
        }
        sig["risk_index"] = round(
            (sig["todo_fixme"] * 3 + sig["unwrap"] * 2
             + max(0, sig["unsafe_fn"] + sig["unsafe_block"] - sig["safety_notes"]))
            / max(1, n_lines / 1000), 2)
        rows.append(sig)
    return rows


def commit_domains(repo: Path, since=None):
    """近期 commit 变更域汇总（问题域发现的驱动源）"""
    rng = f"{since}..HEAD" if since else "-20"
    log = sh(repo, "log", "--format=%h|%s", rng)
    files = sh(repo, "log", "--format=", "--name-only", rng)
    domains = {}
    for f in filter(None, files.splitlines()):
        top = f.split("/")[0] if "/" in f else "(root)"
        domains[top] = domains.get(top, 0) + 1
    return [{"commits": len(log.strip().splitlines()),
             "domains": sorted(domains.items(), key=lambda x: -x[1])[:12]}]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("repo", nargs="?", default="/data/usershare/ai/x-kernel")
    ap.add_argument("--since", default=None, help="git ref，如 !637 对应 hash")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    repo = Path(a.repo)
    if not repo.exists():
        print(f"repo 不存在: {repo}")
        return 1

    crates = scan_crates(repo)
    # docs 覆盖率
    no_design = [c["crate_dir"] for c in crates if not c["docs_design"]]
    no_sec = [c["crate_dir"] for c in crates if not c["docs_security"]]
    # 风险 Top10
    top_risk = sorted(crates, key=lambda c: -c["risk_index"])[:10]
    commits = commit_domains(repo, a.since)

    if a.json:
        print(json.dumps({"crates": crates, "commits": commits}, ensure_ascii=False, indent=1))
        return 0

    print(f"== x-kernel 功能审计扫描（{repo}）==")
    print(f"crate 总数: {len(crates)}  总 LOC: {sum(c['loc'] for c in crates)}")
    print(f"docs/design.md 覆盖: {len(crates)-len(no_design)}/{len(crates)}"
          f"（缺失 {len(no_design)}）")
    print(f"docs/security.md 覆盖: {len(crates)-len(no_sec)}/{len(crates)}（缺失 {len(no_sec)}）")
    print(f"\n风险指数 Top10（TODO×3 + unwrap×2 + 无SAFETY的unsafe，每千行）:")
    for c in top_risk:
        flags = []
        if not c["docs_design"]:
            flags.append("无design.md")
        if c["unsafe_fn"] + c["unsafe_block"] > c["safety_notes"]:
            flags.append(f"SAFETY缺口{c['unsafe_fn']+c['unsafe_block']-c['safety_notes']}")
        print(f"  {c['risk_index']:>7.2f}  {c['crate_dir']:<36} "
              f"loc={c['loc']:<6} todo={c['todo_fixme']:<3} unwrap={c['unwrap']:<4} "
              f"{' '.join(flags)}")
    for c in commits:
        print(f"\n近期 {c['commits']} commits 变更域 Top: {c['domains']}")
    print("\n下一步：对照 knowledge/xkernel_feature_audit.md 新增/更新问题假设；"
          "高风险 crate 用 deepseek_host.py --task 定向审计")
    return 0


if __name__ == "__main__":
    sys.exit(main())
