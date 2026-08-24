# Protokflow 데이터베이스 스키마 설계

> 대상 릴리스: `protokflow` 0.1.0
> 관련 문서: [디자인 토큰 아키텍처](./token-3tier-architecture.md) · [Protokflow 서버 플랜](../plans/2026-08-20-protokflow-server-plan.md)

이 문서는 저장소 계층(`backend/app/protokflow/model/`)의 영속 데이터 모델 및 저장 경계, 동기화 정책을 정의한다. 플랜의 요구사항(R16~R23)과 설계 결정(KD6~KD8)을 반영한 단일 소스 명세다.

---

## 0. 용어

| 용어 | 정의 | 비고 / 주의 |
|---|---|---|
| **레포 / 프로젝트** | SQLite DB 1개의 격리 범위. 테이블로 모델링하지 않는다(§1-1). | 독립된 레포지토리/프로젝트 작업 범위를 의미하며 별도 테이블로 모델링하지 않는다. |
| **디자인 시스템** (`design_systems`) | `DESIGN.md` 1개에 대응하는 1개 엔티티(`default`, `admin-dark` 등). 독립 완결 문서이며 상속 없이 동등한 형제 관계를 갖는다(§5.2). | 독립된 토큰 네임스페이스와 스타일 가이드를 소유하는 단위. |
| **파생 디자인 시스템** (derived) | 기존 디자인 시스템으로부터 분기된 실험용 엔티티. `derived_from_id`로 출처를 추적하되 토큰은 완전 해석된 상태로 독립 관리된다. | 상속 모델이 아니며, 자체 토큰 트리를 독립적으로 완결하여 보유한다. |
| **후보** (`candidates`) | 단일 런(`prototype_runs`) 내에서 나란히 비교하는 개별 화면 변형(`c1`, `c2`). 뷰포트 매트릭스(R11)의 표시 단위. | 디자인 시스템 단위의 실험(파생)과 구분되는 화면 수준의 레이아웃/토큰 변형 단위. |

---

## 1. 설계 목표

1. **에이전트 1회 호출 = DB 1회 트랜잭션.** 도구 호출 하나가 여러 테이블에 걸친 다단계 의례(제안 → 승인 → 승격)를 요구하지 않는다. (SC1)
2. **재현 가능성은 스냅샷으로 확보한다.** 해시 체인·리비전 그래프 없이, 런 생성 시점의 토큰 상태를 그대로 영속화한다.
3. **파생 가능한 것은 저장하지 않는다.** 렌더링이 1ms 이내(R2)이므로 HTML은 캐시 대상이 아니다.
4. **SQLite 단일 파일에서 무설정으로 동작한다.** Postgres 이관 경로는 열어두되, 표준 SQL 호환성과 타입 안전성을 보장하는 선에서 설계한다(§8). (KD6)
5. **스키마가 3계층 토큰 모델을 그대로 반영한다.** Layer 1/2는 디자인 시스템에, Layer 3는 런/후보에 귀속된다.
6. **DB는 소멸 가능하다.** 아래 §1-1 불변식을 어기는 컬럼을 추가하지 않는다.

### 1-1. 저장소 위상 불변식

```
DB = f(DESIGN.md) + 소멸 가능한 런 이력
```

- **레포지토리 단위 격리 SQLite DB**: `.protokflow/protokflow.db`는 레포지토리에 격리되며 Git 추적에서 제외(gitignore)된다(바이너리 및 WAL 파일의 충돌 방지).
- **DB는 작업 저장소, `DESIGN.md` 파일은 Git 기반 팀 동기화 채널**: 모든 읽기/렌더링과 쓰기(`/admin` 편집)는 DB를 거치며, 파일 시스템의 `DESIGN.md`는 투영본으로서 상시 동기화 상태를 유지한다(§6 write-through).
- **재인덱싱 기반 복구성**: DB 파일이 손상되거나 삭제되더라도 `DESIGN.md` 파일들로부터 디자인 시스템과 토큰 데이터를 완전 복구할 수 있다. (단, 파일에 포함되지 않는 임시 런/패치 이력은 소멸을 허용한다.)

---

## 2. 설계 원칙 및 비포함 아키텍처 사양

에이전트와의 초저지연 상호작용 및 단일 호출 완결성(SC1)을 위해, 불필요한 트랜잭션 오버헤드를 유발하는 구조를 배제하고 다음 원칙에 따라 데이터 모델을 간결하게 유지한다.

