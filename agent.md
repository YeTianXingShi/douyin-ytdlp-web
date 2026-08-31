# 项目协作规则

## 项目定位与规则同步

- 本项目是在 yt-dlp 基础上开发的 Web 界面；Web 界面层负责用户交互、任务编排和结果展示，PyPI 的 yt-dlp[default] 包负责视频信息提取与下载能力。
- 需要判断下载能力、支持的站点、URL 形式、Cookie 参数或格式选择时，先确认已安装的 yt-dlp 包和官方文档，再设计或修改 Web 界面行为；不要让 Web 界面承诺底层提取器未实现的能力。
- 每次代码变更完成后，都必须检查本次变更是否影响项目规则、支持范围、命令参数、隐私安全、目录约定或用户验证方式，并同步更新本文件 `agent.md`。
- 规则更新应与代码变更保持在同一工作范围内，使用简洁、可执行的说明；如果没有新增或变化的规则，也要在交付说明中明确检查过规则同步要求。
- 本项目 GitHub Release、版本同步和 GHCR 发布流程遵循仓库级 skill `.agents/skills/douyin-github-release/SKILL.md`；发布步骤和安全边界变更时必须同步更新该 skill。

## 当前实现约定

- Web 后端位于 `backend/`，使用 FastAPI；前端位于 `frontend/`，使用 React + Vite。
- 抖音用户主页列表由 `backend/app/profile_service.py` 独立枚举，视频详情和下载由 `backend/app/ytdlp_service.py` 调用本地 yt-dlp Python API 完成；不要把主页分页逻辑硬塞进上游 `DouyinIE`。
- 任务状态由 SQLite 保存，并由单个串行 worker 执行；长任务必须通过任务状态接口和 SSE/状态流反馈，不要在 HTTP 请求线程中同步阻塞整批下载。
- 远程部署使用服务器挂载的 Netscape/Mozilla Cookie 文件（`DOUYIN_COOKIE_FILE`）；API 请求和前端表单不得接收或回显原始 Cookie。Docker Secret 可能以只读方式挂载，服务启动时必须复制到容器 `/tmp` 下权限为 `0600` 的临时 Cookie 文件供 yt-dlp 使用，服务停止时删除临时副本；不得尝试回写 `/run/secrets`，也不得把临时副本持久化到 state 或下载目录。
- `docker-compose.yml` 必须是可独立使用的部署配置，不要求项目 `.env` 文件；应用环境变量和 Cookie 文件路径直接写在 Compose 文件中，敏感占位值只能由部署者在本地替换，不能提交真实凭据。镜像必须固定为当前已发布的 `ghcr.io/yetianxingshi/douyin-ytdlp-web:v<VERSION>` 标签，发布新版本时同步更新 Compose 和文档中的标签，不使用 `latest` 或运行时镜像变量覆盖。
- Python 依赖和运行环境统一由 `backend/pyproject.toml` 与 `uv` 管理；必须使用 `uv sync --project backend` 创建或更新 `backend/.venv`，使用 `uv run --project backend` 运行服务，禁止依赖系统 Python 或全局 pip 环境；不要恢复独立的 pip `requirements.txt` 作为安装入口。锁定文件 `backend/uv.lock` 如已生成应纳入版本控制。
- 本地服务由根目录 `start.sh`、`stop.sh`、`restart.sh` 管理；三个脚本必须同时管理 FastAPI 后端和 React/Vite 前端。后端依赖使用 uv 隔离环境，前端依赖使用 `frontend/package-lock.json` 配合 npm 安装；PID、日志和 uv 缓存只写入 `state/`，脚本不得把 Cookie 或其他 secret 打印到终端或日志。`.env`（或 `ENV_FILE` 指定的文件）通过 uv 的 dotenv 解析器加载，不要用 shell `source` 解析配置。
- `.env` 中包含空格、括号或分号的值（尤其是浏览器 User-Agent）必须使用双引号；环境文件解析失败时不得假定配置已生效，应先验证实际读取到的绝对路径。
- `.env.example` 的路径配置默认使用相对项目根目录的写法（例如 `./downloads`、`./state/jobs.sqlite3`）；配置读取层必须把相对路径统一解析为项目根目录下的绝对路径，不得依赖当前工作目录。
- 前端默认使用 `FRONTEND_MODE=dev` 启动 Vite 开发服务器（5173 端口）；生产模式使用 `FRONTEND_MODE=preview`，且必须先生成 `frontend/dist`。需要远程暴露时显式设置 `FRONTEND_HOST`，不要默认把开发服务器暴露到公网。
- 用户主页管理以 SQLite 中的 `profiles`、`profile_refreshes`、`profile_refresh_items` 和 `profile_posts` 为准；刷新结果必须先持久化为待确认差异，只有管理员选中的作品才应用到当前清单。未选中的发现结果保留，远端消失作品标记 `remote_missing`，不删除记录或文件。
- 下载任务引用主页作品记录，作品状态、失败分类、脱敏错误、跳过原因、尝试次数和文件名必须逐项保存；失败项通过重试接口重新排队，图集和未知类型默认不重试。
- SQLite 查询结果使用 `sqlite3.Row` 时必须通过 `row["field"]` 或显式转换为 `dict` 后访问，不得直接调用 `row.get(...)`；下载 worker 的主页作品和任务项路径都要遵守这一点。
- 同一主页同时只能存在一个排队或枚举中的刷新任务；前端在刷新进行时必须禁用“更新主页”，后端也必须幂等返回已有刷新任务，避免刷新队列被重复点击堆积。刷新任务必须正确关联 `jobs.refresh_id`，服务重启时修复早期遗漏的关联。
- 主页刷新在全部分页完成前允许保持 `enumerating`，但必须持续同步 `profile_refreshes.status` 和 `discovered_count`，让 Web 页面能显示中间进度；服务恢复时应取消同一主页多余的重复刷新任务。
- 主页刷新支持 `all`、`week`、`month`、`quarter`、`half_year`、`year` 时间范围；范围必须持久化到刷新和任务记录，并在枚举分页时按作品发布时间过滤，达到截止日期后停止继续翻页。时间范围过滤不能把缺少发布时间的作品静默当作已过期；有限时间范围在发现和应用两个阶段都只更新范围内结果，不得把范围外的历史作品标记为 `remote_missing`，只有 `all` 刷新才执行全量远端消失判定。
- 添加主页时应先通过抖音用户信息接口尽力获取并保存作者昵称；主页刷新时使用作品接口返回的最新作者昵称覆盖旧名称。昵称不可用时才回退显示 `sec_user_id`，不得把主页 URL 作为名称。
- 刷新完成后前端应同步重新读取主页摘要，使新获取的作者昵称在当前页面立即生效。
- 已有 `pending_confirmation` 刷新结果时，重新打开主页或再次点击更新必须优先恢复该结果，不得再次请求抖音接口；待确认结果应用或明确放弃后才允许下一次刷新。403 错误需明确提示 Cookie、请求频率或风控可能性。
- 判断主页是否已有活动刷新时，必须同时检查刷新记录和关联任务的状态，不能只依据任务表中的旧 `queued`/`enumerating` 状态。
- 管理后台必须提供任务列表；进行中的任务只能请求安全取消，不能直接删除正在执行的任务。任务完成、失败、取消或待确认后才允许删除任务记录；删除任务记录不得删除已完成的视频文件。
- 后台任务删除属于已确认的管理员操作，不增加二次确认弹窗；主页管理记录删除仍保留确认提示。
- 删除带主页刷新的终态任务时，同时删除对应的待确认刷新快照，避免留下阻塞下一次更新的孤立记录；不删除主页作品记录或已完成视频文件。
- 任务管理列表的计数必须与 worker 的中间状态同步，主页枚举期间至少持续更新已发现数量。
- 下载完成文件使用 Jellyfin 目录规则 `DOWNLOAD_ROOT/profiles/<sec_user_id>/Season <年份>/SxxxxExxxx - <标题> [<aweme_id>].<ext>`，单视频使用 `DOWNLOAD_ROOT/single/<aweme_id>/`；标题变化只更新元数据，不自动重命名已经下载的文件。`DOWNLOAD_ROOT`、数据库和归档路径必须支持环境变量配置。
- Jellyfin 媒体目录使用 `DOWNLOAD_ROOT/profiles/<sec_user_id>/Season <年份>/`；博主目录只使用稳定的 `sec_user_id`，昵称变化不得触发目录重命名。视频首次应用时分配稳定的 Season/Episode 编号，后续刷新不得重新编号。
- 每个主页目录必须生成 `tvshow.nfo`，每个 Season 生成 `season.nfo`，每个已下载视频生成同名 Episode `.nfo` 和本地 `-thumb` 封面；单视频保存到 `DOWNLOAD_ROOT/single/<aweme_id>/` 并生成 `movie.nfo`。
- NFO 必须使用 UTF-8、XML 转义和原子替换；标题变化只更新 NFO，不改已经下载的媒体文件名。NFO 和数据库可以保存互动统计快照，但不得保存 `formats[].url`、临时视频直链、Cookie 或完整请求头。
- 前端展示受保护的视频、NFO 或封面文件时，不能把需要 Bearer Token 的文件接口直接放进 `<img src>` 或普通链接；必须使用带认证头的 `fetch` 获取内容（例如对象 URL），并继续让后端文件接口执行管理员鉴权。
- 文件接口应根据实际扩展名返回正确的 MIME 类型，确保前端通过认证下载的本地封面可以正常预览；未知类型才回退为 `application/octet-stream`。
- 互动统计刷新采用手动元数据任务，不在主页分页更新时默认逐条调用 yt-dlp 详情接口；元数据失败不能把视频下载状态改成失败，且必须保留可重试的错误分类。
- Jellyfin 媒体索引 schema 不提供旧数据库迁移；检测到旧 `jobs.sqlite3` 时必须明确提示备份并删除旧 state，不能静默把旧记录当成新结构使用。
- 下载文件、SQLite 状态、归档文件和 Cookie secret 都是运行时数据，必须保持在版本控制之外；参考仓库只提供算法和接口实现参考，不复制其中的硬编码 Cookie 配置。
- 下载完成判定只能接受实际视频媒体文件（如 `.mp4`、`.mkv`、`.webm`、`.mov`、`.m4v`、`.avi`、`.flv`、`.ts`），必须排除 `-thumb` 封面和 `.nfo`；不能因为文件名包含 aweme_id 就把封面误判为视频。数据库标记已下载但实际媒体缺失时，列表应显示缺失警告，管理员明确重新选择后才可清理对应归档记录并重试。
- 排查“任务完成但找不到文件”时，必须同时核对生效的 `DOWNLOAD_ROOT`、任务项状态、`profile_posts.media_file`/`download_file` 和磁盘实际文件类型；只有确认视频文件存在后才能报告下载成功。归档记录不能替代实际文件存在性校验。

