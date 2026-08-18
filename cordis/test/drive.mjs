// drive.mjs — keyless 回归驱动：官方 Cordis loader 直跑（dsh --profile 无 app 时常驻静默，故绕行）
// 断言：①工具穿管线 ②契约段进 prompt 装配。RC=0 过 / 1 失败。
import { writeFileSync, readFileSync } from 'node:fs'
import { CallId } from '@deepseek-ai/dsh-llm'

export const name = 'drive-test'
export const inject = ['tools', 'systemPrompt']

export function apply(ctx) {
  const RESULT = new URL('./result.json', import.meta.url).pathname
  writeFileSync(RESULT, JSON.stringify({ stage: 'loaded' }))
  void (async () => {
    try {
      const r = await ctx.tools.execute({
        callId: CallId('kdev-regress-1'),
        name: 'graph_guard',
        arguments: { base: 'HEAD', taskType: 'add' },
        signal: new AbortController().signal,
      })
      const text = r.content.map(b => (b.type === 'text' ? b.text : '')).join('')
      const reject = text.includes('REJECT')
      const asm = await ctx.systemPrompt.assemble()
      const has = asm.sections.some(s => s.name === 'kernel-dev-contract')
      writeFileSync(RESULT, JSON.stringify({
        stage: 'done', tool_pipeline: reject ? 'REJECT-seen' : 'unexpected',
        contract_section: has, guard_head: text.slice(0, 260),
      }, null, 2))
      process.exit(reject && has ? 0 : 1)
    } catch (e) {
      writeFileSync(RESULT, JSON.stringify({ stage: 'error', message: String(e && e.message) }))
      process.exit(1)
    }
  })()
}
