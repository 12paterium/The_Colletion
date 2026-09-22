# metadata —— MemeVault 解析产物

本目录是 [MemeVault](https://github.com/12paterium/MemeVault) 对本仓图片做过的一次**全量视觉解析**结果：
一图一个 JSON，含画面描述（`text`）、标签（`tags`）、角色（`character`）、情绪（`emotion`）、用途（`usage`）
和梗背景（`background`），外加图片内容 md5（JSON 里的 `id`，也是文件名里 `.` 后面那 8 位十六进制）。

- 由 MemeVault 的 `tools/import_batches.py` 用视觉模型批量生成，`analyzed_by` 记着模型名、`analyzed_at` 记着时间
- 纯文本、无密钥；`path` 是相对路径：`images/<本仓里的原文件名>.<id 前 8 位>.<扩展名>`
- 这一层是「花过钱」的部分——每张图一次 API 调用，重跑结果还会变（模型有随机性），所以跟图一起版本化。
  **图片以本仓归档目录（`表情/`、`弔图/`、`史/`、`杂篇/`）为准，这里不再存图。**

## 用它重建一个可搜索的表情包库

先装软件：[MemeVault](https://github.com/12paterium/MemeVault)（`pip install -e .`）。
一个「库目录」= 元数据 + 图片副本 + 索引，三者都在这个目录里：

**1. 建库目录、放元数据**

```bash
mkdir -p /path/to/memes-vault
cp -r metadata/memes /path/to/memes-vault/memes
```

**2. 还原图片副本**

MemeVault 要求图片放在 `<库>/images/` 下、且文件名与 JSON 里 `path` 一致
（`原名` → `原名.<id 前 8 位>.扩展名`）。所以要从本仓的归档目录把图拷过去，顺便改名。
文件名对不上的（图后来被重命名过）用 md5 兜底：**文件内容的 md5 就是 JSON 里的 `id`**。
这一步一次性做完即可，下面是复制粘贴用的片段（不是本仓维护的脚本）：

```python
# 在本仓根目录：python restore_images.py /path/to/memes-vault
import hashlib, json, os, shutil, sys

vault = sys.argv[1]
dirs = ["表情", "弔图", "史", "杂篇"]
byname, bymd5 = {}, {}
for d in dirs:
    for root, _, files in os.walk(d):
        for f in files:
            p = os.path.join(root, f)
            byname.setdefault(f, p)
            bymd5.setdefault(hashlib.md5(open(p, "rb").read()).hexdigest(), p)

os.makedirs(os.path.join(vault, "images"), exist_ok=True)
hit = miss = 0
for jf in sorted(os.listdir(os.path.join(vault, "memes"))):
    if not jf.endswith(".json"):
        continue
    meta = json.load(open(os.path.join(vault, "memes", jf), encoding="utf-8"))
    base = os.path.basename(meta["path"])
    stem, ext = os.path.splitext(base)
    name = stem.rsplit(".", 1)[0] + ext                 # 去掉 .<id 前 8 位>
    src = byname.get(name) or bymd5.get(meta["id"])
    if src:
        shutil.copy2(src, os.path.join(vault, "images", base))
        hit += 1
    else:
        miss += 1
        print("缺图:", name)
print(f"还原 {hit} 张，缺 {miss} 张")
```

（建立这份元数据时：1883 条里 1852 条能直接按文件名对上，其余 31 条是之后被改过名的，靠 md5 命中；
md5 抽查全部一致。以后图被改名也不影响——md5 是主键。）

**3. 建索引**

MemeVault 用嵌入模型把三个通道的文本向量化。图片此时已全部入库，这一步只会建索引、不会重新解析：

```bash
cd /path/to/MemeVault
python tools/import_batches.py --data-dir /path/to/memes-vault --source . --batch 1 --batches 1 --build \
    --embedding-model Qwen/Qwen3-VL-Embedding-8B \
    --embedding-api-base https://api.siliconflow.cn/v1 --embedding-api-key <你的 key>
```

嵌入模型要和之后 MCP 配置里的 `embedding.model` 保持一致（索引清单会比对模型名，不一致会整体重嵌）。

**4. 接上 MCP**

写一份 `mcp_config.json`（`data_dir` 指向库目录，模板见 MemeVault 仓库的 `mcp_config.example.json`）：

```bash
meme-mcp --config ./mcp_config.json                    # stdio：Claude Code 等
meme-mcp --config ./mcp_config.json --transport streamable-http   # HTTP：远程客户端
```

之后 `meme_search` 检索、`meme_get` 取图即可。

## 元数据的更新

MemeVault 库里加了新图、或重刷了旧条目之后，把库目录的 `memes/*.json` 整体再拷过来覆盖一次即可
（只同步 JSON，图片以本仓归档目录为准）：

```bash
cp -f /path/to/memes-vault/memes/*.json metadata/memes/
```

每个条目自带内容 md5，跟图片对不上时以 md5 为准；条目被删掉时记得把 `metadata/memes/` 里对应的
JSON 也删掉。
