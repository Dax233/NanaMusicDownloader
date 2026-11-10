# NanaMusicDownloader

批量下载视频、转成 MP3、写入音频 tag、按标题分割词重写歌名/歌手，并模糊匹配歌词。

> 实测只覆盖哔哩哔哩（B 站）合集，其他视频站点未验证。
> 本项目以 AGPL-3.0 发布，歌词匹配部分衍生自 RavelloH/music-lrc-match，详见文末「许可与致谢」。

## 用途

把「一个翻唱合集页」变成「一堆整理好 tag、配好歌词的 MP3」：

1. 用 you-get 下载合集里的全部视频；
2. 用 ffmpeg 转成 MP3，并把歌名、歌手、专辑、封面写进 tag；
3. 按文件名里的分割词（默认 `" - Cover- "`）重写标题与歌手；
4. 按歌名去网易云镜像搜索歌词，写同名 `.lrc` 文件；匹配度低于阈值自动跳过。

## 安装

环境要求：Python 3.11+、ffmpeg、you-get。

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install .

# 需要写 MP3 tag 时再装可选依赖（eyed3）
pip install ".[tag]"

# 外部命令（不是本项目的 pip 依赖）
pip install you-get
sudo apt install ffmpeg        # macOS: brew install ffmpeg
```

核心包只依赖标准库：不装 eyed3 也能 import、跑测试、执行 retitle/lyrics；
`download` 在写 tag 那一步会给出「缺少 eyed3」的明确提示。

## 配置

所有可调项都在 TOML 里，不再需要改源码：

```bash
cp config.example.toml config.toml
# 编辑 config.toml：下载地址、输出目录、cookies、歌手/专辑、分割词、歌词 API 等
```

`config.example.toml` 里每个字段都有注释。要点：

| 配置段 | 关键字段 | 说明 |
| --- | --- | --- |
| `[download]` | `url`、`output_dir`、`cookies_file`、`cover_image`、`bitrate` | 下载地址、输出目录、登录 cookies、封面、转码参数 |
| `[tag]` | `artist`、`album`、`album_artist`、`split_word` | 写入 MP3 的元信息与标题分割词 |
| `[lyrics]` | `songs_dir`、`lrc_dir`、`language`、`similarity_threshold`、`search_apis`、`timeout`、`retries` | 歌词目录、原文/翻译、匹配阈值、多 API 降级顺序与超时重试 |

- 相对路径以**配置文件所在目录**为基准解析；
- `cookies_file`、`cover_image`、`lrc_dir`、`log_file` 留空表示不启用；
- `config.toml` 已写进 `.gitignore`：它可能包含本机 cookies 路径，不要提交；
- 未写进配置文件的项一律使用内置默认值。

## 用法

原本的三步流程（依次运行三个脚本）现在对应三个子命令，外加「一条龙」：

### 1. 下载、转 MP3、写 tag

```bash
nana -c config.toml download
# 也可以临时覆盖地址与输出目录
nana -c config.toml download "https://space.bilibili.com/xxx/..." -o ./output
```

输出目录里已有同名 MP3 时会自动跳过（防重）；转码成功后默认清理源视频与弹幕 XML，
用 `--keep-video` 可保留。

### 2. 按分割词重写标题与歌手

```bash
nana -c config.toml retitle
# 或指定目录 / 分割词
nana -c config.toml retitle ./output --split-word " - Cover- "
```

文件名形如 `歌名 - Cover- 歌手.mp3` 时，标题写成 `歌名`、歌手写成 `歌手`；
没有分割词的文件只把标题改成去掉扩展名的文件名，歌手保持不变。

### 3. 搜索并写入歌词

```bash
nana -c config.toml lyrics
nana -c config.toml lyrics ./output --language translation --threshold 80
```

### 一条龙

```bash
nana -c config.toml all
```

也可以用 `python -m nana ...` 代替 `nana ...`。退出码：0 成功，1 有失败项，2 配置错误。

## 项目结构

```text
nana/
  config.py      TOML 配置加载 + dataclass 校验
  downloader.py  you-get 下载、ffmpeg 转码、eyed3 写 tag（依赖可注入）
  retagger.py    文件名分词与 MP3 tag 重写
  lyrics.py      歌词 API 客户端：多源降级、超时重试、匹配打分
  cli.py         argparse 子命令 download / retitle / lyrics / all
  utils.py       标题清洗、文件名解析、相似度打分等纯函数
  fsutil.py      中间文件清理（单独成模块方便审阅）
tests/           不联网、不依赖外部命令的单元测试
config.example.toml
pyproject.toml
```

## 开发与测试

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest -q
```

测试全部离线：外部命令（you-get / ffmpeg）与 tag 写入都是注入的假实现，
不需要安装 eyed3、you-get、ffmpeg，也不会访问网络。
当前状态：78 个测试通过。

## 从旧版迁移

| 旧版 | 新版 |
| --- | --- |
| 改 `Downloader.py` 顶部常量后运行 | 改 `config.toml`，运行 `nana download` |
| `reTitle.py`（改 `splitword`、`folder_path`） | `nana retitle` |
| `musicLrcMatch.py`（交互式输入目录） | `nana lyrics`（目录/语言/阈值走配置或参数） |
| `requirement.txt` | `pyproject.toml`（`pip install .` / `.[tag]`） |

## 已知限制

- 仅验证过 B 站；其他站点取决于 you-get 是否支持；
- 本地文件名由标题清洗规则生成，若 you-get 的落盘命名与之不一致，会在转码时提示
  「未找到下载后的视频文件」，可加 `--keep-video` 后手动核对；
- 歌词 API 是第三方公开镜像，可用性不稳定；失败会按 `search_apis` 顺序降级，
  全部失败时该首记为失败并继续处理下一首；
- 模糊匹配只看歌名相似度并给歌手命中加分，同名/翻唱仍可能匹配错，可用
  `similarity_threshold` 调整；
- 翻译歌词依赖 API 是否返回 `tlyric`，没有翻译时该首跳过；
- 不做并发下载，大合集会比较慢；
- 日志是追加文本记录，用于回看，不做断点记账：去重靠已有 `.lrc` 与同名 MP3。

## 许可与致谢

- 本项目以 **AGPL-3.0** 发布，完整许可见 [LICENSE](LICENSE)；
- 歌词搜索与匹配的原始实现来自 [RavelloH/music-lrc-match](https://github.com/RavelloH/music-lrc-match)，
  同为 AGPL-3.0。本仓库的 `nana/lyrics.py` 是其衍生重构版，保留原作者 RavelloH 的致谢，
  并继续以 AGPL-3.0 分发；
- 原项目作者：Dax233；仓库内 `avater.jpg` 为示例专辑封面。
