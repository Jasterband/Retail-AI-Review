# AI 审核输入输出契约

JSON Schema：

- [schemas/retail-meeting-check-request.schema.json](schemas/retail-meeting-check-request.schema.json)
- [schemas/retail-meeting-check-response.schema.json](schemas/retail-meeting-check-response.schema.json)

## 调用方式

| 项 | 约定 |
|----|------|
| 触发 | 会议从草稿提交 → `PENDING`；PE 打包调用 AI |
| 传输 | HTTPS JSON；同步长超时 **或** 异步回调均可 |
| 材料 | 仅传 `s3_uri`，AI 侧用 IAM 读对象 |
| 幂等 | 相同 `request_id` 返回首次结果，**不**增加 `ai_check_count` |
| 重提 | 不通过编辑后重新提交 → 新 `request_id`，`attempt_no`/`ai_check_count` +1 |
| 写回锁 | PE 用 `status_version` 乐观锁；版本变化则拒绝覆盖并提示刷新 |

### 建议 API

```
POST /v1/retail_meeting_checks
Content-Type: application/json
Body: RetailMeetingCheckRequest

→ 202 Accepted { "request_id", "job_id" }   # 异步
→ 200 OK RetailMeetingCheckResponse                        # 同步

GET /v1/retail_meeting_checks/{request_id}?mode=simple|full → RetailMeetingCheckResponse
```

- **simple**（默认）：PE 展示——`asset_status` + `fail_reasons`（哪张不合格、原因）  
- **full**：AI debug——checks / OCR / evidence / debug 等尽量全  
异步回调 body 默认同 simple；可用 `options.response_mode`。详见 [PE接口文档-v1.8.md](PE接口文档-v1.8.md) §4.2。

---

## 总状态聚合规则

对 `rule_results`：

1. 任一系统级拉取失败且导致无法审核 → `overall_status = ERROR`（不记业务 FAIL）
2. 否则若存在 `status=FAIL` 且 `trigger_human=false` → `FAIL`
3. 否则若存在 `status=UNCERTAIN` 或 `trigger_human=true` → `NEED_HUMAN`
4. 其余适用规则均为 `PASS`/`SKIP` → `PASS`

`overall_confidence`：适用规则（非 SKIP）confidence 的最小值（或加权平均，实现选一种并在 `model_version` 文档固定）。

PE 映射：

| AI overall | PE meeting.status |
|------------|-------------------|
| PASS | PASS |
| FAIL | FAIL |
| NEED_HUMAN | NEED_HUMAN |
| ERROR | 保持 PENDING，告警重试；超过 N 次可转 NEED_HUMAN |

---

## RetailMeetingCheckRequest 示例（药师大讲堂）

```json
{
  "request_id": "req-hall-2-20260417-001",
  "meeting_id": 1002,
  "session_no": "2",
  "project_type": "LECTURE_HALL",
  "meeting_subtype": null,
  "period_id": 1,
  "form": {
    "meeting_name": "菁英药师大讲堂项目",
    "meeting_date": "2026-04-17",
    "start_time": "14:00",
    "end_time": "16:10",
    "chain_or_store_name": "河南美锐大药房连锁有限公司",
    "location": "信阳市六合春宴酒店（信阳师范大学店）",
    "total_attendees": 35,
    "speakers": [
      {
        "speaker_id": 1,
        "role_title": "讲师",
        "store_name": "美锐大药房",
        "speaker_name": "高芳",
        "topic": "从激素海洋到周期稳定",
        "service_minutes": 30,
        "fee": 800
      },
      {
        "speaker_id": 2,
        "speaker_name": "袁芳",
        "topic": "架起避孕之桥",
        "store_name": "美锐大药房",
        "service_minutes": 30
      },
      {
        "speaker_id": 3,
        "speaker_name": "刘亭",
        "topic": "常规避孕管理",
        "store_name": "美锐大药房",
        "service_minutes": 30
      },
      {
        "speaker_id": 4,
        "speaker_name": "余艳红",
        "topic": "闭经处理",
        "store_name": "美锐大药房",
        "service_minutes": 40
      }
    ]
  },
  "assets": [
    {
      "asset_id": 201,
      "asset_type": "POSTER",
      "s3_uri": "s3://pe-meetings/hall/2/poster.jpg",
      "content_type": "image/jpeg"
    },
    {
      "asset_id": 202,
      "asset_type": "STAND",
      "s3_uri": "s3://pe-meetings/hall/2/stand.jpg",
      "content_type": "image/jpeg"
    },
    {
      "asset_id": 203,
      "asset_type": "NAME_CARD",
      "s3_uri": "s3://pe-meetings/hall/2/name_card.jpg",
      "content_type": "image/jpeg"
    },
    {
      "asset_id": 204,
      "asset_type": "HANDBOOK",
      "s3_uri": "s3://pe-meetings/hall/2/handbook.jpg",
      "content_type": "image/jpeg"
    },
    {
      "asset_id": 210,
      "asset_type": "SPEAKER_PHOTO",
      "s3_uri": "s3://pe-meetings/hall/2/gaofang_1.jpg",
      "content_type": "image/jpeg",
      "speaker_id": 1,
      "speaker_shot_kind": "TITLE_GROUP"
    },
    {
      "asset_id": 211,
      "asset_type": "SPEAKER_PHOTO",
      "s3_uri": "s3://pe-meetings/hall/2/gaofang_2.jpg",
      "content_type": "image/jpeg",
      "speaker_id": 1,
      "speaker_shot_kind": "LECTURING"
    },
    {
      "asset_id": 220,
      "asset_type": "PANORAMA",
      "s3_uri": "s3://pe-meetings/hall/2/panorama.jpg",
      "content_type": "image/jpeg"
    },
    {
      "asset_id": 230,
      "asset_type": "SIGNIN",
      "s3_uri": "s3://pe-meetings/hall/2/signin_1.jpg",
      "content_type": "image/jpeg",
      "sort_no": 1
    }
  ],
  "refs": {
    "template_pack_version": "2026Q2",
    "logo_ref_s3": "s3://pe-templates/bayer_logo.png",
    "duplicate_search_scope": "period"
  },
  "options": {
    "clarity_threshold": 0.6,
    "human_confidence_threshold": 0.75,
    "watermark_time_skew_minutes": 120,
    "name_match_mode": "fuzzy"
  }
}
```

