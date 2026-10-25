# Research Council

**把独立回答、交叉评审、经人类确认的实验执行，放在同一个本地研究工作台里。**

[English](README.md) · [日本語](README.ja.md) · [架构说明](docs/ARCHITECTURE.md) · [开发记录](docs/DEVELOPMENT.md) · [macOS 构建说明](desktop/README.md)

![Research Council 研究工作台](docs/images/research-workspace.png)

截图使用演示文字和独立测试数据，不含个人研究记录，也不代表真实模型效果。

## 为什么做这个项目

同时用几个 AI 助手做研究时，回答、争议、计划和实验结果容易散落在不同聊天中。这个应用把它们整理为可追踪的过程：先独立回答，再顺序交叉评审，由人确认计划和验收标准，最后交给执行者与独立核验者完成有限范围的实验。

模型达成一致只表示一致；是否通过验收仍取决于证据。

## 主要功能

- **独立回答与顺序互评**：区分独立判断和已经公开给其他成员的观点。
- **单独的实验任务入口**：执行前查看完整计划、分歧和验收标准，普通提问不会启动实验。
- **持久化阶段记录**：执行、检查点复核、继续执行、最终独立核验；保留失败现场和待决事项。
- **清楚的等待状态**：需要用户决定时显示等待提示，真正的调用错误继续显示错误。
- **研究资料与笔记**：本地来源、引用卡片、图片、聚焦子聊天和可筛选的研究笔记。
- **可观察的进度**：工具活动、耗时、权限请求，以及客户端能提供的额度和上下文信息。
- **桌面与浏览器界面**：Swift 原生 macOS 窗口；中、日、英三语；浅色、深色、跟随系统。

![实验任务与阶段核验记录](docs/images/experiment-tasks.png)

图中的完成状态来自测试场景，不是科学实验结论。

## 技术实现

前端采用原生 JavaScript、HTML 和 CSS；Python 服务负责讨论编排、CLI 会话、任务记录与本地存储；macOS 外壳使用 Swift、AppKit 和 WKWebView。

Claude、Codex 使用已安装并登录的 CLI；Gemini 是基于可选 Antigravity CLI 的研究集成；Grok 目前只有演示配置。模型选项不等于账号权限证明。

工作目录不是操作系统沙箱，实际文件访问取决于客户端权限。数据在本地保存，但 Live CLI 会向对应模型服务发送本次输入和选定材料。

## 本地运行

需要 Python 3.11 或更高版本；浏览器前端没有生产 npm 依赖。

```sh
git clone https://github.com/nicoyoung1101/research-council.git
cd research-council
python3 bridge.py
```

打开 **http://127.0.0.1:8765/index.html**。可以先体验 Demo 模式；真实调用需要自行安装并登录客户端，在 **Agents & Models** 中明确切换为 **Live CLI**。

macOS 上安装 Xcode 命令行工具后可以构建：

```sh
python3 desktop/build_app.py --output 'dist/Research Council.app'
open 'dist/Research Council.app'
```

当前公开源码基于 **v0.11 / Build 48**，构建结果使用本机 Python 和临时签名，暂不提供经过公证的独立安装包。

## 验证与公开范围

Build 48 在本地通过 **320 项 Python 测试、33 组浏览器场景测试**。浏览器测试使用替代执行器，不调用真实模型。运行方式和环境要求见 [English README](README.md#validation)。

公开仓库包含源码、测试和文档，不含个人讨论、任务数据、凭证、私人工作区或已安装应用。反馈默认只保存在本地。

第三方组件的授权见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。应用原创代码尚未指定项目级许可证。

作者：[Nico Young](https://github.com/nicoyoung1101)。
