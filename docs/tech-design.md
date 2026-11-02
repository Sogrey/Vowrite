# Vowrite 技术方案（P0 / P0.5）

| 项 | 内容 |
|---|---|
| 文档版本 | v0.1 |
| 日期 | 2026-11-02 |
| 状态 | Active |
| 关联 | [PRD.md](./PRD.md) · [dev-plan.md](./dev-plan.md) |

---

## 1. 目标

锁定 P0 Python 实现的模块边界、数据流与失败策略，使 P0.5 硬化可验收，并为 P1（Tauri）迁移提供接口草图，避免实现漂移。

---

## 2. 运行时架构

```
┌──────────── GUI (vowrite_gui.py) ────────────┐
│  pystray 托盘 · tk 设置 · LlmServerManager   │
│  on_notify / 热更新 / 单实例锁 / 开机自启      │
└──────────────────┬───────────────────────────┘
                   │ import vowrite
┌──────────────────▼───────────────────────────┐
│                 vowrite 包                    │
│  app.Vowrite  状态机 + 音频队列 + 钩子         │
│       │                                      │
│       ├─ audio.Recorder                      │
│       ├─ asr.*Transcriber                    │
│       ├─ llm.Polisher                        │
│       ├─ inject.Injector                     │
│       └─ metrics.record_latency → .temp/     │
└──────────────────────────────────────────────┘
```

### 2.1 包结构（`p0/vowrite/`）

| 模块 | 职责 |
|---|---|
| `logutil` | 版本、日志、UTF-8 控制台 |
| `config` | TOML 加载与缺省；`SCRIPT_DIR` = `p0/` |
| `audio` | 16kHz 单声道录音 |
| `asr` | faster-whisper / API；幻觉抑制；CUDA→CPU |
| `llm` | polish / chat / raw；输出守卫；失败降级 |
| `inject` | 剪贴板 + Ctrl+V；可选恢复原剪贴板 |
| `metrics` | 分段延迟 JSONL（`.temp/latency.jsonl`） |
| `app` | 触发、队列、管线编排 |
| `selftest` | 依赖/设备/剪贴板/LLM/ASR 自检 |
| `__main__` | CLI |

入口：

- GUI：`p0/start_vowrite.bat` → `vowrite_gui.py`
- CLI：`python p0/run_vowrite.py` 或 `cd p0 && python -m vowrite`

---

## 3. 管线与状态

### 3.1 数据流

1. 按住触发键 → `Recorder.start`
2. 松开 / 超时 → 音频入队（短于 `min_duration` 丢弃）
3. 单 worker 顺序：`transcribe` → `polish` → `inject`
4. 写 `.temp/latency.jsonl`（asr / llm / inject / total）

### 3.2 状态（对外 `Vowrite.state`）

| 值 | 含义 |
|---|---|
| `IDLE` | 未录音且队列空闲 |
| `RECORDING` | 正在采集（最高优先展示） |
| `PROCESSING` | worker 忙或队列非空 |

**叠录（H08）**：`PROCESSING` 时仍可再次按住开始下一段；仅 `_phase==RECORDING` 时拒绝重入。多段按 FIFO 注入。

### 3.3 键盘钩子

- `keyboard.hook` 返回句柄，保存在 `_hook`
- `stop()` 调用 `keyboard.unhook(_hook)`，避免 `unhook_all` 误伤

---

## 4. 注入策略

1. （可选）备份剪贴板  
2. `pyperclip.copy(text)`  
3. `pause_ms` 后 `Ctrl+V`  
4. `restore_delay_ms` 后写回备份（`restore_clipboard=true`）  
5. 任一步失败：结果尽量留在剪贴板；GUI `on_notify` 提示手动粘贴  

**不做**（P0）：UI Automation 直插、焦点可编辑性硬检测（P1 可补）。

**UIPI**：管理员目标窗口需同级启动 Vowrite。

---

## 5. ASR / LLM 失败与质量

| 点 | 策略 |
|---|---|
| CUDA 不可用 | 初始化候选回退 CPU int8；推理失败再重建 CPU |
| ASR 幻觉 | logprob / no_speech / 指纹 / 语速 |
| 短音频延迟 | `<4s` → `beam_size=3`，否则 5 |
| LLM 超时/宕机 | 返回原转写 |
| polish 吸附示例 | 指纹 + 长度守卫 → 降级原文 |
| 超短 polish | ≤6 字且无口水词 → 透传不调 LLM |

---

## 6. 配置与热更新

- 文件：`p0/config.toml`（gitignore）；示例在仓库根 `config.example.toml`
- **热更新无需重启**：触发键、mode、style、timeout、inject.*、幻觉指纹  
- **需重启引擎**：ASR model / device / compute_type  
- GUI 托盘切 mode：写回 toml（H02）

---

## 7. 显存共存（本机参考）

环境假设：RTX 3060 Laptop 6GB + llama-server + whisper。

| 建议 | 说明 |
|---|---|
| LLM `-ngl` 与 whisper 合计规划 | 显存紧张时 ASR `device=cpu, compute_type=int8` |
| 默认 ASR `small` | 质量不够再上 `large-v3-turbo`（本地目录） |
| llama-server 由 GUI 托管 | 只管理自身拉起的进程；外部服务只读状态 |

---

## 8. 可观测性

| 产物 | 路径 |
|---|---|
| GUI 日志 | `.temp/vowrite-gui.log` |
| 崩溃 | `.temp/vowrite-gui-crash.log` |
| llama-server | `.temp/llama-server.log` |
| 延迟 JSONL | `.temp/latency.jsonl` |
| polish 回归明细 | `.temp/polish-regression-last.json` |

延迟字段：`ts, ok, mode, asr_s, llm_s, inject_s, total_s, audio_s`。

---

## 9. P1（Tauri）迁移草图

| 方案 | 说明 | 倾向 |
|---|---|---|
| A. Rust 重写管线 | cpal + whisper-rs + enigo；与 Python 行为对齐成本高 | P1 中后期 |
| B. 短期嵌入 Python | Tauri 调本包 CLI/本地 RPC；UI 先换壳 | **P1 起步推荐** |
| C. 仅 UI 用 Tauri，引擎保持本进程 | 托盘/指示器/设置迁 Tauri，通过 stdout JSON 或命名管道订状态 | 与 B 接近 |

**接口契约（引擎侧应保持稳定）**：

- 配置：TOML 段名与键（trigger/audio/asr/llm/inject）
- 状态事件：`idle|recording|processing` + 可选耗时
- 命令：start/stop listen、set mode、reload asr、inject test message

定稿前以 dogfood 延迟与注入矩阵为准，不提前锁死 A/B。

---

## 10. 非目标（本阶段）

- 流式 ASR 预览（P3）
- 个人词库 / 修正学习（P2）
- macOS / 账号体系（P4）

---

*随 P0.5/P1 实现滚动修订；重大决策在修订记录追加。*