## RetailMeetingCheckRequest 示例（微型药师）

```json
{
  "request_id": "req-micro-000090-001",
  "meeting_id": 1090,
  "session_no": "000090",
  "project_type": "MICRO",
  "meeting_subtype": "SINGLE",
  "period_id": 2,
  "form": {
    "meeting_name": "单讲师",
    "meeting_date": "2026-05-27",
    "start_time": "14:00",
    "end_time": "14:35",
    "chain_or_store_name": "老百姓大药房连锁（安徽）有限公司",
    "location": "合肥市老百姓大药房连锁（安徽）有限公司淠河路店",
    "total_attendees": 7,
    "speakers": [
      {
        "speaker_id": 1,
        "speaker_name": "示例讲者",
        "topic": "慢病管理",
        "store_name": "淠河路店",
        "service_minutes": 30
      }
    ]
  },
  "assets": [
    {
      "asset_id": 301,
      "asset_type": "E_POSTER",
      "s3_uri": "s3://pe-meetings/micro/000090/agenda.png",
      "content_type": "image/png"
    },
    {
      "asset_id": 302,
      "asset_type": "E_POSTER_DISPLAY",
      "s3_uri": "s3://pe-meetings/micro/000090/display1.jpg",
      "content_type": "image/jpeg"
    },
    {
      "asset_id": 303,
      "asset_type": "PROJECT_INTRO_DISPLAY",
      "s3_uri": "s3://pe-meetings/micro/000090/intro.jpg",
      "content_type": "image/jpeg"
    },
    {
      "asset_id": 304,
      "asset_type": "SPEAKER_PHOTO",
      "s3_uri": "s3://pe-meetings/micro/000090/speaker.jpg",
      "content_type": "image/jpeg",
      "speaker_id": 1,
      "speaker_shot_kind": "TITLE_GROUP"
    },
    {
      "asset_id": 305,
      "asset_type": "PANORAMA",
      "s3_uri": "s3://pe-meetings/micro/000090/panorama.jpg",
      "content_type": "image/jpeg"
    },
    {
      "asset_id": 306,
      "asset_type": "SIGNIN",
      "s3_uri": "s3://pe-meetings/micro/000090/signin.pdf",
      "content_type": "application/pdf"
    }
  ],
  "refs": {
    "template_pack_version": "2026Q2",
    "duplicate_search_scope": "period"
  }
}
```

## RetailMeetingCheckResponse 示例（通过）

```json
{
  "request_id": "req-hall-2-20260417-001",
  "meeting_id": 1002,
  "job_id": 9001,
  "attempt_no": 1,
  "overall_status": "PASS",
  "overall_confidence": 0.91,
  "model_version": "pe-rmc-v1.0.0",
  "template_pack_version": "2026Q2",
  "summary_matched": [
    "日程海报日期/时间/地点与表单一致",
    "台卡四名与讲者名单一致",
    "海报与展架检出拜耳Logo",
    "全景人数≥35",
    "签到表时长>120分钟"
  ],
  "summary_failed": [],
  "need_human_reasons": [],
  "error": null,
  "asset_results": [
    {
      "asset_id": 203,
      "declared_type": "NAME_CARD",
      "detected_type": "NAME_CARD",
      "type_match": true,
      "clarity_score": 0.92,
      "is_blurry": false,
      "ocr_fields": {
        "speaker_names": ["余艳红", "刘亭", "袁芳", "高芳"]
      },
      "duplicate_hit": false
    }
  ],
  "rule_results": [
    {
      "rule_code": "NAME_CARD_SPEAKER_MATCH",
      "status": "PASS",
      "confidence": 0.93,
      "trigger_human": false,
      "reason_text": "识别到余艳红/刘亭/袁芳/高芳，与系统4名讲者集合一致",
      "evidence": {
        "names_ocr": ["余艳红", "刘亭", "袁芳", "高芳"],
        "names_expected": ["高芳", "袁芳", "刘亭", "余艳红"],
        "matched_by": "exact"
      },
      "related_asset_ids": [203]
    }
  ],
  "finished_at": "2026-04-18T10:00:00+08:00"
}
```

