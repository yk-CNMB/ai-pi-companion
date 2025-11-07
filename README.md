\# 🤖 Pico AI Companion - 树莓派上的虚拟形象聊天机器人



这是一个基于 Raspberry Pi 和 Google Gemini API 构建的实时 AI 虚拟形象聊天项目。它允许用户通过手机浏览器，与运行在树莓派上的 AI 角色“Pico”进行文字聊天。



\## 🚀 项目特性



\* \*\*实时通信：\*\* 使用 `Flask-SocketIO` 实现手机和树莓派之间的实时、低延迟消息传输。

\* \*\*AI 驱动：\*\* 后端集成 `Google Gemini API`，利用 `gemini-2.5-flash` 提供快速、高质量的对话体验。

\* \*\*角色设定：\*\* AI 拥有“Pico”的虚拟形象设定（活泼、傲娇、热爱科技）。

\* \*\*会话历史：\*\* 自动维护当前会话的上下文，确保对话连贯性。

\* \*\*一键部署：\*\* 包含 `setup\_and\_run.sh` 脚本，简化在树莓派上的部署和更新流程。



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

