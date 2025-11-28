Pico AI Companion

运行在树莓派上的 AI 虚拟伴侣，具备 Live2D 形象展示、情感动作触发和语音合成功能。

核心功能

AI 核心: 使用 Google Gemini 2.5 Flash 进行对话，支持情感识别。

Live2D 形象: 支持 Cubism 2/3/4 模型。根据 AI 回复的情感标签（开心、生气等）自动触发对应的动作和表情。

语音合成:

主用: 在线 VITS API (支持二次元/初音未来声线)。

备用: 微软 Edge-TTS (免费稳定，自动兜底)。

工作室功能: 网页端可直接切换模型、上传背景图片、调整人设和语音参数。

持久化记忆: 自动保存聊天记录、当前使用的模型和背景设置，重启不丢失。

快速开始

下载代码

git clone [您的仓库地址]
cd ai-pi-companion


配置文件
在项目根目录新建 config.json，填入以下内容：

{
  "GEMINI_API_KEY": "您的_Google_Gemini_API_Key",
  "TTS_MODE": "vits",
  "VITS_API_URL": "[https://artrajz-vits-simple-api.hf.space/voice/vits?text=](https://artrajz-vits-simple-api.hf.space/voice/vits?text=){text}&id=165&format=wav&lang=zh"
}


启动服务

chmod +x setup_and_run.sh
./setup_and_run.sh


访问
等待脚本运行完毕，在浏览器打开终端显示的 Cloudflare 公网链接即可。

使用说明

登录: 输入任意昵称进入聊天室。

管理员权限: 使用昵称 yk 登录，并在聊天框发送 /管理员 即可解锁模型上传和配置保存功能。

工作室: 点击右上角的设置图标打开控制面板，可进行模型切换、背景更换和人设修改。

记忆指令: 发送 /记 [内容] 可让 AI 记住特定信息；发送 /清除记忆 可重置。
