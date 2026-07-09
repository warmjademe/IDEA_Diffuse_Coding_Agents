#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一的 OpenAI 兼容 chat 封装(免依赖,纯 urllib)。支持官方 DeepSeek 与 NAS 本地 Qwen vLLM。
含:重试、超时、token/成本计数、推理模型(reasoning_content)处理。"""
import json, os, time, threading, urllib.request

PROVIDERS = {
    "deepseek":        {"base_url": "https://api.deepseek.com", "key_env": "DEEPSEEK_API_KEY"},
    "qwen_coder_nas":  {"base_url": "http://127.0.0.1:8000/v1", "key_env": None},
    "shqbb":           {"base_url": "https://YOUR_OPENAI_COMPATIBLE_ENDPOINT_A/v1", "key_env": "SHQBB_API_KEY"},  # GPT-5.5 强模型(跨模型验证);key 存 ~/.diffuse_env
    "aimoniker":       {"base_url": "https://YOUR_OPENAI_COMPATIBLE_ENDPOINT_B/v1", "key_env": "AIMONIKER_API_KEY"},  # Claude Sonnet 5 强生成器(RQ6 异构臂);key 存 ~/.diffuse_env
    "easymax_gemini":  {"base_url": "https://YOUR_OPENAI_COMPATIBLE_ENDPOINT_C/v1", "key_env": "EASYMAX_GEMINI_KEY"},  # Gemini 2.5 Flash-Lite 强生成器(RQ6 第四家 Google 臂);key 存 ~/.diffuse_env(与 GPT 的 easymax key 不同)
}

# DeepSeek 定价(元/百万 token,按需改;仅用于估算)
_PRICE = {"deepseek-v4-pro": {"in": 4.0, "out": 16.0},
          "deepseek-v4-flash": {"in": 1.0, "out": 4.0}}

_lock = threading.Lock()
_cost = {"calls": 0, "errors": 0, "prompt_tokens": 0, "completion_tokens": 0,
         "reasoning_tokens": 0, "yuan_est": 0.0}

def _key(provider):
    ke = PROVIDERS[provider].get("key_env")
    if not ke:
        return "EMPTY"
    k = os.environ.get(ke)
    if not k:
        raise RuntimeError(f"缺少环境变量 {ke}(在 NAS 上 `source ~/.diffuse_env`)")
    return k

def chat(provider, model, messages, max_tokens=1024, temperature=0.2, timeout=180, retries=4):
    base = PROVIDERS[provider]["base_url"].rstrip("/")
    url = base + "/chat/completions"
    payload = {"model": model, "messages": messages,
               "max_tokens": max_tokens, "temperature": temperature}
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json",
               "Authorization": "Bearer " + _key(provider),
               "User-Agent": "curl/8.5.0"}  # aimoniker 走 Cloudflare,默认 Python-urllib UA 触发 1010 封禁
    last = None
    for att in range(retries):
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as r:
                d = json.loads(r.read().decode("utf-8"))
            msg = d["choices"][0]["message"]
            content = (msg.get("content") or "").strip()
            u = d.get("usage", {}) or {}
            ctd = u.get("completion_tokens_details") or {}
            rt = ctd.get("reasoning_tokens", 0) if isinstance(ctd, dict) else 0
            with _lock:
                _cost["calls"] += 1
                _cost["prompt_tokens"] += u.get("prompt_tokens", 0)
                _cost["completion_tokens"] += u.get("completion_tokens", 0)
                _cost["reasoning_tokens"] += rt
                if model in _PRICE:
                    _cost["yuan_est"] += (u.get("prompt_tokens", 0) * _PRICE[model]["in"]
                                          + u.get("completion_tokens", 0) * _PRICE[model]["out"]) / 1e6
            return {"content": content, "reasoning": msg.get("reasoning_content"), "usage": u}
        except Exception as e:
            last = e
            time.sleep(2 * (att + 1))
    with _lock:
        _cost["errors"] += 1
    return {"content": "", "reasoning": None, "usage": {}, "error": str(last)}

def cost_report():
    with _lock:
        return dict(_cost)
