<div align="center">

# Vowrite（述写）

> **Speak to Write**

**按住快捷键口述，AI 实时转写并润色，文字直接输出到当前光标位置，无需切换窗口。**

[![Python](https://img.shields.io/badge/python-3.12%2B-blue)]()
[![Stage](https://img.shields.io/badge/stage-P0%20prototype-orange)]()
[![Platform](https://img.shields.io/badge/platform-Windows-blue)]()

</div>

---

Vowrite 是一款全局语音输入工具。按住快捷键口述，AI 将你的语音实时转为文字并自动润色，文字直接输出到当前光标位置，无需切换窗口。解放双手，让口述即书写。

> Vowrite is a global voice input tool. Hold the hotkey and speak, AI transcribes and polishes your speech in real time, text lands directly at your cursor anywhere. Speak to write.

## 工作原理

```
按住右Ctrl ──► 录音 16kHz ──► ASR 转写 ──► LLM 处理 ──► 剪贴板+模拟粘贴 ──► 光标处
 (keyboard)     (sounddevice)  (faster-whisper   (polish=转写润色/       (pyperclip +
                                / 云端 API 可选)    chat=口述问答,        pyautogui)
                                                   失败降级原文本)
```

### 两种输出模式（`--mode` 或 `config.toml [llm] mode` 切换）

| 模式 | 做什么 | 适用场景 |
|---|---|---|
| `polish`（默认） | **把你说的话打成干净文字**：只清口水词/补标点/纠错字，原意原句保留 | 替代打字：对 Cursor/Claude Code 口述 prompt、写 commit message、博客周报 |
| `chat` | 口述一个问题，**AI 答案直接落光标** | 文档里随口问知识、快速取代码片段 |

* **触发**：按住 `右Ctrl` 开口说话，松开即完成
* **转写**：本地 faster-whisper（CUDA 优先，自动回退 CPU），或切换任意 OpenAI 兼容转写 API
* **注入**：写入剪贴板 + 模拟 `Ctrl+V`，任何应用的输入框都能落位

## 快速开始

```powershell
# 1) 克隆并进入项目
cd D:\workspace\sogrey\Vowrite

# 2) 创建虚拟环境（Python 3.12+）
python -m venv .venv

# 3) 安装依赖（国内推荐清华源）
.venv\Scripts\pip.exe install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 4) 轻量自检（依赖/配置/麦克风/剪贴板/LLM）
.venv\Scripts\python.exe p0\vowrite.py --self-test

# 5) 完整自检（首次会下载 ASR 模型，约 460MB，走 hf-mirror）
.venv\Scripts\python.exe p0\vowrite.py --self-test --full
```

# 6) 启动方式（二选一）

## GUI 常驻（推荐）

**双击 `p0\start_vowrite.bat`** —— 无窗口常驻系统托盘，日常使用零命令行：

* **托盘右键菜单**：监听开/关 · 输出模式一键切换（polish/chat）· **LLM 服务一键启停**（自动拉起 llama-server 并探测就绪，只管理自己拉起的进程，外部服务只报状态不动）· 打开设置 · 重启引擎 · 运行自检 · 退出
* **托盘图标状态色**：灰=待机 / 红=录音中 / 蓝=处理中 / 黄=引擎加载中 / 深红=加载失败
* **设置窗**：全部配置可视化编辑，保存即热更新（触发键/模式/润色强度/注入项免重启）；ASR 模型/设备变更点「保存并重启引擎」
* **开机自启**：设置窗内勾选即写入当前用户注册表 Run 键，取消勾选即移除
* **单实例锁**：重复双击不会多开，日志在 `.temp/vowrite-gui.log`（异常崩溃写入 `.temp/vowrite-gui-crash.log`）
* **排查**：托盘无图标时先点任务栏 `^` 折叠箭头找（Win11 默认折叠新图标，可在任务栏设置中设为常驻）；仍异常用 `p0\start_vowrite_debug.bat` 启动可直看报错

> llama-server 托管需在 `[llm.server]` 段配置 exe 与模型路径（本机 `config.toml` 已配好）；启用后 Vowrite 启动时若端口无服务会自动拉起，退出时一并停止，你手动起的服务不受影响。

## CLI 常驻（调试用）

```powershell
.venv\Scripts\python.exe p0\vowrite.py
```

启动后：**按住右 Ctrl 说话 → 松开 → 文字自动落在光标处**。`Ctrl+C` 退出。

> LLM 处理默认指向本地 llama.cpp server（`http://127.0.0.1:8090/v1`），先启动它效果最佳：
> ```
> llama-server.exe -m Qwen2.5-7B-Instruct-Q4_K_M.gguf -ngl 99 --port 8090
> ```
> 没启动也不影响使用——处理会自动降级为输出原始转写。也可在 `config.toml` 指向云端 API（DeepSeek / Qwen 等）。
>
> 模型建议：polish 转写清理需要严格的指令遵循，推荐 **instruct 指令模型**（如官方 Qwen2.5-7B-Instruct）；角色扮演/对话微调模型可能不守规则、把转写内容当对话来回答。

## 常用命令

|命令|用途|
|-|-|
|`python p0\vowrite.py`|常驻监听（主用法，polish 模式替代打字）|
|`python p0\vowrite.py --mode chat`|问答模式：说问题，AI 答案落光标|
|`python p0\vowrite.py --message "嗯那个我在想等下要不要吃饭"`|跳过录音，直接测润色+注入|
|`python p0\vowrite.py --no-inject`|只打印/写剪贴板，不模拟粘贴（安全模式）|
|`python p0\vowrite.py --style heavy`|临时用书面化强度润色|
|`python p0\vowrite.py --self-test [--full]`|自检 / 完整链路自检|

## 配置

首次运行会自动把 `config.example.toml` 复制为 `config.toml`，按需修改：

|配置段|关键项|说明|
|-|-|-|
|`[trigger]`|`key`|触发键（keyboard 库按键名）：`right ctrl` / `f9` / `right shift`…|
|`[audio]`|`min_duration` / `max_duration`|误触过滤 / 最长录音保护（秒）|
|`[asr]`|`engine`|`local`（faster-whisper）或 `api`（OpenAI 兼容转写）|
||`model`|`tiny` / `base` / `small` / `medium` / `large-v3-turbo`|
||`device`|`auto`（CUDA→CPU 回退）/ `cuda` / `cpu`|
||`hf_endpoint`|模型下载镜像，默认 `https://hf-mirror.com`（国内网络）|
|`[llm]`|`mode`|输出模式：`polish`（转写润色，默认）/ `chat`（口述问答落光标）|
||`base_url` / `model` / `style`|OpenAI 兼容接口；`style` 为 `light` / `heavy`|
|`[inject]`|`enabled` / `pause_ms`|注入开关；写剪贴板→粘贴的间隔|

## 已知边界

* **模型升级（推荐）**：默认 `small` 起步；中文质量要求高时切 `large-v3-turbo`（约 1.6GB，809M 参数，RTF≈0.2）。国内下载**优先 ModelScope**（实测 ~49MB/s，hf-mirror 大文件仅 ~360KB/s）：
  ```powershell
  # ModelScope 下载后把 config.toml 的 model 指向该目录即可
  curl.exe -L -o model.bin https://modelscope.cn/models/pengzhendong/faster-whisper-large-v3-turbo/resolve/master/model.bin
  ```
  完整文件清单：`model.bin`（ModelScope）+ `config.json` / `preprocessor_config.json` / `tokenizer.json` / `vocabulary.json`（hf-mirror 补齐，均为小文件）；**`vocabulary.json` 必需**，缺失会报 `Cannot load the vocabulary`
* **显存共存**：GPU 同时跑 LLM server（llama.cpp）与 whisper 时需合计规划；显存不足时 `device=cpu, compute_type=int8`（启动转换 ~34s，转写 RTF≈0.2，短句 1s 内）
* **ASR 幻觉抑制**：whisper 对超短音频（如只说「你好」）可能吐出训练分布里的高频长句，已按置信度（`avg_logprob < -1.0`）丢弃幻觉段；配合 LLM 侧短输入透传（≤6 字无口水词不调 LLM）与 polish 输出守卫（只删不加原则，异常膨胀/示例吸附输出自动降级原文）三重防线
* **管理员窗口**：向以管理员权限运行的应用注入时，需 Vowrite 同样以管理员启动（Windows UIPI 限制）
* **杀软误报**：全局键盘钩子（keyboard 库）可能被安全软件关注，属正常行为
* **剪贴板**：注入会覆盖当前剪贴板内容

## 路线图

|阶段|内容|状态|
|-|-|-|
|P0|Python CLI 原型（本目录）|🚧 进行中|
|P1|Tauri 2 桌面版：悬浮指示器 / 历史 / 设置|待启动|
|P2|双引擎回退 / 个人词库 / 修正学习|待启动|
|P3|流式实时预览 / 选中改写|待启动|

完整需求见 [docs/PRD.md](docs/PRD.md)。

> AI生成
