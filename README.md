
**注：弔图更优质,“史”则接地气**

   # 这是一个梗图+表情等互联网图片库,大约前1600张都是本人手敲命名,此后引入ai自动重命名+人工校正工作流,实现高效rename.

    

## 图片分拣

脚本较为简陋，只处理 `sorting/` 根目录中的图片。每张图片通过一次视觉模型请求同时得到新名称和分类，随后进入以下目录之一：

| 目录 | 判断标准 |
| --- | --- |
| `sorting/表情` | 适合在聊天中直接表达反应、情绪或动作 |
| `sorting/史` | 聊天记录、帖子、长文本或依赖故事上下文的离谱内容 |
| `sorting/梗图` | 内容短小集中，一个笑点即可理解 |
| `sorting/其他` | 壁纸、插画、素材、普通照片或无法归入前三类 |

进入子目录后脚本停止处理，由用户检查并手动搬入最终图库。脚本不递归扫描，也不保存历史记录。

### 安装

```powershell
python -m pip install -r requirements.txt
```

设置一个提供商的 API Key：

```powershell
$env:AI_PROVIDER="你的 API Key"
```
 `AI_MODEL` 指定默认模型。

### 运行

把图片放入 `sorting/` 根目录，然后在仓库根目录执行：

```powershell
python -m scripts/main
```

## metadata/

[MemeVault](https://github.com/12paterium/MemeVault) 对本仓图片做过一次全量视觉解析，结果在 [`metadata/`](metadata/README.md)：
一图一个 JSON（画面描述、标签、角色、情绪、用途、梗背景），可以照着那里的说明重建一个语义搜索表情包库。
图片仍以本仓归档目录为准，`metadata/` 只存解析结果。
