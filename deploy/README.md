# 树莓派网关部署

网关当前是安全干运行版本：不打开 UART、不调用电机、没有视频。即便如此，常驻监听的
控制端口也必须启用认证，不能把无令牌服务直接设为开机启动。

## 已完成

- 源码目录：`/home/pi/tennis/robot_gateway`
- 独立虚拟环境：`/home/pi/tennis/.venv-gateway`
- 端口：TCP 8765，WebSocket 路径 `/ws`
- 健康检查：`http://树莓派地址:8765/health`

## 安装为开机服务

先在树莓派本地生成令牌；令牌只保存在树莓派和受信任终端中，不提交到 Git：

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
sudoedit /etc/tennis-robot-gateway.env
```

在编辑器中写入一行，其中实际令牌至少 20 个字符：

```text
TENNIS_GATEWAY_TOKEN=在这里填入刚生成的令牌
```

然后限制文件权限并安装服务：

```bash
sudo chown root:root /etc/tennis-robot-gateway.env
sudo chmod 600 /etc/tennis-robot-gateway.env
sudo cp /home/pi/tennis/deploy/tennis-robot-gateway.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now tennis-robot-gateway.service
sudo systemctl status tennis-robot-gateway.service --no-pager -l
```

Windows/安卓终端连接时，把同一令牌填入界面的“访问令牌”输入框。若环境文件缺失或令牌
长度不足，服务模板会拒绝启动。不要把 8765 端口映射到公网；远程访问应使用可信 VPN。
