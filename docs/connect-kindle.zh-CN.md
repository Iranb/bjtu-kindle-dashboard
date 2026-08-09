# 从 Windows 连接 Kindle

本文说明如何在不记录真实地址、密码、序列号或私钥的前提下，通过 USB 或
WLAN SSH 连接已安装 USBNetwork 的 Kindle，并向本项目部署仪表盘。

以下占位符需要替换：

| 占位符 | 含义 |
| --- | --- |
| `<KINDLE_IP>` | Kindle 当前局域网地址 |
| `<USB_KINDLE_IP>` | USBNetwork 配置中的 Kindle USB 地址 |
| `<WINDOWS_USB_IP>` | Windows USB 网卡在同一子网中的地址 |
| `<KEY_PATH>` | Windows 上的私钥路径 |
| `kindle` | 本文使用的本地 SSH 别名，可自行改名 |

不要把真实密码、私钥、访问令牌或设备序列号提交到 Git 仓库。

## 1. 三种容易混淆的连接模式

| 模式 | Windows 中的表现 | 是否能 SSH | 典型用途 |
| --- | --- | --- | --- |
| USB 磁盘模式 | 出现 Kindle 磁盘 | 否 | 复制 KUAL 扩展、图片和安装包 |
| USB 网络模式 | 出现 USB/RNDIS 网卡，磁盘消失 | 是 | 首次配置、WLAN 故障救援 |
| WLAN SSH | 不需要数据线，使用局域网地址 | 是 | 日常更新和诊断 |

USB 磁盘与 USB 网络通常不能同时使用。执行 `Toggle USBNetwork` 后磁盘消失，
往往表示设备已经切换成 USB 网卡，并不等于 Windows 没有识别 Kindle。

## 2. Windows 准备

在 PowerShell 中确认 OpenSSH 客户端存在：

```powershell
Get-Command ssh
Get-Command scp
```

若找不到命令，可在 Windows 的“可选功能”中安装 OpenSSH Client。私钥目录应只
允许当前 Windows 用户访问。

## 3. WLAN SSH

### 3.1 Kindle 侧前提

1. Kindle 与电脑连接到同一个可信 Wi-Fi；
2. 在 KUAL → USBNetwork 中启用 `Allow SSH over WiFi`；
3. 建议仅启动 SSH 服务，而不自动切换 USB 为网络模式；
4. 设备保持唤醒，飞行模式关闭。

USBNetwork 配置中对应的关键值通常为：

```sh
USE_WIFI="true"
USE_WIFI_SSHD_ONLY="true"
```

配置文件位于 `/mnt/us/usbnet/etc/config`。它是 shell 文件，必须保持 Unix LF
换行；不要在 USB 网络正在启用时直接修改。优先使用 KUAL 菜单切换这些选项。

### 3.2 获取局域网地址

可以从以下位置获取 `<KINDLE_IP>`：

- Kindle 当前 Wi-Fi 网络的详细信息；
- 路由器的 DHCP 客户端列表；
- 已为 Kindle 设置的 DHCP 地址保留记录。

建议在路由器中按设备 MAC 地址保留一个固定租约，而不是在 Kindle 上写死地址。
文档和脚本中只保存 SSH 别名，不保存个人网络拓扑。

### 3.3 检查端口

```powershell
Test-NetConnection -ComputerName <KINDLE_IP> -Port 22
```

`TcpTestSucceeded : True` 表示 SSH 服务可达。`ping` 失败并不能单独证明 SSH
不可用，有些网络会过滤 ICMP。

### 3.4 首次登录

```powershell
ssh root@<KINDLE_IP>
```

首次连接会显示主机密钥指纹。核对设备后再接受，密码只在交互式提示中输入；
不要把密码写进命令、脚本、截图或仓库。

## 4. 配置密钥登录

旧版 Kindle SSH 服务对 RSA 的兼容性通常更好。先在 Windows 生成独立密钥：

```powershell
ssh-keygen -t rsa -b 3072 -f "$env:USERPROFILE\.ssh\kindle_rsa"
```

为私钥设置口令。生成后只有 `.pub` 文件可以复制或分享，永远不要上传私钥。

使用一次密码登录，把公钥安装到 USBNetwork：

```powershell
scp -O "$env:USERPROFILE\.ssh\kindle_rsa.pub" root@<KINDLE_IP>:/tmp/kindle_rsa.pub
ssh root@<KINDLE_IP> "umask 077; mkdir -p /mnt/us/usbnet/etc; touch /mnt/us/usbnet/etc/authorized_keys; cat /tmp/kindle_rsa.pub >> /mnt/us/usbnet/etc/authorized_keys; rm -f /tmp/kindle_rsa.pub"
```

USBNetwork 使用 OpenSSH 格式的 `/mnt/us/usbnet/etc/authorized_keys`。如果重复
执行安装命令，应检查并删除重复公钥行。

测试密钥：

```powershell
ssh -i "$env:USERPROFILE\.ssh\kindle_rsa" root@<KINDLE_IP> "id"
```

确认密钥可以登录后，再考虑限制密码登录。任何认证限制都应先保留一条已验证的
USB 网络救援路径。

## 5. 创建 SSH 别名

编辑 Windows 用户目录下的 `.ssh/config`：