| 배제 영역 | 설계 Rationale |
|---|---|
| **콘텐츠 주소화 아티팩트 저장소** | 프로토타입 HTML은 템플릿과 토큰을 통해 1ms 이내에 결정론적으로 재생성되는 파생물이므로 별도 아티팩트 해시 테이블을 두지 않는다. |
| **DB 레벨 권위/리비전 그래프** | 디자인 시스템 토큰은 최신 활성 상태 1개만 관리하며, 영속적인 변경 이력 및 버전 관리는 Git에 위임한다. |
| **2단계 승격 프로토콜** | 불필요한 다단계 제안/승인 절차를 배제하고 관리 UI 및 에이전트 승격 명령을 단일 트랜잭션으로 즉시 반영한다. |
| **임대/펜스 분산 동시성 제어** | 트랜잭션이 단일 도구 호출 단위로 완결되므로 SQLite WAL 모드와 `busy_timeout`으로 동시성을 충분히 제어한다(§6 동시성). |
| **상태 전이 이력 테이블** | 수명주기 상태 머신은 Pydantic v2 Enum(KD4) 단일 소스로 관리하며 DB에 중복 모델링하지 않는다. |
| **범용 이벤트 저널** | 조회 요구가 명확한 토큰 패치 이력 전용 테이블(`token_patches`)만 유지하여 단순성을 확보한다. |
| **시맨틱 요소 식별자 체계** | 화면 요소의 복잡한 영속 식별자 및 툼스톤 관리는 현재 제품 범위에서 제외한다. |

`design_systems.source_digest`는 무결성 암호화 증명이 아닌 외부 파일 변경(`git pull`, 브랜치 전환 등) 감지를 위한 목적으로 유지된다(§6 상시 선검사).

---

## 3. 저장 경계

| 데이터 | 위치 | 근거 |
|---|---|---|
| 디자인 시스템, 토큰, 런, 후보, 패치 이력 | **SQLite / Postgres** | 조회·편집·이력 요구가 있는 정규 상태. |
| `DESIGN.md` 문서 | **DB(정본 작업본) + 레포 파일(투영본, Git 커밋 대상)** | DB가 편집 대상이고 파일은 동기화 채널이다(§1-1). 파일을 유지함으로써 팀 공유·PR 리뷰·표준 상호운용성을 확보한다. |
| 데몬 PID / 동적 포트 | `.protokflow/daemon.json` (파일) | 프로세스 수명주기 자산(R8). 파일 기반 락으로 관리하여 프로세스 비정상 종료 시 좀비 레코드 잔존을 방지한다. |
| WebSocket 연결, 구독 중인 뷰포트 | **인메모리** | 프로세스 종료와 함께 소멸하는 것이 정확한 동작(R9). |
| 렌더링된 HTML/CSS | **비영속** (요청 시 생성) | 1ms 이내 생성 가능한 파생물(§1-3). |
| 스냅샷 이미지(R6) | `.protokflow/snapshots/*.png` (파일), 경로만 DB | 대용량 바이너리 BLOB을 DB에서 분리하여 DB 파일 크기 비대화를 방지한다. |
| 내보낸 React/Vue 코드 | 사용자 레포지토리 파일 시스템에 직접 기록 (DB는 메타만 저장) | 코드의 단일 소스는 사용자 레포지토리다. |

---

## 4. 엔티티 관계

```text
                    ┌──────────────────┐
                    │  schema_meta     │  (key/value, 스키마 버전)
                    └──────────────────┘

┌───────────────────────────┐        1     N   ┌──────────────────────────┐
│  design_systems           │──────────────────│  design_tokens           │
│  DESIGN.md 1개 = 1행      │                  │  Layer 1/2 정규화 토큰    │
│  guide_markdown, digest   │                  │  UNIQUE(ds, token_path)  │
└─────────────┬─────────────┘                  └──────────────────────────┘
              │ 1
              │ N
┌─────────────▼─────────────┐        1     N   ┌──────────────────────────┐
│  prototype_runs           │──────────────────│  candidates              │
│  layout_preset            │                  │  Layer 3 pattern 토큰     │
│  token_snapshot (스냅샷)  │                  │  initial / overrides     │
└───────────────────────────┘                  └────────────┬─────────────┘
                                                            │ 1
                               ┌─────────────────────────────┼───────────────┐
                               │ N                           │ N             │ N
                   ┌───────────▼──────────┐   ┌──────────────▼──────┐  ┌─────▼──────┐
                   │  token_patches       │   │  slot_contents      │  │  exports   │
                   │  append-only 이력    │   │  슬롯 커스텀 텍스트  │  │  방출 기록  │
                   └──────────────────────┘   └─────────────────────┘  └────────────┘
```

