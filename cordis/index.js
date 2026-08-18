/**
 * deepseek-kernel-harness · Cordis plugin entry
 *
 * 融合进官方 DeepSeek Harness (dsh) 生态的形态（2026-08-18 改造）：
 *   - AGENTS.md 领域契约 → ctx.systemPrompt.section(order:110)   [Instructions]
 *   - tools/ 验证金字塔 + governance/ 三查 → ctx.tools.register ×8 [Verification]
 *   - state/ 账本保持文件 JSONL（工具直接追加，跨宿主可移植）       [State]
 *   - 宿主循环/方言/权限 → 由 dsh 自身承担（agent-loop / llm adapter / guarded execution）
 *
 * 纯 JavaScript、零构建——规避 git 安装的 prepare/allowBuilds 陷阱
 * （docs/user/develop/basic/publish.md「Installing from GitHub: the build-script catch」）。
 *
 * API 依据（一手核实 2026-08-18）：
 *   defineTool/ctx.tools.register — docs/cordis-tutorial/07-into-the-harness.md
 *   ctx.systemPrompt.section      — packages/core/system-prompt/README.md（order 带：100-199 工具指引）
 *   Schema 配置                   — docs/cordis-tutorial/05-config.md
 */
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawn } from 'node:child_process'
import Schema from '@deepseek-ai/schemastery'
import { defineTool } from '@deepseek-ai/dsh-tools'

const HERE = path.dirname(fileURLToPath(import.meta.url)) // <pkg>/cordis
const PKG = path.resolve(HERE, '..')                      // 包根（npm/git 安装后同构）

export const name = 'deepseek-kernel-harness'
export const inject = ['tools', 'systemPrompt'] // 等 registry 就绪（tutorial ch.3）

export const Config = Schema.object({
  kernelSrc: Schema.string().default(process.env.KERNEL_SRC ?? '').description(
    'Linux 内核树绝对路径；空则工具自探测并报装法（fail-loud，不静默）'),
  kout: Schema.string().default(process.env.KOUT ?? '').description(
    '外置 objtree（L3 增量构建产物目录；空则 KERNEL_SRC/.kout）'),
  taskType: Schema.string().default('add').description(
    '默认任务类型：add | del | cleanup | refactor——决定 Goodhart 守卫 G1 删除率阈值的适用性'),
  timeoutMs: Schema.number().default(300000).description('单个工具超时（ms）'),
})

// ---------- 工具执行内核：spawn CLI + 结果预算（手册 04 章：保尾部，错误栈在最后） ----------
const RESULT_CAP = 16_000

function runCLI(cmd, args, config) {
  const env = { ...process.env }
  if (config.kernelSrc) env.KERNEL_SRC = config.kernelSrc
  if (config.kout) env.KOUT = config.kout
  return new Promise((resolve) => {
    const p = spawn(cmd, args, { cwd: PKG, env })
    let out = '', err = ''
    const timer = setTimeout(() => p.kill('SIGKILL'), config.timeoutMs)
    p.stdout.on('data', (d) => { out += d })
    p.stderr.on('data', (d) => { err += d })
    p.on('error', (e) => { clearTimeout(timer); resolve(`exit=127\nspawn failed: ${e.message}`) })
    p.on('close', (code) => {
      clearTimeout(timer)
      let text = `exit=${code}\n${out}` + (err ? `\n[stderr]\n${err}` : '')
      if (text.length > RESULT_CAP) text = text.slice(-RESULT_CAP) + '\n[truncated, kept tail 16K — 用更窄的 target/offset 定位]'
      resolve(text)
    })
  })
}

const sh = (name) => path.join(PKG, 'tools', name)
const py = (name) => path.join(PKG, 'governance', name)

// output 工厂（canonical string + text render —— tutorial 07 形态）
const textOut = {
  schema: { type: 'string' },
  render: (_args, value) => [{ type: 'text', text: value }],
}

