# 欢迎参与知识库共建

> [!IMPORTANT]
> **欢迎贡献您有权分享的个人知识库，让可靠知识服务更多患者、家属与志愿者。**
>
> **提交前请阅读：[知识库共建与知识产权授权协议](docs/KNOWLEDGE_CONTRIBUTION_AGREEMENT.md)。在已获得本协议明确提示后，主动向社区提供用于共建的知识库链接、文件或访问授权，即视为已阅读并接受协议：允许社区在约定公益服务范围内使用；贡献者对资料来源、知识产权与授权真实性负责。社区不为贡献资料的权属提供担保，相关责任按协议及法律规定承担。不同意请勿提交。**
>
> **不要提交 API Key、Token、账号密码、未脱敏病历或无权转授权的整本图书、付费资料。**

### 如何贡献

1. **整理资料**：优先提供原创科普、护理经验整理、合法授权资料及有明确开放许可的内容，注明来源、版本、适用主题和署名方式。
2. **发起共建**：填写[知识库共建申请](https://github.com/opencare-skillhub/ima-fastgpt-ingest/issues/new?template=knowledge-contribution.yml)，公开提交名称、简介和拟贡献范围，确认协议。非公开共享链接和授权证明请在维护者确认的私密渠道提交。
3. **共享访问**：按维护者提供的接入账号，在 IMA 中创建共享邀请或邀请其加入，开放所需文件的合法读取权限；通常不需要提供您的个人 API Key。
4. **审核接入**：社区核对授权与原文可访问性，经解析、质量检查及必要的专业审核后，决定是否接入 FastGPT；提交不代表自动入库或立即上线。

详情：[贡献操作说明](CONTRIBUTING.md) · [完整协议与权利人反馈方式](docs/KNOWLEDGE_CONTRIBUTION_AGREEMENT.md)

---

# IMA → MinerU → FastGPT

将 IMA 知识库接入 FastGPT 的 Agent 技能与只读预检工具：核对原文访问权限，设计批量文档解析、质量审核、增量入库及向量检索验收。

本仓库包含可执行的 **IMA 只读预检器** 和接入流程文档；不包含已部署的全自动同步服务，也不会安装后自动下载资料、上传 MinerU 或写入 FastGPT。

## 安装

需要 Python 3.10+；本仓库预检器只使用 Python 标准库。使用腾讯官方 IMA 技能还需要 Node.js 18+，具体依赖以官方包的 `meta.json → required_binaries` 为准。

```bash
git clone https://github.com/opencare-skillhub/ima-fastgpt-ingest.git
cd ima-fastgpt-ingest
python3 scripts/ima_probe.py --help
```

仓库根目录就是技能目录，可安装到 Agent 支持的技能路径。已有同名目录时先保留原配置，不要覆盖自己的 `.env`。支持 Codex 的环境中可调用 `$ima-fastgpt-ingest`。

## 申请 IMA Client ID / API Key

1. 先从 [IMA 官方网站](https://ima.qq.com/download)安装并登录 **IMA Desktop**，确认该账号能访问需要接入的知识库。
2. 打开 [IMA 开放接口页面](https://ima.qq.com/agent-interface)，按页面流程获取 **Client ID** 和 **API Key**，妥善保存。
3. 按下列任一方式配置。共享链接中的 `shareId` 不是 API Key，也不等于 `knowledge_base_id`；共享目录可见不代表每个文件都允许 API 下载。

若使用腾讯官方 IMA 技能，请从开放接口页面获取当前官方包。本仓库独立维护，不分发或重新许可腾讯官方技能代码。

### 方式 A：配置文件（推荐）

将占位符替换为自己的凭据；不要将真实值写入 README、聊天截图或公开命令记录。

```bash
mkdir -p "$HOME/.config/ima"
chmod 700 "$HOME/.config/ima"
umask 077
printf '%s\n' 'your_client_id' > "$HOME/.config/ima/client_id"
printf '%s\n' 'your_api_key' > "$HOME/.config/ima/api_key"
chmod 600 "$HOME/.config/ima/client_id" "$HOME/.config/ima/api_key"
```

### 方式 B：环境变量

```bash
export IMA_OPENAPI_CLIENTID="your_client_id"
export IMA_OPENAPI_APIKEY="your_api_key"
```

本仓库对每个字段依次读取：主环境变量 → 兼容环境变量 `IMA_CLIENT_ID` / `IMA_API_KEY` → `~/.config/ima/client_id` / `api_key`。不要保留互相冲突的新旧环境变量。

也可复制 `.env.example` 为私有 `.env`，填入真实值并设为600权限。工具不会自动读取 `.env`，需要显式加载：

```bash
set -a
source .env
set +a
```

### Credential Check（先检查，再调用 API）

推荐使用无网络预检，它同时支持环境变量和配置文件，**只显示配置来源，不输出凭据值**：

```bash
python3 scripts/ima_probe.py --check-credentials
```

只检查推荐的配置文件方式时：

```bash
if test -s "$HOME/.config/ima/client_id" && test -s "$HOME/.config/ima/api_key"; then
  echo "✅ Credentials configured"
else
  echo "⚠️ NO CREDENTIALS — setup required before any API call"
fi
```

这里不在 `test` 前加 `!`；加上会反转第一个文件的判断。`-s` 同时检查文件存在且非空。出现 `NO CREDENTIALS` 时，先完成上面的申请和配置，**不要尝试 API 调用**。

本仓库缺少凭据时返回 `AUTH_REQUIRED`、退出码2，不发网络请求。腾讯官方 `node ima_api.cjs ...` 的错误约定不同：缺少凭据是程序错误 `code: -100`，并向 stderr 输出 `msg`；该值不是本仓库退出码，也不是保证操作系统能保留的负数进程状态。

## 只读核对来源库

使用官方 API 返回的库 ID，不要填写共享链接或 `shareId`：

```bash
python3 scripts/ima_probe.py --kb-id '<knowledge_base_id>' --probe-media 3
```

预检器调用官方 `get_knowledge_base`、`get_knowledge_list`、`get_media_info`：

- 核对库身份，完整遍历游标和子文件夹。
- 检查少量文件是否有访问 URL、是否需要额外下载请求头。
- 输出 URL 主机名，不输出完整签名 URL 或请求头值。
- 无 URL 记录 `CONTENT_UNAVAILABLE`；不把目录标题或搜索高亮当作原文。
- 不下载正文、不请求生成密钥、不添加知识、不写入远端资源。

官方 `get_media_info` 支持原文访问资料，但可能成功返回却没有 URL。具体权限以当前账号与文件实际结果为准；无权访问时使用有权限的客户端或联系资料提供方，不绕过限制。

## 批量解析与入库设计

```text
IMA授权原件
  → MinerU批次申请上传地址
  → 按文件PUT、按batch_id统一轮询
  → 自动下载各文件结果ZIP与Markdown
  → 内容清洗、QA和专业审核
  → approved目录
  → FastGPT增量上传、分块、embedding
  → 检索回归后发布
```

MinerU 的“批量”不表示一次 HTTP 请求上传全部字节，也不表示一个 ZIP 包含所有结果。一个批次有多个上传 URL；每份文件有自己的结果 ZIP，均由程序自动处理。

优先复用：

| 技能 | 分工 |
|---|---|
| `fastgpt-content-processor` | 本地 Markdown 清洗、标签、QA；本流程不传 `--dataset-id` |
| `fastgpt-kb-sync` | 唯一正式上传入口：去重、增量同步、状态核对及检索检查 |

这两个技能不是本仓库捆绑依赖，也不自带 MinerU 解析。先完成一份样本验收，再按当前额度组批。**QA 输出目录可能包含未通过文件，不能整目录直接上传**；只同步评分及专业审核通过的 `approved/`。

详细说明：[架构与成功标准](references/architecture.md)、[API 契约](references/api-contracts.md)、[既有工具复用](references/tool-reuse.md)。

## MinerU Token

从 [MinerU 官方 Token 管理页](https://mineru.net/apiManage/token)按当前流程申请，私有配置使用：

```bash
export MINERU_TOKEN="your_mineru_token"
```

旧工具如需 `MINERU_API_TOKEN`，将其设置为同一值。MinerU 云解析会向解析服务上传文件；正式执行前确认资料处理范围，对患者可识别信息先脱敏。本仓库只读预检不使用 MinerU Token。

## 安全与验证边界

- 本仓库预检器仅将 IMA 主凭据作为 HTTP 请求头发送到 **`ima.qq.com`**，不发送到其他域名，并拒绝 API 重定向。
- 本地凭据只保存在用户选定的私有配置位置；不写入日志、测试快照、Git历史或发布包。不要用 `set -x`、`cat .env`、`env` 或 `printenv`展示真实值。
- 原文下载需另用 IMA 返回的文件访问 URL/header；这些临时凭据不能混同主 Key，也不应出现在公开日志。
- `.env`、凭据目录、原始资料、解析结果与运行日志由 `.gitignore` 排除；打包仍需检查文件清单，`.gitignore`不能替代打包过滤。
- 通用 QA 分数不能证明医学事实正确；旧指南、跨癌种章节与研究进展需分域、版本标记和专业审核。
- 上传成功不等于 embedding 完成；必须检查训练状态和正确来源的检索命中。

## 测试

```bash
python3 -m unittest discover -s scripts -p 'test_*.py' -v
```

离线测试覆盖凭据优先级与缺失时不联网、分页/递归、异常游标、身份校验、日志脱敏及写接口拒绝。测试通过不代表某个真实知识库可访问，亦不代表批量解析或入库已经运行。

## License

[MIT](LICENSE)。适用于本仓库原创代码与文档。第三方平台、官方技能包及资料原件遵循各自许可和使用条件。