`design_systems.derived_from_id`는 같은 테이블을 가리키는 자기참조(출처 추적용)이다.

---

## 5. 테이블 정의

DDL은 SQLite 기준의 논리 스키마이며, 실제 정의는 SQLAlchemy 2.0 모델(`backend/app/protokflow/model/`)이 단일 소스이다(§8). 공통 규약:

- **기본키**: `TEXT` ULID(사전순 정렬 = 생성순). 정수 자동증가는 패치 이력 테이블(`token_patches`)에만 한정한다.
- **공통 감사 컬럼 (`Base`)**: 모든 테이블은 `backend/common/model.py`의 `Base`(`DateTimeMixin` + `LogicalDeleteMixin`)를 상속하여 `created_time`(생성 시각), `updated_time`(NULL 허용, 갱신 시 자동 기록), `deleted`(기본 `0`, 논리 삭제 표식), `deleted_time`을 공통 보유한다. 아래 테이블 정의에는 도메인 컬럼만 기재한다.
- **타임스탬프**: 감사 컬럼(`created_time`/`updated_time`/`deleted_time`)은 공통 `Base`의 `TimeZone` 타입(`DateTime(timezone=True)`, `DATETIME_TIMEZONE` 기준 aware)으로 매핑한다. 도메인 타임스탬프(`design_systems.synced_at`)는 `Timestamp`(naive 거부, UTC 정규화)를 사용한다(§8). SQLite는 ISO-8601 TEXT, Postgres는 `timestamptz`로 저장된다.
- **JSON 컬럼**: `sa.JSON`(SQLite TEXT ↔ Postgres `jsonb`). 인덱싱 대상이 아닌 소규모 구조에만 사용한다.
- **삭제**: 소유 관계는 모두 `ON DELETE CASCADE`. SQLite 커넥션마다 `PRAGMA foreign_keys=ON`을 적용한다. `deleted` 플래그는 런 프루닝·아카이빙 등 소프트 삭제 표식용이며, FK 참조 무결성은 여전히 물리 CASCADE로 처리된다.
- **제약 이름**: 모든 CHECK/UNIQUE/FK/Index에 명시적 이름을 부여한다. SQLAlchemy `MetaData(naming_convention=...)` 규칙(`ck_`, `uq_`, `fk_`, `ix_` 접두사)을 강제하여 마이그레이션 도구(Alembic) 도입 시 가짜 변경 감지를 방지한다.
- **AUTOINCREMENT**: 정수 키를 쓰는 테이블에는 `sqlite_autoincrement=True`를 명시하여 삭제된 rowid 재사용으로 인한 순서 왜곡을 차단한다.

### 5.1 `schema_meta`

```sql
CREATE TABLE schema_meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
-- 초기 행: ('schema_version', '1')
```

테이블·클래스명은 `schema_meta`(`SchemaMeta`)를 사용한다. 공통 감사 컬럼(§5 공통 규약)을 포함한다.

부팅 시 `schema_version`을 읽어 코드가 기대하는 버전과 비교한다. 초기 버전은 Alembic 없이 `create_all` + 버전 검사로 운영하고, 파괴적 변경이 필요한 시점에 마이그레이션 도구를 도입한다(§9).

### 5.2 `design_systems`

```sql
CREATE TABLE design_systems (
  id              TEXT      PRIMARY KEY,
  slug            TEXT      NOT NULL UNIQUE,      -- 'default', 'admin-dark'
  title           TEXT      NOT NULL,              -- Front Matter `name`
  description     TEXT,                            -- Front Matter `description`
  spec_version    TEXT,                            -- Front Matter `version` (현재 'alpha')
  derived_from_id TEXT      REFERENCES design_systems(id) ON DELETE SET NULL,
  front_matter_extras JSON  NOT NULL DEFAULT '{}', -- 모델링하지 않은 최상위 키 원문 보존
  front_matter_raw TEXT     NOT NULL DEFAULT '',  -- Front Matter 원문(주석·정렬·따옴표 포함)
  guide_markdown  TEXT      NOT NULL DEFAULT '',  -- DESIGN.md 본문(Front Matter 제외)
  source_path     TEXT,                           -- 대응하는 DESIGN.md 파일 경로
  source_digest   TEXT,                           -- 마지막 동기화 시점 파일의 sha256
  source_mtime    REAL,                           -- mtime (선검사용)
  source_size     INTEGER,                        -- 크기  (선검사용)
  synced_at       TIMESTAMP
);
```

