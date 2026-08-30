# 第三方代码与参考项目说明

## 内置 A-Bogus 算法

`backend/app/vendor/abogus.py` 来源于抖音 Web A-Bogus 参数生成实现，保留原始作者与 GPLv3 许可说明，并在文件头记录来源和修改目的。该模块已经复制到本项目中，运行时不依赖原始仓库。

原始来源：

- 原始作者项目：<https://github.com/JoeanAmier/TikTokDownloader>
- 参考项目：<https://github.com/Evil0ctal/Douyin_TikTok_Download_API>

发布包含该模块的版本时，应同时保留对应 GPLv3 许可和作者归属信息。

## 参考项目（非运行依赖）

- yt-dlp：<https://github.com/yt-dlp/yt-dlp>
- Douyin_TikTok_Download_API：<https://github.com/Evil0ctal/Douyin_TikTok_Download_API>

本项目通过 PyPI 安装 yt-dlp，并将 A-Bogus 必要代码内置；以上仓库不会被 CI checkout，也不会被 Docker 镜像复制。