## 范围与源码基准

- 本项目不包含 yt-dlp 源码；涉及 yt-dlp 行为、站点支持、命令行参数或提取器能力的判断，先查看 uv 环境中安装的 yt-dlp 包和官方文档，再下结论。
- 不得通过本地源码目录、Git submodule 或 CI checkout 引入 yt-dlp；依赖必须来自 `yt-dlp[default]` 的 PyPI 包并由 `backend/uv.lock` 锁定。
- 本项目不包含 `Douyin_TikTok_Download_API` 源码，也不得在 Docker 或 GitHub Actions 中 checkout、复制或挂载该仓库；其链接只能作为参考资料。
- A-Bogus 仅从 `backend/app/vendor/abogus.py` 加载；该第三方代码必须保留作者、来源和 GPLv3 许可证说明，不能重新改为运行时读取外部仓库。
- 不要仅凭记忆、旧版本经验或第三方文章声称某项能力存在。若已安装的 yt-dlp 包没有对应提取器或 URL 规则，应明确说明“不支持直接处理”，不要把推测写成结论。
- 本地已安装的 `yt-dlp` CLI 可用于辅助核验；CLI、PyPI 包和官方文档结论不一致时，分别说明版本和依据，不要混淆。
- yt-dlp 的 `extract_info(download=True)` 在下载归档命中等场景可能返回 `None`，`requested_formats` 也可能包含空项；调用方必须先做类型归一化，不能直接对不确定值调用 `.get()`。只要输出文件已成功落盘，就不能仅因缺少详情字典而把下载判定为失败；应保留已有主页发现元数据，并向用户显示可理解的元数据缺失提示。