```sshconfig
Host kindle
    HostName <KINDLE_IP>
    User root
    IdentityFile C:/Users/<WINDOWS_USER>/.ssh/kindle_rsa
    IdentitiesOnly yes
    StrictHostKeyChecking yes
    UserKnownHostsFile C:/Users/<WINDOWS_USER>/.ssh/known_hosts_kindle
    ServerAliveInterval 30
    ServerAliveCountMax 3
```

然后测试：

```powershell
ssh kindle "uname -a"
```

如果局域网地址改变，只需要修改 `HostName`。仓库的部署命令只使用别名：

```powershell
python scripts/update_dashboard.py data/dashboard.json `
  --output panel-base.png `
  --deploy kindle
```

## 6. USB 网络连接

USB 网络适合首次安装公钥或 WLAN SSH 不可用时救援。

1. 使用支持数据传输的 USB 线连接 Kindle；
2. 在 KUAL → USBNetwork 中执行 `Toggle USBNetwork`；
3. Kindle 磁盘应消失，Windows 应出现新的 USB Ethernet/RNDIS 网卡；
4. 查看 `/mnt/us/usbnet/etc/config` 中的 `<USB_KINDLE_IP>`；
5. 给 Windows USB 网卡配置同一子网内且不冲突的 `<WINDOWS_USB_IP>`；
6. 测试 22 端口并连接。

USBNetwork 常见默认示例是 Kindle 使用 `192.168.15.244/24`，Windows 可以使用
`192.168.15.201/24`，网关和 DNS 留空。实际值以本机配置为准：

```powershell
Test-NetConnection -ComputerName <USB_KINDLE_IP> -Port 22
ssh root@<USB_KINDLE_IP>
```

操作完成后再次执行 `Toggle USBNetwork`，即可返回 USB 磁盘模式。

如果 Windows 没有出现网卡：

- 确认使用的是数据线而非仅充电线；
- 打开“网络连接”和“设备管理器”查看 USB/RNDIS 设备；
- 等待驱动枚举完成后重新插拔一次；
- 不要因为资源管理器里没有磁盘就立即重复切换模式。

## 7. 部署与检查休眠钩子

确认连接：

```powershell
ssh kindle "/mnt/us/extensions/bjtu-native-screensaver/bin/control.sh status"
```

渲染、上传并预览：

```powershell
python scripts/update_dashboard.py data/dashboard.json `
  --output panel-base.png `
  --deploy kindle
```

读取最近日志：

```powershell
ssh kindle "tail -n 80 /mnt/us/extensions/bjtu-native-screensaver/logs/service.log"
```

Kindle 深度休眠后 WLAN 和 SSH 可能停止响应。需要部署时先唤醒设备，等待 Wi-Fi
图标恢复，再重试连接。这是正常省电行为，不应通过常驻保活来规避。

## 8. 常见故障

### 连接超时

依次检查：设备是否唤醒、IP 是否变化、Wi-Fi 是否相同、22 端口是否开放、路由器
是否启用了 AP/客户端隔离。公共热点通常不适合开启 Kindle SSH。

### Connection refused

IP 可达但 SSH 服务未监听。检查 USBNetwork 是否启动，以及 `Allow SSH over WiFi`
是否已启用。

### Permission denied

检查用户名是否为 `root`、是否选择了正确私钥、公钥是否为单行 OpenSSH 格式，
以及 `authorized_keys` 是否仍在 `/mnt/us/usbnet/etc/`。

### 主机密钥变化

固件恢复或重新安装 SSH 服务后，主机密钥可能改变。先确认变化确实来自自己的
Kindle，再删除旧记录：

```powershell
ssh-keygen -f "$env:USERPROFILE\.ssh\known_hosts_kindle" -R <KINDLE_IP>
```

不要为了省事永久设置 `StrictHostKeyChecking no`。

### scp 报 SFTP/subsystem 错误

较新的 Windows OpenSSH 默认用 SFTP 实现 `scp`，旧 Kindle 服务可能不兼容。
增加 `-O` 强制使用传统 SCP 协议：

```powershell
scp -O <LOCAL_FILE> kindle:<REMOTE_PATH>
```

### Windows 看不到 Kindle 磁盘

先检查是否处于 USB 网络模式。如果 Windows 中出现了 USB Ethernet/RNDIS 网卡，
再次执行 `Toggle USBNetwork` 返回磁盘模式。若两者都没有，再检查数据线、USB
端口和设备管理器。

## 9. 安全与脱敏清单

- 只在自己控制的局域网开启 WLAN SSH；
- 优先使用独立密钥，不复用 GitHub 或其他服务器的私钥；
- 不把密码作为 `sshpass`、URL、环境变量示例或命令参数；
- `.ssh/config`、私钥、`authorized_keys` 和 `known_hosts` 不进入本仓库；
- 截图前遮盖 Wi-Fi 名称、IP、MAC、序列号和账户信息；
- 仪表盘更新令牌应放在 root-only 文件中，不能放在 `/mnt/us` 或图片数据里；
- 不需要远程维护时，可在 KUAL 中选择 `Block SSH over WiFi`。

## 10. 最小恢复路径

在修改 SSH 或休眠服务前，至少保留以下一种恢复能力：

1. KUAL 可以正常打开并切换 USBNetwork；
2. USB 磁盘模式仍能复制扩展文件；
3. USB 网络模式下有一把已验证的 SSH 密钥；
4. 休眠钩子的 `disable` 和 `uninstall` 命令已经记录。

这样即使 WLAN 地址改变、密码认证失效或后台服务异常，也不需要重新执行整个
越狱流程即可恢复。
