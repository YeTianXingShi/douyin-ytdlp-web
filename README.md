# Douyin yt-dlp Web

基于本地 yt-dlp 的抖音单视频和用户主页作品管理 Web 应用。

## 功能

- 单视频下载和抖音用户主页作品枚举
- 主页刷新结果持久化，支持人工选择后应用
- SQLite 保存主页、作品、任务、失败和跳过状态
- 串行下载、断点续跑、失败重试和安全取消
- SSE 实时显示刷新和下载进度
- 下载文件按“标题_发布日期_aweme_id”命名
- 管理后台查看、停止和删除任务记录
- Cookie 只从服务器挂载的 Netscape Cookie 文件读取

## 依赖

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- Node.js/npm
- 本地 yt-dlp 源码目录：`yt-dlp/`

Python 后端必须通过 uv 隔离环境运行，不使用系统 Python 或全局 pip。

## 快速开始

准备本地依赖目录：

```bash
git clone https://github.com/yt-dlp/yt-dlp.git yt-dlp
git clone https://github.com/Evil0ctal/Douyin_TikTok_Download_API.git Douyin_TikTok_Download_API
```

配置并启动：

```bash
cp .env.example .env
# 编辑 .env，至少设置 ADMIN_TOKEN 和 DOUYIN_COOKIE_FILE
./start.sh
```

访问前端：<http://127.0.0.1:5173>

服务脚本：

```bash
./start.sh       # 使用 uv 同步后端环境并启动前后端
./stop.sh        # 停止前后端
./restart.sh     # 重启前后端
```

生产模式先执行 `cd frontend && npm run build`，再运行 `FRONTEND_MODE=preview ./start.sh`。远程访问必须使用 HTTPS 反向代理，并设置管理员 Bearer Token。

## 配置

`.env.example` 中的相对路径以项目根目录为基准：

```dotenv
ADMIN_TOKEN=change-me
DOUYIN_COOKIE_FILE=./cookie/douyin-cookies.txt
DOUYIN_USER_AGENT="与导出 Cookie 的浏览器一致的 User-Agent"
DOWNLOAD_ROOT=./downloads
STATE_DIR=./state
DATABASE_FILE=./state/jobs.sqlite3
DOWNLOAD_ARCHIVE=./state/download-archive.txt
```

Cookie 文件不能提交到 Git，也不能通过 API、URL 或前端表单传入。包含空格、括号或分号的 dotenv 值必须加双引号。

## 使用流程

1. 在“主页作品管理”中添加抖音用户主页。
2. 点击“更新主页”，等待作品发现完成。
3. 在差异列表中勾选需要管理的作品并确认更新。
4. 在作品清单中选择作品下载，失败作品可单独或批量重试。
5. 在“后台任务管理”中查看刷新/下载任务；运行中的任务可停止，终态任务可删除记录，视频文件不会被删除。

所有 API（`/healthz` 除外）都需要：

```http
Authorization: Bearer <ADMIN_TOKEN>
```

## 参考项目

本项目没有复制参考项目中的硬编码 Cookie、Token 或部署配置，仅在许可证允许范围内参考其接口参数、主页枚举和 A-Bogus 适配思路：

- yt-dlp：<https://github.com/yt-dlp/yt-dlp>
- Douyin_TikTok_Download_API：<https://github.com/Evil0ctal/Douyin_TikTok_Download_API>

yt-dlp 负责视频详情提取和下载；本项目独立的主页服务负责抖音用户作品分页和发现结果管理。

## 验证与运行数据

本项目不包含自动化测试用例，按 `agent.md` 中的手工验收标准验证。下载目录、SQLite、归档文件、Cookie 和日志均为运行时数据，已加入 Git 忽略规则。
