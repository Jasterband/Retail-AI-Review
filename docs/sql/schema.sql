-- 药师会零售会议材料检查 · 参考 DDL（PostgreSQL / AWS RDS）
-- 本地开发可用 SQLite + ORM，表结构与下方 ai.* 对齐即可。
--
-- 说明：
-- 1) AI 服务库可只建 ai schema（或等价表），专门存检查中间结果与最终结果。
-- 2) pe.* 仅为对照 PE 业务实体的参考；AI 服务部署时可不建 pe 表。
-- 3) 最终结果：ai_check_job / ai_asset_result / ai_rule_result → 组装后返回 PE。
-- 4) 中间结果（debug）：建议另增 ai_step_log / ai_artifact，见 docs/技术选型与数据存储.md。
-- 5) 列名对齐 CRM/API：photo_id / photo_type / file_url；无 speaker_shot_kind。

CREATE SCHEMA IF NOT EXISTS pe;
CREATE SCHEMA IF NOT EXISTS ai;

-- ---------------------------------------------------------------------------
-- PE 业务
-- ---------------------------------------------------------------------------

CREATE TABLE pe.project_period (
  id              BIGSERIAL PRIMARY KEY,
  project_type    VARCHAR(32)  NOT NULL CHECK (project_type IN ('LECTURE_HALL', 'MICRO')),
  period_name     VARCHAR(100) NOT NULL,
  start_date      DATE         NOT NULL,
  end_date        DATE         NOT NULL,
  status          VARCHAR(16)  NOT NULL DEFAULT 'ACTIVE'
                    CHECK (status IN ('ACTIVE', 'CLOSED')),
  created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE TABLE pe.meeting (
  id                   BIGSERIAL PRIMARY KEY,
  session_no           VARCHAR(20)  NOT NULL,
  period_id            BIGINT       NOT NULL REFERENCES pe.project_period(id),
  project_type         VARCHAR(32)  NOT NULL CHECK (project_type IN ('LECTURE_HALL', 'MICRO')),
  meeting_name         VARCHAR(50)  NOT NULL,
  meeting_subtype      VARCHAR(16)  CHECK (meeting_subtype IS NULL OR meeting_subtype IN ('SINGLE', 'DUAL')),
  meeting_date         DATE         NOT NULL,
  start_time           TIME         NOT NULL,
  end_time             TIME         NOT NULL,
  chain_or_store_name  VARCHAR(50)  NOT NULL,
  meeting_location     VARCHAR(200) NOT NULL,
  remark               VARCHAR(200),
  total_attendees      INT          NOT NULL CHECK (total_attendees >= 0),
  other_fee            NUMERIC(12,2),
  status               VARCHAR(16)  NOT NULL DEFAULT 'DRAFT'
                         CHECK (status IN ('DRAFT', 'PENDING', 'PASS', 'FAIL', 'NEED_HUMAN', 'CLOSED')),
  status_version       INT          NOT NULL DEFAULT 0,
  ai_check_count       INT          NOT NULL DEFAULT 0,
  latest_ai_overall    VARCHAR(16)  CHECK (latest_ai_overall IS NULL
                         OR latest_ai_overall IN ('PASS', 'FAIL', 'NEED_HUMAN', 'ERROR')),
  latest_ai_summary    JSONB,
  latest_job_id        BIGINT,
  created_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  updated_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  CONSTRAINT uq_meeting_session_no UNIQUE (session_no)
);

CREATE INDEX idx_meeting_period_status ON pe.meeting(period_id, status);
CREATE INDEX idx_meeting_type_date ON pe.meeting(project_type, meeting_date);

CREATE TABLE pe.speaker (
  id               BIGSERIAL PRIMARY KEY,
  meeting_id       BIGINT       NOT NULL REFERENCES pe.meeting(id) ON DELETE CASCADE,
  sort_no          INT          NOT NULL DEFAULT 1,
  role_title       VARCHAR(10)  NOT NULL,
  store_name       VARCHAR(50)  NOT NULL,
  speaker_name     VARCHAR(20)  NOT NULL,
  topic            VARCHAR(50)  NOT NULL,
  service_minutes  INT          NOT NULL CHECK (service_minutes > 0),
  lecture_fee      NUMERIC(12,2) NOT NULL,
  tax              NUMERIC(12,2)
);

CREATE INDEX idx_speaker_meeting ON pe.speaker(meeting_id);

-- 会议材料：概念对齐 CRM Photo / API photos[]（photo_id 对外为字符串）
CREATE TABLE pe.meeting_asset (
  id                 BIGSERIAL PRIMARY KEY,
  meeting_id         BIGINT       NOT NULL REFERENCES pe.meeting(id) ON DELETE CASCADE,
  photo_type         VARCHAR(32)  NOT NULL,
  sort_no            INT          NOT NULL DEFAULT 1,
  file_url           VARCHAR(512) NOT NULL,
  content_type       VARCHAR(64)  NOT NULL,
  file_size_bytes    BIGINT,
  speaker_id         BIGINT       REFERENCES pe.speaker(id) ON DELETE SET NULL,
  created_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_asset_meeting_type ON pe.meeting_asset(meeting_id, photo_type);

-- ---------------------------------------------------------------------------
-- AI 审核
-- ---------------------------------------------------------------------------

CREATE TABLE ai.template_ref (
  id            BIGSERIAL PRIMARY KEY,
  project_type  VARCHAR(32)  NOT NULL CHECK (project_type IN ('LECTURE_HALL', 'MICRO')),
  template_kind VARCHAR(32)  NOT NULL,
  period_id     BIGINT       REFERENCES pe.project_period(id),
  s3_uri        VARCHAR(512) NOT NULL,  -- 模版 pack 内部路径；非请求 file_url
  version       VARCHAR(32)  NOT NULL,
  crop_meta     JSONB,
  is_active     BOOLEAN      NOT NULL DEFAULT TRUE,
  created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_template_active ON ai.template_ref(project_type, template_kind, version)
  WHERE is_active;

CREATE TABLE ai.ai_check_job (
  id                     BIGSERIAL PRIMARY KEY,
  meeting_id             VARCHAR(36)  NOT NULL,  -- 对齐 CRM MeetingID / API string
  attempt_no             INT          NOT NULL,
  task_id                VARCHAR(50)  NOT NULL,  -- 对齐 CRM TaskID / API task_id ≤50
  pe_snapshot            JSONB        NOT NULL,
  overall_status         VARCHAR(16)  CHECK (overall_status IS NULL
                           OR overall_status IN ('PASS', 'FAIL', 'NEED_HUMAN', 'ERROR')),
  overall_confidence     REAL,
  model_version          VARCHAR(64),
  template_pack_version  VARCHAR(32),
  started_at             TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  finished_at            TIMESTAMPTZ,
  error_code             VARCHAR(64),
  error_message          TEXT,
  CONSTRAINT uq_ai_task_id UNIQUE (task_id),
  CONSTRAINT uq_ai_meeting_attempt UNIQUE (meeting_id, attempt_no)
);

CREATE TABLE ai.ai_asset_result (
  id                       BIGSERIAL PRIMARY KEY,
  job_id                   BIGINT       NOT NULL REFERENCES ai.ai_check_job(id) ON DELETE CASCADE,
  photo_id                 VARCHAR(36)  NOT NULL,  -- 对齐 CRM PhotoID / API string
  photo_type               VARCHAR(32),
  detected_type            VARCHAR(32),
  type_match               BOOLEAN,
  clarity_score            REAL,
  is_blurry                BOOLEAN,
  ocr_fields               JSONB,
  detections               JSONB,
  topic_reuse_hit            BOOLEAN      DEFAULT FALSE,
  topic_reuse_ref_session_no VARCHAR(20),
  topic_text_ocr             TEXT
);

CREATE INDEX idx_asset_result_job ON ai.ai_asset_result(job_id);

CREATE TABLE ai.ai_rule_result (
  id                 BIGSERIAL PRIMARY KEY,
  job_id             BIGINT       NOT NULL REFERENCES ai.ai_check_job(id) ON DELETE CASCADE,
  rule_code          VARCHAR(64)  NOT NULL,
  status             VARCHAR(16)  NOT NULL
                       CHECK (status IN ('PASS', 'FAIL', 'SKIP', 'UNCERTAIN')),
  confidence         REAL,
  trigger_human      BOOLEAN      NOT NULL DEFAULT FALSE,
  reason_code        VARCHAR(64),
  reason_text        TEXT,
  evidence           JSONB,
  related_photo_ids  VARCHAR(36)[]
);

CREATE INDEX idx_rule_result_job ON ai.ai_rule_result(job_id, rule_code);

-- 照片盗用/跨会议混用：历史图像指纹（只与其他会议比，不查会内）
CREATE TABLE ai.image_dup_history (
  id                 BIGSERIAL PRIMARY KEY,
  meeting_id         VARCHAR(36)  NOT NULL,
  session_no         VARCHAR(20),
  period_id          VARCHAR(36),
  photo_id           VARCHAR(36),
  photo_type         VARCHAR(32),
  phash              VARCHAR(64)  NOT NULL,       -- 感知哈希
  embedding          BYTEA,                       -- 可选；生产建议 pgvector
  created_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_image_dup_phash
  ON ai.image_dup_history(period_id, phash);

CREATE INDEX idx_image_dup_meeting
  ON ai.image_dup_history(meeting_id);

-- 主题不重复：仅讲者照 OCR 出的讲题/标题（文字，非图像）
CREATE TABLE ai.topic_history (
  id                 BIGSERIAL PRIMARY KEY,
  meeting_id         VARCHAR(36),
  session_no         VARCHAR(20),
  period_id          VARCHAR(36),
  photo_id           VARCHAR(36),
  speaker_name       VARCHAR(20)  NOT NULL,
  topic_raw          VARCHAR(200) NOT NULL,
  topic_normalized   VARCHAR(200) NOT NULL,
  created_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_topic_history_period_speaker
  ON ai.topic_history(period_id, speaker_name, topic_normalized);

CREATE INDEX idx_topic_history_period_norm
  ON ai.topic_history(period_id, topic_normalized);

-- 回填 meeting.latest_job_id 外键（可选）
ALTER TABLE pe.meeting
  ADD CONSTRAINT fk_meeting_latest_job
  FOREIGN KEY (latest_job_id) REFERENCES ai.ai_check_job(id);
