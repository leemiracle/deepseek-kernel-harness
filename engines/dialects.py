#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dialects.py — 引擎方言注册表（手册 09 章：模型方言适配）

设计原则：
  1. 宿主只说 OpenAI 兼容协议一种话（主流引擎全部提供兼容端点）
  2. 方言差异收敛为三类：thinking 开关 kwargs / reasoner 特殊行为 / 备注
  3. 按 base_url 关键字自动识别引擎，也可 KH_ENGINE 显式指定
  4. reasoning_content 一律不回灌（宿主 run() 只 append content+tool_calls，
     天然跨家安全——Preserved Thinking 铁律的协议无关实现）

实测标记：✅ = 本机 e2e 实证；⚠ = 官方文档端点、未实测（接 key 后用 engine_probe.py 验）
"""
import os

# env 覆盖链（老变量名保留兼容，新名 KH_* 优先）
def api_key():
    return os.environ.get("KH_API_KEY") or os.environ.get("DEEPSEEK_API_KEY", "")


def base_url():
    return (os.environ.get("KH_BASE_URL") or os.environ.get("DEEPSEEK_BASE_URL")
            or "https://api.deepseek.com")


DIALECTS = {
    "zhipu": {
        "match": ("bigmodel",),
        "default_base": "https://open.bigmodel.cn/api/coding/paas/v4",
        "loop_kwargs": {"extra_body": {"thinking": {"type": "disabled"}}},
        "thinker_kwargs": {},          # 保留默认深度思考（glm-5.3 返 reasoning_content，宿主不回灌）
        "loop_default": "glm-5.3",
        "thinker_default": "glm-5.3",
        "tested": True,
        "note": "coding 端点 glm-5.3/5-Turbo/4.7 实测通；loop 必须 thinking:disabled 否则拖慢工具循环",
    },
    "deepseek": {
        "match": ("deepseek",),
        "default_base": "https://api.deepseek.com",
        "loop_kwargs": {},
        "thinker_kwargs": {},          # reasoner 不接受 thinking 类参数（方言表铁律）
        "loop_default": "deepseek-chat",
        "thinker_default": "deepseek-reasoner",
        "tested": False,
        "note": "reasoner 返 reasoning_content；chat 无思考模式",
    },
    "dashscope": {
        "match": ("dashscope",),
        "default_base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "loop_kwargs": {"extra_body": {"enable_thinking": False}},
        "thinker_kwargs": {"extra_body": {"enable_thinking": True}},
        "loop_default": "qwen3-coder-plus",
        "thinker_default": "qwen3-max",
        "tested": False,
        "note": "qwen3 系 enable_thinking 开关（compatible-mode 端点）",
    },
    "moonshot": {
        "match": ("moonshot",),
        "default_base": "https://api.moonshot.cn/v1",
        "loop_kwargs": {},
        "thinker_kwargs": {},
        "loop_default": "kimi-k2-0905-preview",
        "thinker_default": "kimi-k2-0905-preview",
        "tested": False,
        "note": "原生 OpenAI 风格；k2 无独立思考开关",
    },
    "openai": {
        "match": ("api.openai.com",),
        "default_base": "https://api.openai.com/v1",
        "loop_kwargs": {},
        "thinker_kwargs": {},
        "loop_default": "gpt-5-mini",
        "thinker_default": "gpt-5",
        "tested": False,
        "note": "o/g 系推理模型靠模型名选择，无思考开关参数",
    },
    "anthropic": {
        "match": ("api.anthropic.com",),
        "default_base": "https://api.anthropic.com/v1",
        "loop_kwargs": {},
        "thinker_kwargs": {},
        "loop_default": "claude-sonnet-4-5",
        "thinker_default": "claude-opus-4-5",
        "tested": False,
        "note": "⚠ 官方 OpenAI 兼容层；扩展思考经兼容层不透传，用模型档位区分",
    },
    "gemini": {
        "match": ("generativelanguage.googleapis.com",),
        "default_base": "https://generativelanguage.googleapis.com/v1beta/openai",
        "loop_kwargs": {},
        "thinker_kwargs": {},
        "loop_default": "gemini-2.5-flash",
        "thinker_default": "gemini-2.5-pro",
        "tested": False,
        "note": "⚠ OpenAI 兼容端点；thinking 经 reasoning_effort 透传，默认不动",
    },
    "local": {
        "match": ("localhost", "127.0.0.1", "0.0.0.0"),
        "default_base": "http://localhost:8000/v1",
        "loop_kwargs": {},
        "thinker_kwargs": {},
        "loop_default": "qwen3-coder:30b",
        "thinker_default": "qwen3-coder:30b",
        "tested": False,
        "note": "vLLM/Ollama/LMStudio 全是 OpenAI 兼容；api_key 随便填非空即可",
    },
}

_DEFAULT = {"loop_kwargs": {}, "thinker_kwargs": {}, "tested": False, "note": "未知引擎：按裸 OpenAI 兼容处理"}


def resolve_dialect(base=None):
    """base_url（或 KH_ENGINE 显式名）→ 方言 dict。未命中返回保守默认。"""
    explicit = os.environ.get("KH_ENGINE", "")
    if explicit:
        d = dict(DIALECTS.get(explicit, _DEFAULT))
        d["name"] = explicit
        return d
    b = (base or base_url()).lower()
    for name, spec in DIALECTS.items():
        if any(k in b for k in spec["match"]):
            d = dict(spec)
            d["name"] = name
            return d
    d = dict(_DEFAULT)
    d["name"] = "generic"
    return d


def loop_model():
    return os.environ.get("KH_LOOP_MODEL") or resolve_dialect()["loop_default"]


def thinker_model():
    return os.environ.get("KH_THINKER_MODEL") or resolve_dialect()["thinker_default"]
