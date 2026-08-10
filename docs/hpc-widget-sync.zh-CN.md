# 本地 HPC Widget 到 Kindle 的定时锁屏同步

## 推荐结论

最佳结构不是让 Mac 定时 SSH 进入 Kindle，而是拆成两个互不等待的周期：

```text
BJTU HPC Widget snapshot.json
  → Mac 二次最小化、匿名化
  → 本地生成 1072×1448 灰度 PNG
  → 仅在可见内容变化时发布
  → Kindle RTC 唤醒后通过 HTTPS + ETag 拉取
  → 校验 PNG/SHA-256，原子替换并自然重新休眠
```

这样 Kindle 睡眠、IP 变化或短时离线都不会阻塞 Mac；Mac 睡眠或发布失败时，Kindle
继续使用上一张已验证图片。两个方向都不需要保存 Kindle 的 SSH 密码。

## 隐私边界

HPC Widget 的原始快照只留在 Mac。本项目的适配器会再次做数据最小化：

- 账户名固定映射为 `ACCOUNT A` 到 `ACCOUNT F`；
- 不输出作业 ID、作业名、登录状态细节、令牌或 guardian 原文；
- 只保留集群总量、四个节点的容量/状态、匿名账户的运行/排队计数；
- 远端分支只允许 `assets/panel-base.png` 和不含业务数据的校验清单。

即便匿名化，GPU 空闲量和作业计数仍属于真实集群使用情况。启用公共 GitHub 发布前，
必须明确接受这些聚合指标可以公开；否则应改用私有对象存储。不要把原始
`snapshot.json` 放进 Git、HTTP 目录或 Kindle。

## 本地渲染

只生成本地预览，不发布：

```bash
python3 scripts/run_hpc_kindle_sync.py \
  --runtime-dir "$HOME/Library/Application Support/BJTUKindleSync"
```

输出目录中的 `outbox/panel-base.png` 必须是 1072×1448、8 位灰度 PNG。适配器以
规范化 JSON 的 SHA-256 判断“可见语义”是否改变；快照只更新时间但数值不变时，
不会重写 PNG。快照超过 15 分钟、采集返回非零或携带错误时，画面明确显示
`STALE`，而不是把旧数据伪装成实时数据。

## 发布端点

### 方案 A：专用单提交 Git 分支

当聚合指标允许公开时，推荐使用同一公开仓库的 `kindle-live` 分支：

- 分支只含 PNG 和校验清单；
- 每次变化都 amend 唯一根提交，再使用精确 `--force-with-lease` 更新；
- 不产生无限增长的高频提交历史；
- 发布器发现分支不是单提交或存在额外文件时会拒绝改写；
- HTTPS URL 或 plist 中禁止内嵌用户名、密码和令牌。

首次启用示例（该命令会真实创建/更新远端分支）：

```bash
python3 scripts/run_hpc_kindle_sync.py \
  --runtime-dir "$HOME/Library/Application Support/BJTUKindleSync" \
  --remote https://github.com/OWNER/REPOSITORY.git \
  --branch kindle-live
```

Kindle 的 `UPDATE_URL` 随后指向：

```text
https://api.github.com/repos/OWNER/REPOSITORY/contents/assets/panel-base.png?ref=kindle-live
```

发布器依赖 Mac 已有的 Git 凭据；凭据不进入 Kindle、仓库、命令输出或 launchd
配置。若后台 `git push` 无法使用 Keychain 凭据，应先修复 Mac 的非交互 Git
认证，不要把令牌写进 URL。

### 方案 B：私有对象存储

若聚合指标不能公开，使用支持稳定 URL、ETag 和 TLS 1.2 的私有对象存储。写入凭据
只放在 Mac Keychain；若读取也需认证，把只读 header 放在 Kindle root 所有、权限
`0600` 的 `/var/local/bjtu-dashboard/curl.conf`。USB 可见的 `update.conf` 仍只保存
非敏感 URL。该方案需要单独接入具体存储服务，不能用“秘密但公开可访问”的 URL
冒充访问控制。

## macOS 定时任务

先查看将生成的 plist，不做修改：

```bash
python3 scripts/install_macos_hpc_sync.py --print-plist
```

确认发布端点后安装：

```bash
python3 scripts/install_macos_hpc_sync.py --install \
  --remote https://github.com/OWNER/REPOSITORY.git \
  --branch kindle-live
```

安装器把最小运行时和独立 Python 虚拟环境放到用户的 Application Support，避免依赖
iCloud 仓库是否已下载；LaunchAgent 同时使用 `WatchPaths` 监听快照变化，并以 300 秒
`StartInterval` 兜底。进程通过文件锁防止重叠，发布成功状态单独保存，所以网络发布
失败后下一轮仍会重试，而不会因为 PNG 没再次变化而漏发。任务通过 `env -i` 启动，
只传入最小的 `HOME`、`PATH`、locale 和 Python 设置，避免继承用户图形会话中的无关
令牌或凭据。

卸载只移除 LaunchAgent，保留运行时和最后一张图以便审计或恢复：

```bash
python3 scripts/install_macos_hpc_sync.py --uninstall
```

## Kindle 更新周期

Kindle 侧继续使用现有 `bjtu-dashboard-updater`：

1. 在最后一级 `readyToSuspend` 后设置一次性 `rtcWakeup`；
2. 计划唤醒且用户未解锁时执行 `abortSuspend`，等待 Wi-Fi 自动恢复；
3. 以 HTTPS 和 `If-None-Match` 请求图片；`304` 时不写闪存；
4. `200` 时检查响应大小、PNG 签名、1072×1448、8 位灰度和 SHA-256；
5. 下载到 `.incoming`，校验通过后 `mv` 原子替换；失败则保留旧图；
6. 仅在屏保状态渲染，不模拟电源键，网络窗口结束后由 powerd 自然深度休眠；
7. 用户主动解锁变为 `active` 时取消后台任务，不替换或刷新画面。

设备的完整实测边界见 [RTC 唤醒与后台 Wi-Fi 实测记录](rtc-wifi-validation.zh-CN.md)。

## 故障与恢复

| 故障 | 行为 |
|---|---|
| HPC 快照临时错误但仍可读取 | 生成 `STALE` 告警图 |
| 快照缺失或结构损坏 | 本轮失败，不覆盖 outbox 或 Kindle 旧图 |
| Mac 睡眠或离线 | launchd 在恢复后继续；Kindle 保留旧图 |
| 发布失败 | 不记录成功 SHA，下一轮重试同一张图 |
| Kindle Wi-Fi/HTTPS 失败 | 退避重试，旧图保留 |
| 用户在后台窗口解锁 | 取消下载后的替换/渲染，保持前台使用 |
| 远端分支被人工改写 | 发布器拒绝覆盖额外文件或多提交历史 |

当前实现尚未解决两项环境性边界：Mac 长时间关机时无法产生新快照；Kindle 固件或
网络更换后，需要重新验证 TLS、Wi-Fi 恢复和 powerd 状态机。
