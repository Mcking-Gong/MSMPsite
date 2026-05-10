#!/bin/bash
# ==========================================
#  MSMP 一键启动脚本 (Linux/macOS)
#  同时启动网站 + MC 服务器
#  服务端版本: Paper 1.21.11
# ==========================================

echo ""
echo "  ╔══════════════════════════════════════╗"
echo "  ║     MSMP All-in-One Launcher         ║"
echo "  ║     Paper 1.21.11 + Website          ║"
echo "  ╚══════════════════════════════════════╝"
echo ""

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
MC_DIR="$ROOT_DIR/test-server"
WEBSITE_DIR="$ROOT_DIR"

# ====== 选择启动模式 ======
echo "  请选择启动模式:"
echo ""
echo "    [1] 仅启动 MC 服务器"
echo "    [2] 仅启动网站"
echo "    [3] 同时启动 MC 服务器 + 网站 (默认)"
echo ""
read -p "  输入选择 (1/2/3): " MODE
MODE="${MODE:-3}"
echo ""

# ====== 查找 Java ======
find_java() {
    # 优先使用 JAVA_HOME
    if [ -n "$JAVA_HOME" ] && [ -x "$JAVA_HOME/bin/java" ]; then
        echo "$JAVA_HOME/bin/java"
        return
    fi

    # 常见路径
    for p in /usr/lib/jvm/java-17 /usr/lib/jvm/java-21 \
             /usr/local/java /opt/java \
             /Library/Java/JavaVirtualMachines/jdk-17 /Library/Java/JavaVirtualMachines/jdk-21; do
        if [ -x "$p/bin/java" ]; then
            echo "$p/bin/java"
            return
        fi
    done

    # 系统 PATH
    if command -v java &>/dev/null; then
        echo "java"
        return
    fi

    echo ""
}

# ====== 查找可用的 Python ======
find_python() {
    local python_cmd=""
    local use_pythonpath=false

    # 方案1: venv Python（如果可用且能导入 flask）
    if [ -f "venv/bin/python" ] || [ -f "venv/bin/python3" ]; then
        local venv_python=""
        [ -f "venv/bin/python3" ] && venv_python="venv/bin/python3" || venv_python="venv/bin/python"
        if "$venv_python" -c "import flask" &>/dev/null; then
            echo "$venv_python"
            return
        fi
    fi

    # 方案2: 带 PYTHONPATH 的系统 Python（venv 包存在但 python 不工作）
    if [ -d "venv/lib" ]; then
        # 找到 venv 的 site-packages 路径
        local site_packages=""
        for sp in venv/lib/python*/site-packages; do
            if [ -d "$sp/flask" ]; then
                site_packages="$sp"
                break
            fi
        done
        if [ -n "$site_packages" ]; then
            # 尝试系统 python3
            if command -v python3 &>/dev/null; then
                echo "PYTHONPATH:$site_packages:python3"
                return
            fi
            # 尝试系统 python
            if command -v python &>/dev/null; then
                echo "PYTHONPATH:$site_packages:python"
                return
            fi
        fi
    fi

    # 方案3: 系统 Python
    if command -v python3 &>/dev/null; then
        echo "python3"
        return
    fi
    if command -v python &>/dev/null; then
        echo "python"
        return
    fi

    echo ""
}

# ====== 启动网站 ======
start_website() {
    echo "  [→] 启动 MSMP 网站..."
    cd "$WEBSITE_DIR"

    local result=$(find_python)
    if [ -z "$result" ]; then
        echo "  [×] 未找到可用的 Python!"
        echo "  [×] 请确保已安装 Python 3.10+ 并安装依赖"
        exit 1
    fi

    local python_cmd=""
    local pythonpath_dir=""

    # 检查是否是 PYTHONPATH 方式
    if [[ "$result" == PYTHONPATH:* ]]; then
        local parts=(${result//:/ })
        pythonpath_dir="${parts[1]}"
        python_cmd="${parts[2]}"
        echo "  [√] 使用系统 Python + venv 包 (PYTHONPATH)"
    else
        python_cmd="$result"
        echo "  [√] 使用 Python: $python_cmd"
    fi

    # 后台启动网站
    if [ -n "$pythonpath_dir" ]; then
        PYTHONPATH="$pythonpath_dir" nohup "$python_cmd" server.py > website.log 2>&1 &
    else
        nohup "$python_cmd" server.py > website.log 2>&1 &
    fi
    WEBSITE_PID=$!
    echo "  [√] 网站已启动 (PID: $WEBSITE_PID)"
    echo "  [√] 网站地址: http://localhost:5000"
    echo "  [√] 管理面板: http://localhost:5000/admin"
    echo "  [√] 日志文件: $WEBSITE_DIR/website.log"
    echo ""
}

# ====== 启动 MC 服务器 ======
start_mc() {
    echo "  [→] 启动 MC 服务器..."
    cd "$MC_DIR"

    JAVA_CMD=$(find_java)
    if [ -z "$JAVA_CMD" ]; then
        echo "  [×] 未找到 Java! 请安装 JDK 17+"
        echo "  [×] Ubuntu/Debian: sudo apt install openjdk-21-jdk"
        echo "  [×] CentOS/RHEL:   sudo dnf install java-21-openjdk-devel"
        exit 1
    fi

    echo "  [√] Java: $JAVA_CMD"
    $JAVA_CMD -version 2>&1 | head -1

    # 查找服务端 JAR
    SERVER_JAR=""
    for f in paper-1.21.11-*.jar; do
        if [ -f "$f" ]; then
            SERVER_JAR="$f"
            break
        fi
    done

    if [ -z "$SERVER_JAR" ]; then
        echo "  [×] 未找到 Paper 服务端 JAR!"
        exit 1
    fi

    echo "  [√] 服务端: $SERVER_JAR"

    # 检查 EULA
    if [ ! -f eula.txt ]; then
        echo "  [!] 首次运行，自动接受 Minecraft EULA"
        echo "# By changing the setting below to TRUE you are indicating your agreement to our EULA (https://aka.ms/MinecraftEULA)." > eula.txt
        echo "eula=true" >> eula.txt
        echo "  [√] EULA 已接受"
    fi

    # 内存设置
    MEMORY="${MSMP_MEMORY:-2G}"

    echo ""
    echo "  ──────────────────────────────────────"
    echo "  MC 服务器启动参数:"
    echo "    Java:    $JAVA_CMD"
    echo "    内存:    $MEMORY"
    echo "    服务端:  $SERVER_JAR"
    echo "  ──────────────────────────────────────"
    echo ""

    exec $JAVA_CMD -Xms1G -Xmx$MEMORY -jar $SERVER_JAR --nogui
}

# ====== 执行 ======
case "$MODE" in
    1)
        start_mc
        ;;
    2)
        start_website
        echo "网站正在后台运行。按 Ctrl+C 停止。"
        wait
        ;;
    3)
        start_website
        start_mc
        ;;
    *)
        echo "  [×] 无效选择"
        exit 1
        ;;
esac