// ---------- 工具注册表：验证金字塔 L1-L4 + graph 三查 + 队列 ----------
const TOOL_SPECS = [
  {
    name: 'k_check',
    description: 'L1 风格验证：checkpatch.pl --strict。金字塔第一层，不过不碰 L2。失败输出即修复导航：修第一个 ERROR 再重跑。',
    parameters: { target: { type: 'string', required: true, description: 'file.c 或 patch.diff（相对内核树或绝对路径）' } },
    run: (a, c) => runCLI('bash', [sh('k_check.sh'), a.target ?? ''], c),
  },
  {
    name: 'k_static',
    description: 'L2 静态分析：sparse (C=2) + coccinelle。需要内核树；工具缺失时报装法（exit 2）。',
    parameters: { target: { type: 'string', required: true, description: '内核树相对路径（子系统目录）' } },
    run: (a, c) => runCLI('bash', [sh('k_static.sh'), a.target ?? ''], c),
  },
  {
    name: 'k_build',
    description: 'L3 构建验证：make W=1 增量（外置 objtree + flock 防并行互踩）。警告=失败心态：非零警告须逐条解释。',
    parameters: { target: { type: 'string', required: true, description: '内核树相对路径（M= 目标）' } },
    run: (a, c) => runCLI('bash', [sh('k_build.sh'), a.target ?? ''], c),
  },
  {
    name: 'k_boot',
    description: 'L4 冒烟：virtme/qemu 启动刚构建的内核。金字塔顶层，L3 过了才值得跑。',
    parameters: {},
    run: (_a, c) => runCLI('bash', [sh('k_boot.sh')], c),
  },
  {
    name: 'k_maintainer',
    description: 'LKML 收件人解析：get_maintainer.pl。收件人由脚本决定，agent 不自选（契约）。',
    parameters: { target: { type: 'string', required: true, description: 'file.c 或 patch.diff' } },
    run: (a, c) => runCLI('bash', [sh('k_maintainer.sh'), a.target ?? ''], c),
  },
  {
    name: 'graph_guard',
    description: 'graph 三查①反 Goodhart：diff 结构级反 gaming（删代码消警告/注释掉报警/抑制标记/空 diff）。改完必跑；REJECT = 禁止入队。判定看 diff 结构不看警告数——指标可被 gaming，结构不可。',
    parameters: {
      base: { type: 'string', description: 'git base（默认 HEAD~1）' },
      taskType: { type: 'string', description: 'add/del/cleanup/refactor（覆盖默认）' },
    },
    run: (a, c) => runCLI('python3', [py('goodhart_guards.py'), '--base', a.base ?? 'HEAD~1',
      '--task-type', a.taskType ?? c.taskType,
      ...(c.kernelSrc ? ['--repo', c.kernelSrc] : []), '--json'], c),
  },
  {
    name: 'graph_conflict',
    description: 'graph 三查②治向上盲区：按 diff 文件路径输出影响面 + 必须补验清单（include/→全树抽样重编；Kconfig→config 矩阵）。头文件/Kconfig/Makefile 改动必跑。',
    parameters: {
      base: { type: 'string', description: 'git base（默认 HEAD~1）' },
      files: { type: 'string', description: '逗号分隔文件列表（与 base 二选一）' },
    },
    run: (a, c) => runCLI('python3', [py('global_conflicts.py'),
      ...(a.files ? ['--files', a.files] : ['--base', a.base ?? 'HEAD~1',
      ...(c.kernelSrc ? ['--repo', c.kernelSrc] : [])]), '--json'], c),
  },
  {
    name: 'patch_queue',
    description: 'graph 三查③治并行冲突：补丁队列（账本即队列，file→series 互斥）。改文件前 claim 查占用；完结 release；precheck 测基线漂移。claim 前必须先过 graph_guard + graph_conflict。',
    parameters: {
      action: { type: 'string', required: true, description: 'status | claim | release | precheck' },
      series: { type: 'string', description: 'series 标识（claim/release 用，如 S-NET-FIX）' },
      files: { type: 'string', description: '逗号分隔文件列表（claim 用）' },
      patch: { type: 'string', description: '补丁路径（precheck 用）' },
    },
    run: (a, c) => {
      const args = [py('patch_queue.py'), a.action ?? 'status']
      if (a.action === 'claim' && a.series) args.push(a.series, ...(a.files ?? '').split(',').map(s => s.trim()).filter(Boolean))
      if (a.action === 'release' && a.series) args.push(a.series)
      if (a.action === 'precheck' && a.patch) args.push(a.patch, ...(c.kernelSrc ? ['--repo', c.kernelSrc] : []))
      return runCLI('python3', args, c)
    },
  },
]

// ---------- apply：契约进 system prompt + 工具进 registry ----------
export function apply(ctx, config) {
  // 1) 领域契约（AGENTS.md）→ system prompt 工具指引带（order 100-199，官方 band 约定）
  const contract = readFileSync(path.join(PKG, 'AGENTS.md'), 'utf8')
  ctx.systemPrompt.section({
    name: 'kernel-dev-contract',
    order: 110,
    text: `# Kernel Dev Contract（deepseek-kernel-harness）\n${contract}`,
  })

  // 2) 8 个 model-facing 工具（schema 即 prompt：金字塔纪律写在 description 里）
  for (const spec of TOOL_SPECS) {
    ctx.tools.register(defineTool({
      name: spec.name,
      description: spec.description,
      parameters: spec.parameters,
      output: textOut,
      async execute(args) {
        return spec.run(args ?? {}, config)
      },
    }))
  }

  ctx.logger?.info?.(`[dsh-kernel-harness] 8 tools + contract section registered (kernelSrc=${config.kernelSrc || '<auto>'})`)
}