## 测试与验证

- 不要编写、添加或修改测试用例；用户会自行验证。
- 未经用户明确要求，不要运行测试套件，也不要为了验证而新增测试文件、测试夹具或模拟数据。
- 如任务需要确认行为，可以进行不改变项目代码的命令行试运行、源码检查或输出文件检查，但应把这类操作称为核验，不要生成测试用例。

## 抖音 / Douyin 规则

- 以 uv 环境中实际安装的 yt-dlp 版本及其提取器实现为准。
- 当前 `DouyinIE` 只匹配 `https://www.douyin.com/video/<数字ID>` 形式的单视频 URL；不能因为视频元数据含有 `/user/...` 链接，就声称用户主页可以直接作为播放列表处理。
- 已安装包中的 `TikTokUserIE` 针对 `tiktok.com/@...`，不能当作抖音用户主页提取器使用。对 `https://www.douyin.com/user/...` 的“下载全部作品”支持，必须先确认存在明确的 Douyin 用户列表实现，否则应说明需要外部生成视频 URL 列表后再批量下载。
- 用户链接同时含有 `modal_id` 时，可将数字 `modal_id` 作为目标视频 ID，构造对应的 `/video/<modal_id>` URL；仍应使用 `--no-playlist` 避免误处理主页或其他关联内容。
- 抖音下载遇到登录、验证码、风控或 `Fresh cookies ... are needed` 时，说明 Cookie 可能是必需的；不要承诺所有公开视频都能无 Cookie 下载。