- `slug`는 사용자와 에이전트가 도구 인자로 전달하는 식별자(`design_system: "admin-dark"`)이므로 고유해야 한다. 내부 외래키 참조는 `id`를 사용한다.
- **Front Matter 키 매핑**: `name` → `title`, `description` → `description`, `version` → `spec_version`. 토큰 그룹(`colors`/`typography`/`rounded`/`spacing`/`components`)은 `design_tokens`로 정규화한다.
- **`front_matter_extras`는 무손실 라운드트립을 위한 컬럼이다.** DESIGN.md 스펙이 정의한 `omitted`(생략 섹션 선언) 및 커스텀 확장 키를 원문 그대로 보존하여 파일 export 시 공식 린터(`@google/design.md`) 규격을 충족한다.
- **`front_matter_raw`는 in-place 패치 write-through의 기반이다.** Front Matter 원문을 주석, 빈 줄, 따옴표 스타일, 키 순서까지 바이트 단위로 보존한다. 저장 시 이 원문을 라운드트립 파서로 읽어 대상 토큰 위치만 치환하므로 Git diff 최소화(단일 토큰 변경 시 1줄 diff) 및 사용자 서식 보존을 보장한다. 정규화된 행 기반 직렬화 재생성 방식과 달리 불필요한 diff 노이즈를 차단한다. 파일 미연동 시스템은 생성 시점에 1회 직렬화하여 이 컬럼을 초기화한다.
- `guide_markdown`은 `design://systems/{slug}` 리소스로 반환되어 에이전트의 프롬프트 컨텍스트가 된다.
- `source_path`가 NULL인 디자인 시스템은 **DB 전용**(파일 미연동)이다. 파생 디자인 시스템은 기본적으로 DB 전용으로 생성되어 Git 트리를 오염시키지 않으며, 필요 시 명시적 export를 통해 `design/{slug}.md` 파일로 변환된다.
- `derived_from_id`는 **출처(provenance) 추적용 메타데이터**이다. 파생 시스템도 완전 해석된 자기완결 토큰 트리를 가지며, `promote_tokens`의 원본 병합 대상 식별 및 `/admin` UI의 diff 표시에 사용된다.
- `source_mtime`/`source_size`는 도구 호출 시 파일 변경 여부를 저비용(`stat`)으로 선검사하여 해시 계산 오버헤드를 회피하는 용도이다(§6).

#### 디자인 시스템 형제 모델 및 독립 완결성 규약

