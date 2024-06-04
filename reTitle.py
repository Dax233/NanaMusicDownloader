# -*- coding: utf-8 -*-
## github.com/Dax233/NanaMusicDownloader
### MICENCE: GPL
#### By: Dax233
#### 更新于2024/06/04


import os
import eyed3

## 输出预设
success = '\033[0;32m[+]\033[0m'
error = '\033[0;31m[x]\033[0m' 
warning = '\033[0;33m[!]\033[0m'
done = '\033[0;36m[>]\033[0m'
separator = '\n================================\n'


splitword = ' - Cover- ' # 分割词
folder_path = 'output' # 指定要处理的文件夹路径

# 获取指定文件夹下的所有文件
files = os.listdir(folder_path)

for file in files:
    # 获取完整的文件路径
    file_path = os.path.join(folder_path, file)

    # 检查文件是否存在
    if not os.path.exists(file_path):
        print(done + f"文件 {file_path} 不存在，跳过处理。\n")
        continue

    # 检查文件是否为音频文件
    if file.endswith('.mp3'):
        audiofile = eyed3.load(file_path)
        # 将音频文件的标题改为文件名（不包括后缀）
        audiofile.tag.title = os.path.splitext(file)[0]
        
        # 如果有分歌词就将分割词后的字段写进artist，否则不更改
        if splitword in file:
            temp = file.split(splitword)[1]
            artist = temp.split(".mp3")[0]
            audiofile.tag.artist = artist
        
        audiofile.tag.save()

        # 打印一条信息表示文件已被处理
        print(done + f"已处理文件：{file_path}\n")
