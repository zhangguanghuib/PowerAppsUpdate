# Power Apps 文档更新监控

每天检查 Microsoft Learn 的两个英文目录，生成详细英文 PDF，保存在仓库的 GitHub Release 附件中，供用户按需手动下载，不自动发送邮件：

- <https://learn.microsoft.com/en-us/power-apps/>
- <https://learn.microsoft.com/en-us/troubleshoot/power-platform/power-apps/>

无需 AI 密钥，也不需要 Azure。使用 GitHub Actions；计费及执行额度取决于仓库与 GitHub 套餐。

## 工作方式

1. 从官方 sitemap index 动态发现这两个目录内的文章，**每天抓取全部文章正文**，而不是仅依赖修改日期。
2. 首次运行：保存全部当前正文；用文章 `updated_at`（缺失时用 sitemap `lastmod`）筛选近 30 天候选。尝试获取公开仓库截止日期前及当前的源文件，生成**源文件**详细差异，同时附当前已发布正文。
3. 无可验证历史时明确标注，只提供当前正文，绝不虚构历史差异。首次结果不是完整的网站历史审计：遗漏/不准确的修改日期、私有源文件、历史同步延迟及被移除文章均可能影响覆盖。
4. 后续运行：比较已发布正文快照。PDF 按文章列出新增内容、修改前后段落、删除内容、原文链接及出处。不变正文不会仅因修改日期变化而生成报告。新发现文章不一定是新发布文章。
5. PDF 存入 GitHub Release 附件；快照存入 `monitor-state` 分支。PDF 归档成功后才推进快照。抓取、PDF 或归档失败均使任务失败；不会将不完整扫描保存为成功基线。不配置邮件服务，也不自动发送报告通知。

**文档更新不等于新功能发布。** 此工具不自动判断 feature。正文对比包含文本、链接地址、图片引用地址；不下载图片，不比较图片二进制、CSS 或站点导航。代码格式化、空白及模板噪声会被规范化。两次检查之间的中间版本不保证捕获。跨出监控目录的重定向会明确失败，需要人工核查。

相同页面的查询参数/锚点会合并，监控默认文档版本，而非每个历史版本。代码块缩进会保留并参与比较。

## 本地安装与验证（Windows / PowerShell）

需要 Python 3.12+、[uv](https://docs.astral.sh/uv/)。

```powershell
uv sync --locked
uv run pytest
uv run ruff check .
```

完整运行（可能需要数十分钟；首次历史查询建议设置 `GH_TOKEN`，避免 GitHub 公共 API 的匿名限额）：

```powershell
uv run python monitor.py
```

输出位于 `output\pdf\`。本地不自动提交快照。检查报告成功后，将 `next-snapshot.json.gz` 复制为下次使用的 `state-store\snapshot.json.gz`。不要把局部测试快照当生产基线。

小范围真实网站冒烟测试，使用独立输出目录：

```powershell
uv run python monitor.py --limit 3 --no-history --output tmp\smoke
```

再次测试请更换空的输出目录，避免误用旧的局部快照。开发验证生成的 [两篇文章 PDF 样本](output/pdf/powerapps-monitor-sample.pdf) 仅用于展示格式与历史标注，不是全目录的最近 30 天报告。

`--no-history` 会明确标注禁用历史查询，不声称有历史差异。PDF 字体默认 Windows Arial / Linux DejaVu Sans；可用 `PDF_FONT` 指定 Unicode TrueType 字体。字体未覆盖的字符会写为 `[U+XXXX]`，不会悄悄变成方框。

## 配置云端运行

1. 将本项目上传到你自己的 GitHub 仓库，保留 `uv.lock`。默认分支需含 [工作流](.github/workflows/monitor.yml)。建议私有仓库。
2. 无需配置 SMTP 或邮件 Secrets / Variables。若之前已配置，可在 **Settings → Secrets and variables → Actions** 删除本工具不再使用的 `SMTP_USERNAME`、`SMTP_PASSWORD`、`MAIL_TO` Secrets，以及 `SMTP_HOST`、`SMTP_PORT`、`SMTP_SECURITY`、`MAIL_FROM` Variables；若其他工作流仍在使用，请保留。
3. 确认仓库允许 Actions 的 `contents: write`，且规则允许创建 Release、推送 `monitor-state`。凭据使用任务自带 `GITHUB_TOKEN`，不需要个人 token。
4. **Actions → Power Apps documentation monitor → Run workflow** 手动运行首次任务。
5. 确认 Release PDF 与 `monitor-state` 均存在，再启用日常使用。云端 cron 是 `0 1 * * *`，即北京时间每天 09:00；GitHub 可能延迟执行，不保证准点。公共仓库长期不活跃可能自动停用定时任务，请定期检查。

## 手动下载 PDF

进入 GitHub 仓库首页 → **Releases** → 选择需要的报告 → 展开 **Assets** → 点击 `powerapps-updates-*.pdf` 下载。PDF 作为仓库的 Release 附件保存，不提交到代码分支。

私有仓库需要登录具备仓库访问权限的 GitHub 账号。无正文变化时不生成新报告。工具不发送邮件；GitHub 平台自身的 Release / Actions 通知取决于用户的 Watch 和通知设置，如需关闭请在 GitHub 中调整。

## 保存、重试与运行限制

- Release PDF 不设自动过期；仅在仓库、Release 或附件被删除时丢失，仍受 GitHub 政策、容量和可用性限制。重要资料请另行备份。运行产物只用于诊断，保留 30 天，不承担长期归档。
- 状态分支含压缩的完整正文，Git 历史会增长，需关注仓库容量。不要删除状态分支；删除会导致重新执行首次初始化。
- 相同差异使用稳定的 Release 标签，重试覆盖同一附件。PDF 归档成功后若推送状态失败，可重新运行任务；只有状态成功推进后，后续扫描才以新正文作为基线。
- 首次历史查询失败（如 API 限流）会明确失败，可稍后重试；不会静默跳过。明确不存在的历史文件会在 PDF 标注。
- 单次任务上限 180 分钟，4 个抓取线程，HTTP 超时及有限重试；限流、文章结构变化、目录异常收缩都可能使任务失败。失败时检查 Actions 日志，GitHub 自带通知可用于任务失败提醒。
- 目录消失条目需在两次成功扫描中均未出现才报告“未再列出”，不直接断言网页已删除。大幅缩减会拒绝推进状态。

## 许可与归属

源文档公开仓库声明 CC BY 4.0。PDF 保留 Microsoft / Microsoft Learn contributors 归属、原文地址、源文件比较地址及许可证链接，并明确重新排版/改写。第三方素材可能有独立条款；本工具不复制图片。详细报告可能含较长原文，请按原始文档许可使用。
