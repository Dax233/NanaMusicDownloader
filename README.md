# NanaMusicDownloader
### 基于Python，批量下载视频，转mp3，修改音频tag信息，找歌词等功能。
注:只尝试过下载哔哩哔哩视频，其余视频网站未做测试



## 使用  
环境:Python3  

**1.安装依赖**

    pip install -r requirements.txt

**2.根据注释与需要编辑文件**

`Downloader.py`里有专辑封面路径、cookies文件路径、视频URL、歌手信息。专辑信息。专辑作者信息。`reTitle.py`和`musicLrcMatch.py`则是分割词。

**3.运行`Downloader.py`**

下载视频并转音频，并编辑音频tag。

**4.手动处理不规则文件名**

音频文件的标题部分是直接取的视频标题，很多视频即使是同一个投稿者投稿也不一定按一定的范式取标题，所以这一步可以手动处理这些不规则的文件名，为下面的重新设置音频标题和匹配歌词提供方便。

**5.运行`reTitle.py`**

依照分割词对文件名进行分割分类，重新编辑音频的标题信息和歌手信息。

**6.运行`musicLrcMatch.py`**

模糊匹配歌词，不一定全能找到或者找对。


## 鸣谢
- [music-lrc-match](https://github.com/RavelloH/music-lrc-match/)

### LICENCE
AGPL @Dax233