## Cookie 与隐私

- 优先建议 `--cookies-from-browser <browser>`，或让用户使用 `--cookies <Netscape-cookie-file>`；不要要求用户把 Cookie 内容粘贴到聊天中。
- Cookie、登录会话、浏览器数据库和下载的视频都视为敏感数据。不要打印 Cookie 值、提交到 Git、上传到远端、写入日志或放进示例配置。
- 若必须保存 Cookie 文件，应使用用户指定的安全路径和严格权限（例如 `chmod 600`），并确认其不在版本控制范围内。
- 需要读取浏览器 Cookie 或 macOS 钥匙串时，应先说明这是敏感读取操作；只读取完成任务所需的数据，不导出或展示完整 Cookie。
- 抖音视频请求可能绑定同一公网 IP、User-Agent、浏览器会话或 Cookie 新鲜度；失败时如实报告环境限制，不要绕过验证码或平台访问控制。

## 下载与批量操作

- URL（尤其含 `&` 的查询参数）必须整体加引号，避免 shell 将参数拆开。
- 目标是单个视频时使用 `--no-playlist`，并采用稳定的输出模板（至少包含视频 ID）以避免同名覆盖。
- 批量 URL 使用 `--batch-file`；长时间或重复任务使用 `--download-archive`，遇到单个失效条目时可使用 `--ignore-errors` 继续处理。
- 批量请求应设置合理的请求间隔，尊重抖音服务条款、版权和访问频率限制；不要把“全部”表述为绝对完整，除非已确认分页、权限、删除状态和风控均未造成遗漏。
- 不执行会覆盖、删除或清空用户文件的操作；下载前确认目标目录和文件范围。

## 修改纪律

- 只做用户要求的最小范围修改；本项目必须保持与 yt-dlp 和 Douyin_TikTok_Download_API 源码仓库解耦，不重新引入外部源码路径依赖。
- 不要把 Cookie、账号信息、临时下载产物、缓存或本机配置加入提交内容。
- 每次代码变更后同步检查并更新 `agent.md`；规则本身发生变化时，应把规则文件与代码变更一起交付。
- 修改后说明改动的文件、规则是否同步更新、未做的测试，以及用户需要自行验证的步骤。
