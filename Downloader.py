# -*- coding: utf-8 -*-
## github.com/Dax233/NanaMusicDownloader
### MICENCE: GPL
#### By: Dax233
#### 更新于2024/06/04

import os
import re
import json
import glob
import eyed3
import subprocess
from PIL import Image
from eyed3.id3.frames import ImageFrame

img_path = "avater.jpg" # 专辑封面路径
url = "https://space.bilibili.com/498898366/channel/collectiondetail?sid=2626585" # 视频URL或合集页url
cookies_file = "cookies.txt"  # cookies文件路径
artist = 'ななひら' # 歌手信息
album = 'ななひら翻唱集' # 专辑信息
album_artist = 'ななひら' # 专辑作者信息


## 输出预设
success = '\033[0;32m[+]\033[0m'
error = '\033[0;31m[x]\033[0m' 
warning = '\033[0;33m[!]\033[0m'
done = '\033[0;36m[>]\033[0m'
separator = '\n================================\n'

def download_videos_as_mp3(url, cookies_file):
    # 设置输出目录
    output_dir = './output'
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # 下载视频
    print('\n' + done + "[Download]Running you-get command...\n")
    command = f'you-get --playlist --cookies {cookies_file} -o {output_dir} "{url}"'
    subprocess.check_output(command, shell=True).decode()

    # 使用you-get的命令行工具获取播放列表中的所有视频信息
    print(done + "[Get information]Running you-get command...\n")
    command = f'you-get --json --playlist --cookies {cookies_file} -o {output_dir} "{url}"'
    output = subprocess.check_output(command, shell=True).decode()

    # 使用正则表达式找到所有的 JSON 对象
    matches = re.findall(r'\{.*?\}(?=\s*\{|\s*$)', output, re.DOTALL)

    # 解析每个 JSON 对象并添加到列表中
    data = [json.loads(match) for match in matches]

    # 将列表写入metadata.json文件
    with open('metadata.json', 'w') as f:
        json.dump(data, f)

    # 从metadata.json文件中读取视频信息
    print(done + "Parsing JSON output...\n")
    try:
        with open('metadata.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError:
        print(error + "Failed to decode JSON from metadata.json. Here is its content:\n")
        with open('metadata.json', 'r', encoding='utf-8') as f:
            print(f.read())
        return

    # 遍历每个视频
    for video_info in data:
        title = video_info["title"]
        print(done + f"Processing video: {title}\n")

        # 将视频转换为mp3
        print(done + "Converting video to mp3...\n")
        title = re.sub(r'[<>:"/\\|?*]', '-', title)  # 将非字母数字字符替换为 '-'
        mp4_file = os.path.join(".\output", f"{title}.mp4")
        mp3_file = os.path.join(".\output", f"{title}.mp3")
        command = ['ffmpeg', '-i', mp4_file, '-vn', '-ar', '44100', '-ac', '2', '-b:a', '192k', mp3_file]
        subprocess.run(command, check=True)

        # 检查文件是否存在
        if not os.path.isfile(mp3_file):
            print(error + f"File not found: {mp3_file}\n")
            continue

        # 修改mp3信息
        print(done + "Modifying mp3 information...\n")
        audiofile = eyed3.load(mp3_file)
        audiofile.tag.title = title
        audiofile.tag.artist = artist
        audiofile.tag.album = album
        audiofile.tag.album_artist = album_artist
        img_type = Image.open(img_path).format.lower()
        audiofile.tag.images.set(ImageFrame.FRONT_COVER, open(img_path, 'rb').read(), 'image/' + img_type)
        audiofile.tag.save()

    # 删除弹幕文件和视频文件
    file_types = ["xml", "mp4"]
    for file_type in file_types:
        files = glob.glob(output_dir + f"/*.{file_type}")
        for file in files:
            try:
                os.remove(file)
                print(f"Deleted {file}")
            except OSError as e:
                print(f"Error: {file} : {e.strerror}")


    print(success + "Done!\n")

download_videos_as_mp3(url, cookies_file)
