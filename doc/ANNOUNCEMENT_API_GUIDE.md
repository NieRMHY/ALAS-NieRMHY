# 公告 API 增量更新对接文档

为了降低服务器带宽消耗，ALAS 客户端已升级公告获取逻辑。请 API 服务端配合进行以下调整。

## 接口信息

- **路径**: `/api/get/announcement`
- **方法**: `GET`

## 请求参数变更

| 参数名 | 类型    | 必填          | 说明                              |
| :----- | :------ | :------------ | :-------------------------------- |
| `t`    | int     | 是            | 时间戳 (用于防止 CDN/浏览器 缓存) |
| `id`   | int/str | **否 (新增)** | 客户端当前缓存的公告 ID           |

## 服务端处理逻辑 (伪代码)

服务端需要获取客户端传递的 `id`，并与当前最新公告的 ID 进行对比。

```python
def get_announcement(request):
    # 1. 获取当前最新公告
    latest_announcement = DB.get_latest_announcement()

    if not latest_announcement:
        return {}

    # 2. 获取客户端传来的 ID
    client_id = request.args.get('id')

    # 3. 对比 ID
    # 注意：客户端传来的可能是字符串，需要确保类型一致再对比
    if str(client_id) == str(latest_announcement['announcementId']):
        # [情况 A] 客户端已有最新公告
        # 方式一：返回 HTTP 304 Not Modified (推荐)
        return Response(status=304)

        # 方式二：返回空 JSON (如果框架不支持 304)
        # return {}

    # [情况 B] 客户端无公告或公告已过期
    # 返回完整公告内容
    return {
        "announcementId": latest_announcement['announcementId'],
        "title": latest_announcement['title'],
        "content": latest_announcement['content']
    }
```

## 响应示例

### 情况 1: 有新公告 (HTTP 200)

当 `id` 参数不存在，或 `id` 与最新 ID 不匹配时：

**示例 A (纯文本):**

```json
{
  "announcementId": 1001,
  "title": "版本更新公告",
  "content": "修复了一些已知问题..."
}
```

**示例 B (网页链接 - 推荐):**

```json
{
  "announcementId": 1002,
  "title": "活动网页",
  "url": "https://example.com/event-page",
  "content": ""
}
```

_(注意：当 `url` 存在时，content 可为空。前端将优先渲染网页。)_

### 情况 2: 无需更新 (HTTP 304 或 200 Empty)

当 `id` 与最新 ID 匹配时：

**方案 A (推荐):**

- **Status Code**: `304 Not Modified`
- **Body**: (Empty)

**方案 B (兼容):**

- **Status Code**: `200 OK`
- **Body**:

```json
{}
```

_(ALAS 客户端兼容这两种返回方式)_