## RetailMeetingCheckResponse 示例（不合格）

```json
{
  "request_id": "req-hall-x-002",
  "meeting_id": 1009,
  "overall_status": "FAIL",
  "overall_confidence": 0.88,
  "summary_matched": ["拜耳Logo检出"],
  "summary_failed": ["台卡仅识别到3个姓名，缺少讲者「刘亭」", "全景合计人数28<35"],
  "need_human_reasons": [],
  "asset_results": [],
  "rule_results": [
    {
      "rule_code": "NAME_CARD_SPEAKER_MATCH",
      "status": "FAIL",
      "confidence": 0.9,
      "trigger_human": false,
      "reason_code": "NAME_SET_MISMATCH",
      "reason_text": "台卡姓名集合与系统讲者不一致：缺少刘亭",
      "evidence": {
        "names_ocr": ["余艳红", "袁芳", "高芳"],
        "missing": ["刘亭"]
      }
    },
    {
      "rule_code": "PANORAMA_COUNT",
      "status": "FAIL",
      "confidence": 0.85,
      "reason_code": "COUNT_BELOW_THRESHOLD",
      "reason_text": "全景合计人数28，低于阈值35",
      "evidence": { "count": 28, "threshold": 35 }
    }
  ]
}
```

## RetailMeetingCheckResponse 示例（需人工）

```json
{
  "request_id": "req-micro-y-003",
  "meeting_id": 1100,
  "overall_status": "NEED_HUMAN",
  "overall_confidence": 0.55,
  "summary_matched": [],
  "summary_failed": [],
  "need_human_reasons": ["项目介绍展示投影倾斜，OCR置信度低于阈值", "清晰度不足无法可靠判定签到时长"],
  "rule_results": [
    {
      "rule_code": "PPT_TEMPLATE_MATCH",
      "status": "UNCERTAIN",
      "confidence": 0.52,
      "trigger_human": true,
      "reason_code": "OCR_LOW_CONFIDENCE",
      "reason_text": "投影倾斜导致模版相似度处于灰区"
    },
    {
      "rule_code": "SIGNIN_DURATION",
      "status": "UNCERTAIN",
      "confidence": 0.4,
      "trigger_human": true,
      "reason_code": "BLURRY",
      "reason_text": "签到表模糊，无法可靠读取起止时间"
    }
  ],
  "asset_results": []
}
```

---

## 错误码

### HTTP / 网关层

| HTTP | 含义 |
|------|------|
| 400 | 请求 Schema 校验失败 |
| 401/403 | 鉴权失败 |
| 404 | `request_id` 不存在（查询时） |
| 409 | 幂等冲突策略异常（极少） |
| 429 | 限流 |
| 500 | AI 服务内部错误 |
| 503 | 依赖不可用（可重试） |

### `error.code` / 资产 `fetch_error.code`（系统，非业务 FAIL）

| code | retryable | 说明 |
|------|-----------|------|
| SCHEMA_INVALID | N | 请求字段不合规 |
| S3_NOT_FOUND | N | 对象不存在 |
| S3_ACCESS_DENIED | N | 无权限 |
| S3_TIMEOUT | Y | 拉取超时 |
| S3_CORRUPT | N | 无法解码图/PDF |
| ASSET_MISSING | N | 声明有 asset 但 URI 空/无效 |
| MODEL_TIMEOUT | Y | 推理超时 |
| MODEL_UNAVAILABLE | Y | 模型服务不可用 |
| TEMPLATE_PACK_NOT_FOUND | N | 指定模版版本不存在 |
| INTERNAL_ERROR | Y | 未知内部错误 |

### 业务 `reason_code`（规则 FAIL/UNCERTAIN）

见 [01-er-field-dictionary.md](01-er-field-dictionary.md) 中 `reason_code` 表。

---

## PE 提交前必传校验（非 AI）

提交进入 `PENDING` 前 PE 应拦截缺项，避免无意义 AI 调用：

**大讲堂：** E_POSTER、POSTER、STAND、NAME_CARD、HANDBOOK、每讲者 2 张 SPEAKER_PHOTO、PANORAMA≥1、SIGNIN≥1；讲者通常 4 人。

**微型：** E_POSTER、E_POSTER_DISPLAY、PROJECT_INTRO_DISPLAY、SPEAKER_PHOTO（单1/双2）、PANORAMA≥1、SIGNIN≥1。

AI 仍对「提交后 S3 读失败」返回 `ASSET_MISSING` / `S3_*`。
