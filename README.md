\# 🤖 Pico AI Companion - 树莓派上的虚拟形象聊天机器人


本项目是一个受 Neuro-Sama 启发的、运行在树莓派（Raspberry Pi）上的 AI 虚拟形象聊天机器人。

它不仅仅是一个聊天机器人，而是一个完整的、可通过公网访问的、支持多人实时互动的 Live2D 虚拟形象。Pico 拥有自己的情感引擎、语音合成能力，以及由管理员掌控的、可动态切换的模型和人设“工作室”。


作者言：
1，网址（现在）是:https://huge-polished-powerful-refuse.trycloudflare.com/  来玩哦
  2，我前端会做但是难看的像坨屎，所以是ai做的，懒得看代码修bug，所以除了基础部分以外其他的也是ai写的
  没有高中毕业所以懒得写介绍也是ai做的，你要骂我冲着我来，别伤害我ai叠。
  3，会考虑买域名的，本来就想买结果cloudflare慢的和啥一样
  4，没有合适的live2d和语音，所以都是随便找的一些...后面肯定会更新的，有好的也给我推荐一下
  5，/记  是记录重要记忆用的，普通记忆也记但是怕垃圾信息多了拖慢响应

🎮 如何使用：Pico 指南

1. 访问

在任何设备（电脑、手机）的浏览器上，打开 setup_and_run.sh 脚本最后给你的那个 ...trycloudflare.com/pico/... 网址。

2. 登录

输入一个你的昵称，例如 "YK"。

3. 互动

聊天: 在底部输入框打字并发送。

移动模型: 在左侧舞台区（模型身上）按住鼠标或手指拖拽。

缩放模型: 滚动鼠标滚轮，或在手机上双指捏合/张开。

模型归位: 如果模型找不到了，点击右上角的 🎯 按钮。

4. 调教 Pico (本地记忆)

Pico 的记忆保存在你自己的浏览器里。

添加记忆: 发送 /记 我喜欢蓝色

清除记忆: 发送 /清除记忆

5. 工作室 (切换模型)

点击右上角的 🛠️ 设置 按钮。

在模型列表里，点击你想要切换的模型（如 "Mao"）。

Pico 会立刻“变身”！

👑 管理员 (YK) 专属指南

你的账户（YK）拥有特殊权限，可以管理整个平台。

1. 激活权限

登录时，用户名必须输入 "YK"。

进入聊天室后，发送消息：

/好想要个姐姐摸我说我已经做的很好了
（只有和我一样性压抑的人才配当管理）


✨ 核心功能

🧠 智能 AI 大脑: 搭载 Google Gemini 2.5 Flash，通过精心设计的 Prompt 实现情感表达。

🎨 实时 Live2D 形象:

使用 PixiJS v6 + Live2D 引擎渲染，性能出色。

情感-动作双重驱动：AI 回复时附带情感标签（如 [HAPPY], [ANGRY]），自动触发模型对应的表情与动作。

口型同步：实时分析语音音量，驱动模型嘴巴张合，实现“真·说话”。

🗣️ 实时语音合成: 集成 Edge-TTS，AI 的每一句话都会在后台自动合成高保真语音并播放。

🌐 全球公网访问: 使用 Cloudflare Tunnel，无需公网 IP 或路由器端口映射，即可将树莓派服务安全发布到全球。

🧑‍🤝‍🧑 多人聊天室: 基于 Socket.IO 和 Gunicorn + Eventlet 架构，支持多人同时在线实时聊天。

🔒 客户端记忆存储：

公共聊天记录：自动保存在每个用户的浏览器本地（localStorage），不消耗服务器资源。

AI 专属记忆：用户可通过 /记 指令，将关键事实存入本地，AI 会在后续对话中回忆起这些信息。

👑 强大的管理员系统:

分级权限：普通用户可切换模型，但只有管理员能解锁全部功能。

Pico 工作室 (🛠️)：一个用于管理模型的 Web 界面。

人设编辑器：管理员可实时修改每个模型的人设（persona.txt），AI 会立刻采用新设定。

模型管理器：管理员可一键下载或删除服务器上的 Live2D 模型。

🛠️ 技术架构

硬件: 树莓派 (推荐 4B/5, 4GB+ RAM)

后端: Python + Flask + Gunicorn (Eventlet 模式)

AI 核心: Google Gemini API (gemini-2.5-flash)

实时通信: Flask-SocketIO

前端: HTML / CSS / JavaScript

图形渲染: PixiJS v6 + Live2D (Cubism 2 & 4)

