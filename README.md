---
title: 社团填报助手后端说明
output: pdf_document
---

# 说明

2xx — 成功
状态码 含义 常见场景
200 OK 请求成功 GET 查询成功、POST 操作成功
201 Created 创建成功 注册用户、新建资源
204 No Content 成功但无返回内容 DELETE 删除成功
3xx — 重定向
状态码 含义 常见场景
301 Moved Permanently 永久重定向 域名迁移
302 Found 临时重定向 登录后跳转
304 Not Modified 内容未变化 ETag 命中缓存 ← 你用过的！
4xx — 客户端错误（用户/前端的锅）
状态码 含义 常见场景
400 Bad Request 请求格式/参数错误 字段缺失、类型错误
401 Unauthorized 未认证 没带 Token、Token 过期
403 Forbidden 无权限 Token 合法但权限不足
404 Not Found 资源不存在 查询不存在的社团
405 Method Not Allowed 请求方法不对 用 GET 请求了 POST 接口
409 Conflict 资源冲突 重复选社、用户名已存在
422 Unprocessable Entity 参数校验失败 FastAPI 最常见，Pydantic 校验不通过
429 Too Many Requests 请求太频繁 触发限流

# admin需要的接口

> 首先我定义: 在抢社团的过程中,需要严格禁止管理员对数据库进行操作

1. 上传文件初始化数据库
2. 查看所有数据
3. 修改所有数据
4. 导出选课数据

# 关于前端的数据刷新逻辑

1. 首页数据: onLoad初始化, onShow开始轮询(几秒请求一次), onHide(跳转页面停止轮询), 然后对于剩余人数的特定数据, 采用websocket实时连接修改
2. 管理员数据: 同理,

# 命令

```bash
# 获取管理员权限
sudo -i
# 初始化：服务器初始化
apt update
apt upgrade -y
apt install -y curl wget git vim htop net-tools build-essential

# nginx安装配置
apt install -y nginx

# 启动Nginx
systemctl start nginx
systemctl enable nginx

# 检查Nginx状态
systemctl status nginx
# 此时可以访问http://你的IP 测试

apt install -y mysql-server

# 配置mysql
# 启动MySQL
systemctl start mysql
systemctl enable mysql

# 修改MySQL root用户密码
mysql -u root << EOF
ALTER USER 'root'@'localhost' IDENTIFIED BY 'GG1214';
FLUSH PRIVILEGES;
EOF

# 安装miniconda3
# 下载Miniconda（最新版本）
MINICONDA_URL="https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh"
MINICONDA_INSTALLER="/tmp/miniconda.sh"

curl -o ${MINICONDA_INSTALLER} ${MINICONDA_URL}

# 安装Miniconda
bash ${MINICONDA_INSTALLER} -b -p /opt/miniconda3
/opt/miniconda3/bin/conda init bash
source ~/.bashrc

# 设置conda镜像源（加速下载）
conda config --add channels https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/main
conda config --add channels https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/free
conda config --set show_channel_urls yes

conda create -n club python=3.11


# 安装Certbot和Nginx插件
sudo apt install -y certbot python3-certbot-nginx

# 验证安装
certbot --version
```

```bash
# 查看目前在运行的系统服务
systemctl list-units --type=service --state=running
# 开机自启的服务
systemctl list-unit-files --type=service --state=enabled
```

# nginx配置

> 需要注意的是，nginx worker进程默认是www-data用户运行

上级目录（/home/ubuntu）：需要执行权限（x）

这样 www-data 才能"进入"这个目录
不需要读权限，所以别人看不到目录内容列表
目标目录（/home/ubuntu/TEST）：需要执行权限（x）

这样 www-data 才能进入去访问里面的文件
你已经有了 drwxrwxr-x，所以没问题
文件（index.html）：需要读权限（r）

这样 www-data 才能读取文件内容
你已经有了 -rw-rw-r--，所以没问题
总结成一句话： 从根目录开始，访问链中的每一级目录都必须对 www-data 可执行（x），最终的文件必须对 www-data 可读（r）

还需要注意，权限设置的时候，目录和文件相互独立，不是说目录有权限了，文件就自动有权限了。每一级都要单独设置。

```bash
# 启用配置（创建软链接）
sudo ln -s /etc/nginx/sites-available/example.com /etc/nginx/sites-enabled/example.com

# 检查配置语法
sudo nginx -t

# 重启Nginx
sudo systemctl restart nginx
```

server{
listen 80;
server_name gg1214.uk;
return 301 https://$server_name$request_uri;
}
server {
listen 443 ssl http2;
listen [::]:443 ssl http2;

    server_name gg1214.uk;
    ssl_certificate /etc/letsencrypt/live/gg1214.uk/fullchain.pem; # managed by Certbot
    ssl_certificate_key /etc/letsencrypt/live/gg1214.uk/privkey.pem; # managed by Certbot
    include /etc/letsencrypt/options-ssl-nginx.conf; # managed by Certbot
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem; # managed by Certbot

    # ====== 关键：WebSocket 升级配置 ======
    # 允许升级到 WebSocket
    #proxy_set_header Upgrade $http_upgrade;
    #proxy_set_header Connection "upgrade";
    # ====== 连接超时配置（重要） ======
    # WebSocket 长连接需要更长的超时时间
    #proxy_connect_timeout 60s;
    #proxy_send_timeout 3600s;      # 改大：1小时
    #proxy_read_timeout 3600s;      # 改大：1小时

    # ====== 缓冲配置 ======
    # WebSocket 不能使用缓冲
    #proxy_buffering off;

    #location ~ ^/(auth|api|ws|student|admin|docs|openapi\.json|redoc) {
    #    proxy_pass http://127.0.0.1:8000;
    #    proxy_http_version 1.1;
    #    proxy_set_header Host              $host;
    #    proxy_set_header X-Real-IP         $remote_addr;
    #    proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
    #    proxy_set_header X-Forwarded-Proto $scheme;
    #    proxy_connect_timeout 60s;
    #    proxy_send_timeout 60s;
    #    proxy_read_timeout 60s;
    #}

}
