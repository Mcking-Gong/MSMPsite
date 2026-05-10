# MSMP 服务器网站

Minecraft Java 版服务器网站项目。

## 服务器信息
- 服务器地址：`msmp.mplusm.site`
- 版本：1.21.11，ViaVersion 支持 1.9-1.26
- 玩家上限：50

## 技术栈
- **后端**：Python Flask + Flask-SocketIO
- **前端**：单页 HTML，CSS 变量主题系统（深色/浅色）
- **MC 插件**：MSMPBridge — Paper 1.21.11 Java 插件

## 快速开始

### 网站部署
1. 安装 Python 3.8+
2. 安装依赖：`pip install -r requirements.txt`
3. 配置 `.env` 文件（参考下方配置说明）
4. 启动：`python server.py`

### 环境变量 (.env)
```
ADMIN_PASSWORD=你的管理员密码
PORT=5000
SECRET_KEY=你的密钥
MC_SERVER_DIR=MC服务器目录路径
PLUGIN_API_KEY=插件API密钥
```

### MC 插件部署
详见 [MSMPBridge/PLUGIN_DEPLOY.md](MSMPBridge/PLUGIN_DEPLOY.md)

### 一键启动
- Windows：`start.bat`
- Linux：`start.sh`

## 详细部署指南
详见 [DEPLOY_GUIDE.md](DEPLOY_GUIDE.md)
