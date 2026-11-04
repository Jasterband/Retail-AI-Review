# 药师会零售会议材料检查（AI 服务）

FastAPI 服务：对齐 `docs/PE接口文档-v1.8.md`。已接入 **本地样例读图 + OpenAI 兼容多模态** 与规则引擎（手册等缺口材料规则 SKIP）。

## 目录

```text
app/
  main.py / config.py / auth.py / db.py
  api/retail_meeting_checks.py
  schemas/ models/
  services/
    asset_fetch.py      # s3_uri → 本地映射（PDF 渲首页）
    vision/             # OpenAI 兼容多模态
    pipeline/           # AssetContext + 聚合
    rules/              # 通用 / 大讲堂 / 微型规则
    check_runner.py     # 异步流水线
    callback.py         # HMAC 回调
    history.py          # pHash / 主题历史
docs/fixtures/          # 黄金场 Request + s3_local_map.json
```

## 启动（API + Live Demo）

需要 Python 3.9+。

```bash
cd "/Users/ruining.yu/Downloads/药师会照片审核示例"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# 编辑 .env：填公司 MyGenAssist Token（见下方「公司网关」）

uvicorn app.main:app --reload --port 8000
```

| 入口 | URL |
|------|-----|
| **Live Demo（推荐）** | http://127.0.0.1:8000/demo/ |
| Swagger | http://127.0.0.1:8000/docs |
| 根路径 | 自动跳到 `/demo/` |

默认 Token：`dev-token-change-me`。  
Demo 里选场次 → **开始真实审核** 即走提交/轮询/展示全链路（详见 [`demo/README.md`](demo/README.md)）。  
**无 `OPENAI_API_KEY` 时服务可启动**，但审核会 `ERROR` / `MODEL_UNAVAILABLE`。

## 本地材料映射

开发期不接真 S3：请求里仍传 `s3://...`，由 [`docs/fixtures/s3_local_map.json`](docs/fixtures/s3_local_map.json) 映射到仓库内样例路径。

配置项（`.env`）：

| 变量 | 说明 |
|------|------|
| `OPENAI_API_KEY` | **公司 MyGenAssist / ALICN Token**（变量名仍叫这个，兼容 OpenAI SDK） |
| `OPENAI_BASE_URL` | 公司网关，默认 `https://chat.int.alicn.bayer.cn/api/v2` |
| `VISION_MODEL` | 看图模型，推荐 `qwen3.5-ocr`（或 `qwen3.5-flash`） |

### 公司网关（MyGenAssist）

本服务走 **OpenAI 兼容** `POST {BASE}/chat/completions`，把 Base URL 指到公司网关即可，不必用公网 OpenAI。

```bash
# .env
OPENAI_API_KEY=你的公司Token
OPENAI_BASE_URL=https://chat.int.alicn.bayer.cn/api/v2
VISION_MODEL=qwen3.5-ocr
```

改完后重启 `uvicorn`。Demo 页提示「已配置 Vision」即表示 Key 已读到。
| `LOCAL_ASSET_ROOT` | 样例根目录，默认进程 cwd |
| `S3_LOCAL_MAP_PATH` | 映射表路径 |
| `CALLBACK_HMAC_SECRET` | 回调签名密钥（可选） |

## 快速试调

```bash
# 健康检查
curl -s http://127.0.0.1:8000/health \
  -H 'Authorization: Bearer dev-token-change-me'

# 提交大讲堂黄金场 143（需 Key；样例在 零售照片ai审核/）
curl -s -X POST http://127.0.0.1:8000/v1/retail_meeting_checks \
  -H 'Authorization: Bearer dev-token-change-me' \
  -H 'Content-Type: application/json' \
  -d @docs/fixtures/hall-meirui-pass.json

# 查询
curl -s 'http://127.0.0.1:8000/v1/retail_meeting_checks/req-hall-143-20260623-001?mode=simple' \
  -H 'Authorization: Bearer dev-token-change-me'
```

其它夹具：微型合格 `micro-000090-pass.json`（000606）、双讲 `micro-000125-pass.json`（000921）、不合格 `micro-000089-pass.json`（000620）。  
样例根目录：`零售照片ai审核/药师大讲堂` · `零售照片ai审核/微型药师`。  
跨会查重：先跑一场会写入 `image_dup_history`，再提交 `docs/fixtures/dup-hit.json`。

## 离线冒烟（不需 Key）

```bash
source .venv/bin/activate
python scripts/smoke_offline.py
```

## 规则说明

- 规则矩阵：[`docs/03-rule-matrix.md`](docs/03-rule-matrix.md)  
- PE simple 对接：[`docs/README-PE-simple对接.md`](docs/README-PE-simple对接.md)  
- 黄金集 / SKIP：[`docs/05-golden-set.md`](docs/05-golden-set.md)  

`HANDBOOK_DETECT` / `HANDBOOK_NOT_STALE`：请求未带 `HANDBOOK` 资产时 **SKIP**，不挡 PASS。