[DESIGN.md 스펙](https://github.com/google-labs-code/design.md)에는 계층적 상속(`extends`/`inherits`)이나 오버라이드 규약이 존재하지 않으며, 린트 규칙 `broken-ref`는 모든 토큰 참조가 단일 파일 내에서 완결될 것을 요구한다. 따라서 Protokflow는 디자인 시스템을 상속 관계가 아닌 동등한 **형제 관계의 자기완결 문서**로 모델링한다.

| 항목 | 토큰 해석용 상속 (배제) | 출처 추적 `derived_from_id` (채택) |
|---|---|---|
| 토큰 참조 완결성 | 불완전 (부모 토큰 참조 필요) | 완전 (자체 토큰 트리 독립 완결) |
| `broken-ref` 린트 | 실패 | 통과 |
| 부모 삭제 시 동작 | 자식 시스템 오류 발생 | `SET NULL`, 자식 시스템 정상 유지 |
| 주요 용도 | 런타임 값 상속 | 병합(merge) 대상 식별, diff 표시 |

**파일 배치 규약**:

```
repo/
├─ DESIGN.md          → slug 'default'   (스펙의 기본 위치)
├─ design/
│  ├─ admin-dark.md   → slug 'admin-dark'
│  └─ mobile.md       → slug 'mobile'
└─ .protokflow/protokflow.db   (gitignore)
```

탐색 범위는 레포지토리 루트와 `design/` 디렉토리로 한정한다.

### 5.3 `design_tokens` (Layer 1/2)

```sql
CREATE TABLE design_tokens (
  id           TEXT      PRIMARY KEY,
  design_system_id TEXT      NOT NULL REFERENCES design_systems(id) ON DELETE CASCADE,
  tier         TEXT      NOT NULL CONSTRAINT ck_design_tokens_tier
                         CHECK (tier IN ('foundation', 'component')),
  token_path   TEXT      NOT NULL,   -- 'colors.primary', 'components.button-primary.rounded'
  value        TEXT      NOT NULL,   -- 리터럴 또는 참조 표현식 '{colors.primary}'
  origin       TEXT      NOT NULL DEFAULT 'design_md' CONSTRAINT ck_design_tokens_origin
                         CHECK (origin IN ('design_md', 'admin_ui', 'agent')),
  CONSTRAINT uq_design_tokens_ds_path UNIQUE (design_system_id, token_path)
);
CREATE INDEX ix_design_tokens_ds_tier ON design_tokens (design_system_id, tier);
```

- **행 단위 정규화**: 개별 토큰 PATCH 시의 경합을 제거하고, `UNIQUE(design_system_id, token_path)`로 경로 중복을 방지하며, 시스템 간 diff 조회를 단순화한다.
- **원문 값 보존**: `{colors.primary}` 참조의 해석 및 순환 참조 검출은 코어 엔진(`protokflow.core`)의 캐스케이드 해석기 책임이며(R1), DB는 원문 문자열을 그대로 저장한다.
- `tier`는 계층별 조회(`:root` CSS 변수 생성 시 foundation 우선 정렬 등)를 지원하기 위한 인덱싱 컬럼이다.

### 5.4 `prototype_runs`

```sql
CREATE TABLE prototype_runs (
  id             TEXT      PRIMARY KEY,
  design_system_id   TEXT      NOT NULL REFERENCES design_systems(id) ON DELETE CASCADE,
  screen_goal    TEXT      NOT NULL,
  layout_preset  TEXT      NOT NULL,               -- 'split-card', 'centered-modal', ...
  variation_axes JSON      NOT NULL DEFAULT '[]',  -- ["pattern.layout.mode"]
  token_snapshot JSON      NOT NULL,               -- 해석 완료된 Layer 1/2 평면 맵
  status         TEXT      NOT NULL DEFAULT 'active' CONSTRAINT ck_prototype_runs_status
                           CHECK (status IN ('active', 'exported', 'archived'))
);
CREATE INDEX ix_prototype_runs_ds_created ON prototype_runs (design_system_id, created_time);
```

- **`token_snapshot`**: 런 생성 시점에 디자인 시스템 토큰을 캐스케이드 해석한 결과를 그대로 스냅샷으로 영속화한다. 이후 디자인 시스템 토큰이 변경되더라도 기존 런의 프리뷰와 내보내기 결과는 불변으로 유지되며, 복잡한 리비전 그래프 없이도 렌더링 재현성을 보장한다.
- `design_system_id`는 출처 추적 및 `/admin`의 시스템별 런 목록 필터링을 위해 유지한다.

### 5.5 `candidates` (Layer 3)

```sql
CREATE TABLE candidates (
  run_id          TEXT      NOT NULL REFERENCES prototype_runs(id) ON DELETE CASCADE,
  candidate_key   TEXT      NOT NULL,               -- 에이전트가 지정한 'c1', 'c2'
  label           TEXT      NOT NULL,
  position        INTEGER   NOT NULL DEFAULT 0,     -- 뷰포트 매트릭스 정렬 순서
  initial_tokens  JSON      NOT NULL DEFAULT '{}',  -- 생성 시 Layer 3 파라미터
  token_overrides JSON      NOT NULL DEFAULT '{}',  -- 패치 누적 후 현재 유효값
  snapshot_path   TEXT,                             -- .protokflow/snapshots/*.png
  PRIMARY KEY (run_id, candidate_key)
);
```

- 후보 식별자는 에이전트가 지정한 키(`c1`, `c2`)와 `run_id`의 복합 기본키 `(run_id, candidate_key)`로 구성한다.
- `initial_tokens`와 `token_overrides`를 함께 유지하여, 현재 유효 상태 조회(오버라이드 단일 읽기)와 초기화 복원(initial 복사)을 모두 O(1)로 처리한다.
- **후보의 최종 유효 토큰** = `runs.token_snapshot` ← `candidates.token_overrides` (덮어쓰기).

### 5.6 `token_patches`

```sql
CREATE TABLE token_patches (
  seq            INTEGER   PRIMARY KEY AUTOINCREMENT,  -- 단조 증가 = 적용 순서
  run_id         TEXT      NOT NULL,
  candidate_key  TEXT      NOT NULL,
  token_path     TEXT      NOT NULL,
  previous_value TEXT,                                 -- NULL = 신규 오버라이드
  next_value     TEXT      NOT NULL,
  origin         TEXT      NOT NULL CONSTRAINT ck_token_patches_origin
                           CHECK (origin IN ('agent', 'admin_ui')),
  FOREIGN KEY (run_id, candidate_key)
    REFERENCES candidates (run_id, candidate_key) ON DELETE CASCADE
);
CREATE INDEX ix_token_patches_target ON token_patches (run_id, candidate_key, seq);
```

- **추가 전용(append-only) 이력 테이블**: 되돌리기(undo), 작업 회고, 확정 시 변경 요약 생성을 위해 패치 로그를 보존한다.
- 행이 한 번 삽입되면 갱신되지 않으므로 `updated_time`은 NULL, `deleted`는 `0`으로 유지된다(공통 감사 컬럼은 스키마에 존재하나 이 테이블에서는 미사용).
- 현재 상태 읽기는 `candidates.token_overrides`에서 수행하며, 패치 로그 역재생을 통한 상태 계산은 수행하지 않는다.
- `seq`는 `sqlite_autoincrement=True`를 적용하여 삭제된 rowid 재사용으로 인한 순서 왜곡을 방지한다.

### 5.7 `slot_contents`

```sql
CREATE TABLE slot_contents (
  run_id        TEXT      NOT NULL,
  candidate_key TEXT      NOT NULL,
  slot_key      TEXT      NOT NULL,   -- 'headline', 'cta-label', 'form-fields'
  content       TEXT      NOT NULL,
  content_kind  TEXT      NOT NULL DEFAULT 'text' CONSTRAINT ck_slot_contents_kind
                          CHECK (content_kind IN ('text', 'html', 'markdown')),
  PRIMARY KEY (run_id, candidate_key, slot_key),
  FOREIGN KEY (run_id, candidate_key)
    REFERENCES candidates (run_id, candidate_key) ON DELETE CASCADE
);
```

- `update_slot_custom` 도구(R5)의 저장소로, 덮어쓰기(upsert) 방식으로 동작한다.
- `content_kind`는 템플릿 렌더링 시 이스케이프 정책을 결정한다. `html` 모드는 명시적 요청 시에만 허용되며 렌더러가 새니타이즈를 수행한다.

### 5.8 `exports`

```sql
CREATE TABLE exports (
  id            TEXT      PRIMARY KEY,
  run_id        TEXT      NOT NULL,
  candidate_key TEXT      NOT NULL,
  format        TEXT      NOT NULL CONSTRAINT ck_exports_format
                          CHECK (format IN ('react-tailwind', 'vue-tailwind',
                                            'html-css', 'json-tokens')),
  output_path   TEXT,                    -- 파일 경로(기록 가능한 경우)
  byte_size     INTEGER,
  FOREIGN KEY (run_id, candidate_key)
    REFERENCES candidates (run_id, candidate_key) ON DELETE CASCADE
);
```

방출된 코드 본문은 사용자 레포지토리에 저장되며, DB에는 어떤 후보가 어떤 포맷으로 코드화되었는지에 대한 메타데이터만 기록하여 런 상태를 `exported`로 관리한다.

---

## 6. 쓰기 경로

| 트리거 | 트랜잭션 (단일) |
|---|---|
| 파일 → DB 재인덱싱 (R16) | `design_systems` upsert + `design_tokens` 전량 동기화 |
| `/admin` 토큰 편집 (R18) | `design_tokens` update(`origin='admin_ui'`) + `DESIGN.md` write-through |
| `create_prototype_run` (R5) | `prototype_runs` insert(스냅샷 포함) + `candidates` N행 insert |
| `patch_tokens` (R10) | `token_patches` N행 insert + `candidates.token_overrides` update |
| `update_slot_custom` (R5) | `slot_contents` upsert |
| `export_prototype` (R14) | `exports` insert + `prototype_runs.status='exported'` |
| `promote_tokens` — 신규 타깃 | `design_systems` insert(`derived_from_id` 설정, `source_path=NULL`) + `design_tokens` N행 insert |
| `promote_tokens` — 기존 타깃 | `design_tokens` N행 upsert(`origin='agent'`) + 타깃이 파일 연동이면 write-through |
| DB → 파일 export (R16) | `design_systems`(`source_path`, 동기화 메타) update |

모든 도구 호출은 단일 트랜잭션으로 처리된다(§1 목표 1). 쓰기 트랜잭션의 소유권은 서비스 계층에 일원화되며, MCP/HTTP 어댑터는 DB 세션을 직접 제어하지 않는다.

### 파일 → DB 상시 선검사

`DESIGN.md`는 도구 호출 외에도 `git pull`, 브랜치 전환, fresh clone, 파일 직접 수정 등 다양한 경로로 변경될 수 있다.

따라서 매 도구 호출 시 **대응 파일의 `(mtime, size)`를 선검사**하고, 불일치 시에만 sha256을 계산해 `source_digest`와 비교한 후 재인덱싱을 수행한다. `stat` 기반 선검사는 마이크로초 단위로 완료되므로 오버헤드가 없으며, 파일 워처 데몬 없이도 일관성을 유지한다.

진행 중인 프리뷰는 실행 시점의 `prototype_runs.token_snapshot`을 참조하므로 재인덱싱의 영향을 받지 않는다.

### 인덱싱 시 YAML 앵커 거부

인덱싱 시 Front Matter에 YAML 앵커(`&name`) 또는 별칭(`*name`)이 존재하면 **명시적 오류로 거부**하고, `{colors.primary}` 형식의 스펙 참조 문법으로 변환할 것을 안내한다.

DESIGN.md 표준 스펙은 참조 문법으로 `{path.to.token}` 문자열 포맷만을 규정한다. YAML 앵커 및 별칭은 로드 시점에 파서에 의해 사전 역참조(dereference)되므로, 대상 토큰을 in-place 패치할 때 별칭 노드가 정적 값으로 고착화되어 참조 무결성이 단절된다. 이러한 묵시적 참조 손상을 방지하기 위해 파일 인덱싱 시점에 YAML 앵커 검출 시 즉시 처리를 중단하고 오류를 반환한다.

### 동시성

하나의 MCP 프로세스 내에서 MCP 어댑터와 ASGI 프리뷰 서버가 코어 인스턴스를 공유한다. 또한 동일 레포지토리에 대해 복수의 프로세스(예: 에이전트 세션 + 터미널의 `protokflow serve`)가 접근할 수 있으므로, SQLite는 WAL 모드 및 `busy_timeout`을 기본 적용하여 단일 트랜잭션 경합을 처리한다.

---

## 7. 요구사항 추적

| 요구사항 | 대응 테이블/컬럼 |
|---|---|
| R1 (3계층 캐스케이드) | `design_tokens.tier`, `candidates.token_overrides`, `prototype_runs.token_snapshot` |
| R2 (레이아웃 프리셋 렌더링) | `prototype_runs.layout_preset` (템플릿 자체는 패키지 리소스) |
| R5 (도구 6종 인터페이스) | `prototype_runs`, `candidates`, `token_patches`, `slot_contents`, `exports`, `design_systems.derived_from_id` |
| R6 (스냅샷 이미지) | `candidates.snapshot_path` |
| R10 (핫패치) | `token_patches`, `candidates.token_overrides` |
| R11 (뷰포트 매트릭스) | `candidates.position` |
| R14/R15 (코드 내보내기) | `exports.format` |
| R16 (DESIGN.md 양방향 직렬화) | `design_systems` 동기화 컬럼(`title`, `spec_version`, `front_matter_extras`, `front_matter_raw`, `guide_markdown`, `source_*`), `design_tokens` |
| R17 (SQLite 영속화) | 전체 스키마 + `schema_meta` |
| R18 (관리 UI) | `design_systems`, `design_tokens.origin` |
| R19 (런 보존 정책) | `prototype_runs.status`, `prototype_runs.created_time` |
| R20 (스키마 버전 검사) | `schema_meta` |
| R21 (파일 선검사 및 재인덱싱) | `design_systems.source_mtime`, `design_systems.source_size`, `design_systems.source_digest` |
| R22 (파생 디자인 시스템) | `design_systems.derived_from_id`, `design_systems.source_path` |

---

## 8. Postgres 이식 — 현재 적용 항목과 유예 항목

Postgres 확장 경로는 열어두되, 현재 단계의 준비 작업은 방언과 무관하게 데이터 정합성과 표준 규약을 높이는 작업에 한정한다.

**현재 적용 항목 (표준 SQL 및 타입 안전성)**
- `backend/app/protokflow/model/types` 모듈을 통해 단일화된 커스텀 타입 정의:
  - `Timestamp` — naive `datetime`을 거부하고 UTC aware 객체만 수용·정규화. 도메인 타임스탬프 컬럼(`design_systems.synced_at`)에 적용.
  - `Ulid` — TEXT(26) 기반 고정 길이 식별자.
  - `Json` — `sa.JSON` 매핑.
- 모든 제약 조건(CHECK, UNIQUE, FK, Index)에 명시적 네이밍 규칙 적용.
- 감사 컬럼(`created_time`/`updated_time`/`deleted_time`)은 공통 `Base`의 `TimeZone` 타입을 따른다(§5 공통 규약). 저장 시각의 UTC 통일이 필요하면 `DATETIME_TIMEZONE=UTC`로 설정한다.
- `CHECK` 제약 열거값을 Pydantic v2 Enum 문자열과 동기화.
- SQLite 전용 문법(ROWID 의존, `INSERT OR REPLACE` 등)을 배제하고 표준 SQLAlchemy API 사용.

**유예 항목 (실제 Postgres 요구 시 도입)**
- `JSONB` variant 승격(`with_variant`), 방언별 조건부 인덱스, 다중 DB 백엔드 DI.
- 복잡한 다중 테넌시 및 행 단위 소유권 모델.

> **주의**: 레포지토리 단위 격리 모델은 데이터베이스의 물리적 위치(로컬 SQLite 또는 원격 Postgres)를 제약하지 않는다. 다만 원격 Postgres 운영 시 §1-1의 로컬 복구 불변식이 적용되지 않으므로 마이그레이션 도구(Alembic) 관리가 필요하다.

---

## 9. 마이그레이션 및 데이터 보존

- **0.1.0 초기 버전**: `MappedBase.metadata.create_all()` 및 `schema_meta.schema_version` 버전 검사를 적용한다. 버전 불일치 시 명확한 오류 및 안내를 제공한다.
- **복구 메커니즘**: DB가 손상되거나 삭제되더라도 `DESIGN.md` 파일들로부터 디자인 시스템과 토큰 트리를 언제든 재인덱싱하여 복구할 수 있다.
- **런 보존 정책**: 런 데이터는 기본값으로 디자인 시스템당 최근 50개를 유지하며, 초과분은 `archived` 상태로 전환 후 `protokflow prune` 명령으로 정리한다. 디자인 시스템과 토큰은 자동 삭제 대상에서 제외된다.
- **커넥션 설정**: 커넥션 초기화 시 `PRAGMA foreign_keys=ON`, `PRAGMA journal_mode=WAL`, `PRAGMA busy_timeout`을 강제하여 CASCADE 정합성과 다중 프로세스 동시성을 보장한다.

---

## 10. 열린 질문

| # | 질문 | 현재 설계의 가정 |
|---|---|---|
| Q1 | 디자인 시스템 토큰의 버전 이력/롤백이 필요한가? | `DESIGN.md`가 Git에 커밋되므로 버전 관리는 Git에 위임하는 것으로 가정. 필요 시 `design_system_versions` 테이블 신설 검토. |
| Q2 | 사용자(A2)의 후보 평가·코멘트를 영속화하는가? | 현재 요구사항에 없어 미포함. 필요 시 `candidate_feedback` 신설. |
| Q3 | 스냅샷 이미지의 보존 기간은? | 런 프루닝(§9)과 함께 삭제하는 것으로 가정. |
| Q4 | 커스텀 프리셋 레지스트리(`.protokflow/presets/`)가 DB 항목이 되는가? | 파일 시스템 기반으로 가정. DB화 시 `layout_presets` 테이블 추가 검토. |
| Q5 | 동일한 `token_snapshot`을 여러 런이 복제하는 것을 허용하는가? | 허용. 스냅샷은 수 KB 수준이며 프루닝으로 상한 관리. 추후 필요 시 `snapshots` 테이블로 중복 제거 검토. |
