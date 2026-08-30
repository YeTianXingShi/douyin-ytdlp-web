---
name: douyin-github-release
description: "发布本项目的 GitHub Release 和 GHCR Docker 镜像；用于版本同步、发布前核验、Release 创建和镜像标签验证。"
---

# Douyin GitHub Release

用于 `/Users/xiangzhen/Temp/yt-dlp-web` 的版本发布。只处理本项目，不把本流程泛化到其他仓库。

## 发布前检查

- 以根目录 `VERSION` 作为唯一应用版本来源；Release tag 必须是 `v<VERSION>`。
- 同步检查 `backend/pyproject.toml`、`frontend/package.json` 和 `frontend/package-lock.json` 的版本号。后端版本变化后必须执行 `uv lock --project backend`，发布前使用 `uv sync --locked --project backend`。
- 不新增或运行测试用例；可以执行 Python 编译、前端生产构建、锁文件检查和导入核验。
- 核验 `import yt_dlp` 来自 uv 环境的 `site-packages`，并核验 `backend.app.vendor.abogus` 可以生成参数。项目不得依赖或 checkout 本地 yt-dlp、`Douyin_TikTok_Download_API` 或其他外部源码。
- 检查 `git diff --check` 和提交范围；Cookie、Token、数据库、下载文件、`.env` 和其他运行时数据不得进入提交。

## Compose 与镜像

- `docker-compose.yml` 必须是自包含配置，不使用 `${...}` 插值或项目 `.env`。镜像使用明确的已发布 tag（例如 `ghcr.io/yetianxingshi/douyin-ytdlp-web:v0.0.2`），不要把 `latest` 作为生产部署版本。
- Release workflow 只 checkout 当前仓库，构建 `linux/amd64`，并推送 `v<VERSION>`、`<VERSION>` 和 `latest` 三个 GHCR 标签。
- Docker 构建上下文不得包含两个外部源码目录；A-Bogus 只能从 `backend/app/vendor/abogus.py` 加载，许可证和作者归属见 `NOTICE.md`。

## 发布流程

1. 阅读 `CHANGELOG.md` 并补充当前版本说明；确认版本文件、Compose tag 和锁文件一致。
2. 执行必要的非测试核验，提交并推送 `main`。
3. 只有用户明确要求发布时才创建 Release：

   ```bash
   gh release create v<VERSION> --target main --title "v<VERSION>" --notes-file CHANGELOG.md
   ```

4. 等待 `.github/workflows/release.yml` 完成；失败时先读取失败步骤日志，修复后让 Release tag 指向修复提交再重跑。
5. 用 `gh release view` 和 `gh run view` 记录 Release/Actions URL。用 GHCR 匿名 token 请求支持 OCI index 的 manifest，确认三个 tag 返回 HTTP 200；不要输出 token。

## 安全边界

- 创建、删除或重建 Release/tag、推送 Git、发布 GHCR 都是外部状态变更，必须来自用户明确请求；不要因为普通代码修改自动发布。
- 不把真实管理员 Token、Cookie 或浏览器会话写入 skill、Compose、日志、Release notes 或提交。
- 发布完成后报告版本、提交、Release URL、Actions URL、镜像 tag 和未完成的验证项；没有 Docker daemon 时说明只完成 registry/API 验证。
