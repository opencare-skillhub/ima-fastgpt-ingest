# API契约

接口需以当前官方文档和目标实例为准，不把接口存在当作当前账号已获权限。

## IMA

[官方入口](https://ima.qq.com/agent-interface)。知识库接口为`https://ima.qq.com/openapi/wiki/v1/`下JSON POST，认证头为`ima-openapi-clientid`、`ima-openapi-apikey`。

| 方法 | 输入 | 检查 |
|---|---|---|
| get_knowledge_base | ids数组 | data.infos映射中的ID和名称 |
| get_knowledge_list | knowledge_base_id, cursor, limit，可选folder_id | knowledge_list, is_end, next_cursor |
| get_media_info | media_id | code=0后再检查media_type、url_info |

目录接口返回knowledge_list，搜索接口search_knowledge返回info_list。文件夹可能是FolderInfo或media_type=99条目；使用返回ID原串，不增删folder_前缀。重复游标、缺失下一页游标、schema变化或文件夹环均判目录不完整，不触发删除。

媒体有URL时，后续下载仅附其url_info.headers；无URL则记录CONTENT_UNAVAILABLE。笔记类型11通过notebook_ext_info进入notes内容接口。预检器不会读取笔记正文或下载URL。API端禁止自动跟随重定向，以免泄露主凭据。

## MinerU

[官方云API](https://mineru.net/doc/docs/index_en.html?v=1.0)。本地文件批量协议：

`POST /api/v4/file-urls/batch` → `PUT each upload URL` → 自动提交 → `GET /api/v4/extract-results/batch/{batch_id}` → 下载每份done文件的full_zip_url。

PUT发送原始字节，按官方契约不自行加Content-Type；不要把主Token发送给存储URL。保持请求清单/返回URL/data_id映射，保存任务ID，超时恢复而不盲目重复提交。受header保护的IMA原件先下载再解析。

自部署MinerU的[HTTP协议](https://opendatalab.github.io/MinerU/usage/http_api/)与云端/api/v4不是同一套接口。限制与额度运行前复核，不能按旧文档固定承诺。

## FastGPT

[官方知识库API](https://doc.fastgpt.cn/openapi/dataset)及[API文件库](https://doc.fastgpt.cn/guide/dataset/third-party/api_dataset)。私有实例以`/apidoc/systemopenapi`和小样本响应为准。

普通MD导入候选为`POST /api/core/dataset/collection/create/localFile`，multipart包含file及JSON data。保存collectionId，等待分块/向量训练完成，再用searchTest和真实应用检索验证。由目标dataset的向量模型处理，不混入维度不同的外部向量。

API文件库需要适配`/v1/file/list`、`/v1/file/content`、`/v1/file/detail`、`/v1/file/read`。IMA并不直接实现FastGPT协议；可返回审校后的MD content，不能把共享目录页当正文。
