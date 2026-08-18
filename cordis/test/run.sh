#!/usr/bin/env bash
# run.sh — Cordis 层一键回归（dsh rc 期 breaking 时跑这个）
# 依赖：node≥18 + npm（沙盒内自动装 loader/deps；首次约 30-60s，缓存后秒级）
set -u
REPO=$(cd "$(dirname "$0")/../.." && pwd)   # 仓根（先算好，后面 cd 沙盒不失效）
cd "$REPO"
[ -d node_modules/@deepseek-ai/cordis ] || { echo "缺依赖：npm install"; exit 2; }

SB=$(mktemp -d /tmp/kh-cordis-test.XXXXXX)
# KEEP_SANDBOX=1 保留现场（默认清；失败时也保留供解剖）
if [ "${KEEP_SANDBOX:-0}" != "1" ]; then trap 'rm -rf "$SB"' EXIT; fi
echo "[regress] sandbox: $SB"
git init -q "$SB" && git -C "$SB" config user.email t@t && git -C "$SB" config user.name t

# 内置 gaming 样本：12 行报警代码全注释（G2 必触发，此前多轮实证）
cat > "$SB/demo.c" <<'EOF'
int probe(void){
    int r = legacy_probe_a(dev);
    if (r < 0) {
        dev_err(dev, "a fail");
        return r;
    }
    int r2 = legacy_probe_b(dev);
    if (r2 < 0) {
        dev_err(dev, "b fail");
        return r2;
    }
    return r + r2;
}
EOF
git -C "$SB" add . && git -C "$SB" commit -qm init
cat > "$SB/demo.c" <<'EOF'
int probe(void){
    // int r = legacy_probe_a(dev);
    // if (r < 0) {
    //     dev_err(dev, "a fail");
    //     return r;
    // }
    /* deprecated legacy probe a, see ticket 9981 */
    /* keep silence per maintainer request 2026-08 */
    // int r2 = legacy_probe_b(dev);
    // if (r2 < 0) {
    //     dev_err(dev, "b fail");
    //     return r2;
    // }
    return 0;
}
EOF

rm -f "$REPO/cordis/test/result.json"

# 沙盒装齐 loader 依赖（真实用户安装形态；复用 npm 缓存，秒级）
cat > "$SB/package.json" <<EOF
{ "name": "kh-regress", "private": true,
  "dependencies": {
    "@deepseek-ai/cordis": "4.0.1",
    "@deepseek-ai/cordis-plugin-loader": "^1.0.2",
    "@deepseek-ai/cordis-plugin-include": "^1.0.6",
    "@deepseek-ai/cordis-plugin-group": "^1.0.1",
    "@deepseek-ai/cordis-plugin-hmr": "^1.0.16",
    "@deepseek-ai/cordis-plugin-timer": "^1.1.3",
    "@deepseek-ai/dsh-system-prompt": "0.1.0-rc.7",
    "@deepseek-ai/dsh-tools": "0.1.0-rc.7",
    "@deepseek-ai/dsh-llm": "0.1.0-rc.7",
    "deepseek-kernel-harness": "file:$REPO"
  } }
EOF
(cd "$SB" && npm install --no-audit --no-fund --silent > "$SB/npm.log" 2>&1) || { echo "沙盒 npm install 失败："; tail -5 "$SB/npm.log"; exit 2; }

# cordis.yml 经由已安装包名引用（node 解析走沙盒 node_modules）
cat > "$SB/cordis.yml" <<EOF
- name: '@deepseek-ai/dsh-system-prompt'
- name: '@deepseek-ai/dsh-tools'
- name: 'deepseek-kernel-harness'
  config:
    kernelSrc: $SB
    taskType: add
- name: '$REPO/cordis/test/drive.mjs'
EOF

echo "[regress] kernel Cordis 管线：loader → tools.execute(graph_guard) → prompt 装配"
(cd "$SB" && timeout -k 3 90 node node_modules/@deepseek-ai/cordis/bin.js > "$SB/boot.log" 2>&1)
RC=$?
echo "--- result ---"
cat "$REPO/cordis/test/result.json" 2>/dev/null || { echo "(result missing)"; tail -15 "$SB/boot.log" 2>/dev/null; exit 1; }
[ $RC -eq 0 ] && echo "[regress] PASS (RC=0)" || echo "[regress] FAIL (RC=$RC)"
exit $RC
