# Scoped Memory

**中文** · [Português](README.pt-BR.md) · [English](README.en.md)

做项目时，真正麻烦的往往不是忘了一句聊天内容，而是忘了当时为什么这样决定、哪些办法已经试过、下一步该从哪里接着做。

Scoped Memory 是一个可供 Codex 和 DeepSeek Harness 使用的本地工程记忆工具。它把值得长期保留的内容按照“使用者、项目、当前任务”分开放置，并用脚本把工程转换成紧凑的结构化事实。换一个会话或代理继续工作时，可以直接读取已有结论和工程关系，不必重新翻完整聊天记录，也不必先把代码改写成自然语言摘要。

## 为什么不让大模型每次重新读工程

一般的工作方式是：大模型打开很多文件，把代码、日志和测试重新解释成一段自然语言，然后再依靠这段解释继续工作。项目一大，这个过程会反复消耗上下文；压缩以后还可能丢失文件路径、符号名称、依赖方向和证据位置。

Scoped Memory 把工作分成两层：

1. **工程脚本负责整理事实。** 脚本直接扫描文件树，读取语言结构和项目清单，记录文件指纹、顶层符号、导入关系、测试位置、依赖名称和 Git 状态。这个过程可重复、可比较，不需要调用大模型。
2. **大模型负责判断和工作。** Codex 或 DeepSeek Harness 先查询一小段与当前任务有关的工程事实，再按需打开少数源码文件。它不用先把整个工程翻译成文章，最后向人交付结果时才组织自然语言。

实际流程是：

```text
代码、测试、配置和 Git 状态
        ↓
确定性工程扫描脚本
        ↓
按项目隔离的 EIR/1 工程索引
        ↓
按问题和长度预算选出相关事实
        ↓
Codex / DeepSeek Harness 继续分析、修改和验证
        ↓
最终结果才转换成人类自然语言
```

例如，模型不需要先阅读一段“认证模块依赖数据库模块”的说明。它可以直接得到：认证文件包含哪些符号、导入了哪个模块、对应测试在哪里、这些文件当前是否发生变化。需要确认实现细节时，它再打开准确的文件，而不是重新遍历整个仓库。

这样做带来的变化：

- 减少重复读取和重复总结，给实际推理、编码和测试留下更多上下文。
- 文件、符号、依赖和版本都有稳定标识，不依赖某次聊天的措辞。
- Codex 与 DeepSeek Harness 可以读取同一份工程地图，不需要分别建立两套自然语言摘要。
- 工程发生变化后重新运行脚本，就能用文件指纹和 Git 状态识别新旧差异。
- 索引只是导航和记忆，不替代源码、测试或运行结果；需要下结论时仍以真实工程证据为准。

第一版有意保持简单和可检查。它能提取 Python、JavaScript、TypeScript 等常见源码的顶层符号与导入关系，也能识别测试和常见依赖清单；它不会假装已经理解所有业务含义，也不会凭索引自动证明调用链正确。更深的语义分析、增量差异和语言服务器接入可以在后续版本继续扩展。

## 它适合记住什么

- 长期有效的工作习惯，例如代码风格和交付偏好。
- 只属于当前项目的架构决定、限制条件和已经验证的事实。
- 当前任务做到哪里、还有什么没完成、哪些方法已经失败。

它不应该保存密码、密钥、个人资料、完整聊天记录或大段命令输出。这里保存的是帮助继续工作的摘要，不是另一个聊天档案库。

## 不同项目不会混在一起

每个项目都有独立身份。默认情况下，一个项目看不到另一个项目的记忆。只有使用者明确指定要继承哪个项目时，跨项目内容才会被读取。

同一个 Git 仓库的工作树共享项目身份，因此在不同工作树之间切换不会失忆。普通复制或重新克隆的仓库不会自动继承原项目记忆，避免把不相关的工程误认成同一个项目。

## 记忆怎样保存

所有内容默认留在本机，不需要云端服务，也不需要额外密钥。记录先进入 SQLite 数据库，同时生成一份便于检查和迁移的 JSONL 审计日志。

旧记录不会被偷偷改写。更新一条结论时，系统会追加一条新记录并注明它取代了哪一条；忘记某项内容时，也会追加一条删除标记。这样可以追溯发生过什么，也可以检查日志是否完整。

## 在 Codex 中怎样工作

插件会在任务开始、恢复以及上下文压缩后，自动取回当前项目最相关的一小段记忆。内容有严格的长度限制，不会把整个历史重新塞回会话。

也可以通过命令行或 MCP 工具主动保存决定、建立任务检查点、查找记录或忘记某个主题。读取类工具不会改动数据；写入和忘记操作有明确的权限标记。

## 工程中间层 EIR/1

`memory_ingest_project` 使用确定性脚本扫描工程，生成 `EIR/1`：文件指纹、语言、符号、导入关系、测试角色、依赖清单和 Git 状态。它不调用大模型，不保存源码正文，并跳过密钥、环境变量文件、二进制文件和超大文件。

`memory_engineering_context` 再按查询和 token 预算返回一小段紧凑 JSON。大模型直接消费这些符号和关系；只有最终交付给人时才需要整理成自然语言。

```bash
scripts/scoped-memory --home /tmp/scoped-memory-demo ingest .
scripts/scoped-memory --home /tmp/scoped-memory-demo engineering-context . --query memory --token-budget 1200
```

## DeepSeek Harness

DeepSeek Harness 原生支持本地 stdio MCP，因此可以直接使用同一个服务：

先使用隔离环境安装命令行服务：`pipx install git+https://github.com/lixuanfan567-png/scoped-memory.git`。

```yaml
- insert:
    - id: mcp-scoped-memory
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: scoped_memory
        transport: stdio
        command: scoped-memory-mcp
        cwd: !!js process.cwd()
        env:
          SCOPED_MEMORY_HOME: /absolute/path/to/scoped-memory-data
```

连接后，Harness 会看到 `mcp__scoped_memory__memory_ingest_project`、`mcp__scoped_memory__memory_engineering_context` 以及原有记忆工具。Codex 与 DeepSeek Harness 可以共享同一个本地记忆库，同时继续遵守项目隔离规则。

## 本地开发

需要 Python 3.10 或更高版本。运行测试：

```bash
python3 -m unittest discover -s tests -v
```

构建安装包：

```bash
python3 -m pip wheel . --no-deps
```

初始化一个项目并查看状态：

```bash
scripts/scoped-memory --home /tmp/scoped-memory-demo init .
scripts/scoped-memory --home /tmp/scoped-memory-demo status .
```

测试覆盖项目隔离、任务隔离、显式继承、Git 工作树、独立克隆、并发写入、更新与忘记、中文长度预算、EIR 工程提取、敏感文件排除、启动注入、MCP 调用和审计恢复。

## 当前状态

项目目前处于早期版本。核心存储、隔离规则、Codex 启动注入和 MCP 调用已经通过自动化测试及真实运行验证，但在稳定版发布前仍可能调整接口。

参与方式见 [CONTRIBUTING.md](CONTRIBUTING.md)，安全边界和漏洞报告方式见 [SECURITY.md](SECURITY.md)。

本项目使用 MIT 许可证，详见 [LICENSE](LICENSE)。
