# 药师会材料审核 · 验收工作台

同一 FastAPI 进程托管 **真实审核 API + 本页 + 样例照片**。面向业务/研发验收：多场次切换、能力期望对照、A–G 路线图、黄金集批量跑。

## 一键使用

```bash
cd "/Users/ruining.yu/project/零售"
source .venv/bin/activate
# .env 里配置 OPENAI_API_KEY（可选 OPENAI_BASE_URL / VISION_MODEL）
uvicorn app.main:app --reload --port 8000
```

浏览器打开：**http://127.0.0.1:8000/demo/**

1. 确认 Token（默认 `dev-token-change-me`，与 `.env` 的 `API_TOKENS` 一致）
2. 选 **药师大讲堂 / 微型药师**
3. 在 **场次** 下拉中切换（`[可审]` 有夹具；`[浏览]` 仅看材料）
4. 点 **开始真实审核**，或 **批量跑可审场次**（串行提交 + 轮询，汇总到能力矩阵页）

## 视图

| Tab | 说明 |
|-----|------|
| 按材料 | 照片列表 + 单张 checks / OCR |
| 能力矩阵 | C/D/E 检测点：期望 vs 实跑；含批量跑结果表 |
| 场级规则 | `rule_results` |
| 路线图 A–G | 拍板 / 样例 / 能力 / 对接进度（只读） |
| JSON | 当前材料或摘要 |

`NEED_HUMAN` 单独标色，**不当作 FAIL**。

## 数据文件

| 文件 | 说明 |
|------|------|
| `scenarios.json` | 场次目录：`id` / `label` / `auditable` / `fixture?` / `photo_base` / `photos_meta` / `expect` |
| `capabilities.json` | C/D/E 能力 → `rule_code` + 适用项目 |
| `roadmap.json` | A–G 条目 + `status`: `blocked` / `todo` / `wip` / `done` |

### `expect` 约定

```json
{
  "overall_status": "PASS",
  "rules": {
    "PANORAMA_COUNT": "PASS",
    "BAYER_LOGO": "PASS"
  }
}
```

不合格场可写 `"overall_status": "FAIL"` 与期望失败的 `rule_code`。

### 当前场次

**可审 · 合格：** 大讲堂 143 / 204 / 208 / 209 / 224；微型 000606 / 000670；双讲 000921 / 000938

**可审 · 不合格：** 大讲堂 185（缺材）、负样本拼盘 NEG-HALL；微型 000728 / 001348 / 001358 / 001453 / 000664

**浏览（命名已修、待补 form）：** 169 / 183 / 218 / 225 / 231

期望汇总：[`docs/fixtures/expects.json`](../docs/fixtures/expects.json)

## 路径

| URL | 说明 |
|-----|------|
| `/demo/` | 验收工作台 |
| `/crop/` | 四角点裁剪（模版 pack） |
| `/v1/demo_config` | Token / Vision 是否已配 |
| `/v1/retail_meeting_checks` | 真实审核 API |
| `/fixtures/*.json` | 请求夹具 |
| `/samples/hall/...` · `/samples/micro/...` | 样例照片 |

## 说明

- Live 每次生成新 `task_id`（`req-demo-{timestamp}-…`）
- 无 `OPENAI_API_KEY` 时任务会 `ERROR` / `MODEL_UNAVAILABLE`
- 大讲堂一场约十几张图，多模态可能需 1～3 分钟；批量跑会更久