公网隧道: Cloudflare (cloudflared)

🚀 安装与启动

1. 硬件准备

一台已配置好网络（Wi-Fi 或有线）的树莓派。

推荐使用 64 位 Raspberry Pi OS (Trixie)，并确保已安装 python3, python3-venv 和 git。

2. 获取代码

在树莓派的终端中，克隆本项目：

git clone [您的 GitHub 仓库 URL]
cd [您的项目文件夹名]


3. 关键配置：API 密钥

这是最重要的一步。你需要 Google Gemini API 密钥。

在项目根目录（与 app.py 同级）创建一个新文件：

nano config.json


粘贴以下内容，并换上你自己的 API Key：

{
  "GEMINI_API_KEY": "AIzaSy...这里替换成你的真实密钥..."
}


按 Ctrl+O 保存, Ctrl+X 退出。

4. 安装 Live2D 模型

你需要至少安装一个模型才能启动。脚本已预置了 Hiyori。

安装 svn (用于从 GitHub 下载子文件夹)：

sudo apt update
sudo apt install subversion -y


运行下载脚本（选择一个你之前创建的、能用的下载脚本）：

# 示例：运行 Hiyori 官方源下载脚本
bash install_hiyori_v4.sh


(你也可以在工作室启动后，让管理员下载更多模型)

5. 一键启动 (使用全能管家)

我们已经把所有复杂的步骤都封装到了 setup_and_run.sh 脚本里。

第一次运行：

# 赋予脚本执行权限
chmod +x setup_and_run.sh

# 运行！
bash setup_and_run.sh


脚本会自动执行以下所有操作：

自我修复：清除 Windows 换行符。

自动更新：git pull 拉取最新代码。

创建环境：创建 .venv 虚拟环境。

安装依赖：安装 gunicorn, eventlet, edge-tts 等所有必需的 Python 包。

下载组件：自动下载 cloudflared 二进制文件。

启动服务：在后台启动 Gunicorn 和 Cloudflare 隧道。

报告地址：在终端打印出你的专属公网网址。

日常运行：
以后每次你想重启或更新服务，只需要再次运行：

bash setup_and_run.sh
\## 🛠️ 技术栈



\* \*\*硬件：\*\* Raspberry Pi 4B/5 (推荐 4GB RAM 或更高)

\* \*\*后端：\*\* Python, Flask, Flask-SocketIO, python-dotenv

\* \*\*AI/LLM：\*\* Google Gemini API

\* \*\*前端：\*\* HTML, CSS, JavaScript (Socket.io 客户端)

\* \*\*部署：\*\* Git, Python 虚拟环境, Shell 脚本



\## ⚙️ 部署指南



\### 步骤 1: GitHub 准备 (您的电脑)



1\.  将本项目克隆或下载到您的电脑。

2\.  将整个 `ai-pi-companion` 文件夹上传到您自己的 GitHub 仓库。



\### 步骤 2: 树莓派部署 (您的树莓派)



1\.  \*\*安装 Git 和 Python 虚拟环境工具：\*\*

&nbsp;   ```bash

&nbsp;   sudo apt update

&nbsp;   sudo apt install git python3-venv -y

&nbsp;   ```



2\.  \*\*克隆项目：\*\*

&nbsp;   ```bash

&nbsp;   cd ~ # 切换到主目录

&nbsp;   git clone \[您的 GitHub 仓库 URL] ai-pi-companion

&nbsp;   cd ai-pi-companion

&nbsp;   ```



3\.  \*\*运行部署脚本：\*\*

&nbsp;   ```bash

&nbsp;   chmod +x setup\_and\_run.sh

&nbsp;   ./setup\_and\_run.sh

&nbsp;   ```

&nbsp;   ⚠️ \*\*注意：\*\* 脚本运行时会提示您输入 \*\*`GEMINI\_API\_KEY`\*\*，请确保您已准备好 Key。



\### 步骤 3: 手机端访问



脚本成功启动后，它会显示树莓派的本地 IP 地址和端口（默认为 `:5000`）。



1\.  确保您的手机和树莓派连接在\*\*同一个 Wi-Fi 网络\*\*下。

2\.  在手机浏览器中输入显示的地址，例如：`http://192.168.1.100:5000`。

3\.  开始与您的 Pico Companion 聊天！



\## 🔄 如何更新项目？



如果您在电脑上修改了代码并推送到 GitHub，只需在树莓派的 `ai-pi-companion` 目录下\*\*重新运行\*\*部署脚本即可：



```bash

cd ~/ai-pi-companion

./setup\_and\_run.sh



