> 历史资料：以下设计、数量与验收状态不代表当前实现。当前入口与事实以 README.md 和 docs/DELIVERY_V5.md 为准。

# dz 定时全自动（每天 08:00）

## 已注册的定时任务

- ID: `dz-auto`，规则 `daily:08:00`，类型 `cmd`（守护进程本地执行，免费，不耗 AI 会话）
- 执行内容：`cd zhengyao && python3 -m dz.cli pipeline`（后台运行，日志 → logs/auto.log）

## 管线五段（每段独立容错，一段挂不拖全链）

1. **collect**：双板公开采集——anthropic(Greenhouse) + spotify(Lever)，限速 2-5s、robots.txt、指数退避、来源留存
2. **sync**：GitHub BOSS 数据集增量同步（只读本地 CSV，零网络）
3. **eval**：黄金集评测（62 条，离线规则引擎，P/R/F1 写入 reports/eval.md + run_log）
4. **report**：差距分析 → 投递队列 → reports/latest.md + summary.md + dashboard.html（全部离线规则）。靶心报告尾部自动并入「学习闭环 · 全库市场」段：全库样本缺口表 → 两周项目计划 → 最难一条 JD 的差距清单+简历点（学习闭环不锚在静态池，锚在全库）
5. **api**：B 主干自愈——探测 127.0.0.1:8770/api/stats，掉线就拉起脱离管线的实例（日志 logs/api.log）

最后向手机发系统通知（需给 DeepSeek Harness 开「通知」权限，否则只写 run_log）。

## 管理命令

```sh
LJ=/data/user/0/com.deepseek.harness/files/payload/dshhome/skills/dsh-life/scripts/life.js
node "$LJ" cron list            # 看定时任务
node "$LJ" cron rm dz-auto      # 删掉
# 改时间：删了重新加，expr 支持 daily:HH:mm / interval:Xm / 5 段 cron
node "$LJ" cron add --id dz-auto --name "dz每日管线" --expr "daily:21:30" --type cmd \
  --payload "cd /data/user/0/com.deepseek.harness/files/harness对话记录/zhengyao && nohup python3 -m dz.cli pipeline >> logs/auto.log 2>&1 &"
node "$LJ" daemon start          # 手机重启后若守护进程没起来，手动拉起
```

## 手动跑一次

```sh
cd zhengyao && python3 -m dz.cli pipeline
```

## 约束（不变）

- 只碰公开接口与本地文件；需登录平台不抓、不绕过风控、**投递永远人工**。
- 守护进程必须在跑（`node life.js status` 看）；关机错过的班次不会补跑。
- 词表（ontology.py）改了之后手动跑一次 `python3 -m dz.cli reextract`。
