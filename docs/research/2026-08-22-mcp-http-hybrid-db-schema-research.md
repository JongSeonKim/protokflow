# MCP + HTTP 하이브리드 구조 프로젝트의 DB 스키마 설계 리서치

> 조사일: 2026-08-22 · 대상 문서: [데이터베이스 스키마 설계](../concepts/database-schema.md)
> 조사 질문: **"에이전트용 MCP 어댑터와 사람용 HTTP 서버가 하나의 코어/DB를 공유하는 구조"를 채택한 프로젝트들은 영속 계층을 어떻게 설계했는가?** 디자인 시스템 도메인에 국한하지 않고 조사했다.

결론 요약: 우리의 핵심 결정 두 가지(**현재값 + 추가전용 이력 분리**, **스냅샷 박제로 재현성 확보**)는 성숙한 프로젝트에서 동일하게 발견되어 검증되었다. 반면 **파일↔DB 동기화 상태 모델**과 **SQLite 방언 이식 방법론**은 우리 설계가 명백히 얕고, 즉시 보강이 필요하다.

---

## 1. 조사 대상과 선정 기준

"하이브리드"를 세 층위로 나누어 분류했다. 참고 가치는 A > B > C 순이다.

| 층위 | 정의 | 조사 대상 | 확인 근거 |
|---|---|---|---|
| **A. 진성 하이브리드** | 로컬 우선 단일 프로세스에서 MCP 도구와 HTTP 앱이 같은 코어/DB를 공유 | **Basic Memory** | `mcp/async_client.py`의 `_asgi_client()`가 `basic_memory.api.app`의 FastAPI 인스턴스를 `httpx.ASGITransport`로 직접 호출 (소스 확인) |
| **B. 서버 우선 + MCP 부가** | HTTP 서버가 주(主)이고 동일 DB 위에 MCP 표면을 추가 | **Arize Phoenix**, **Langfuse**, **Dagster**, **MLflow** | Phoenix는 인스턴스의 `/mcp` 엔드포인트로 MCP 클라이언트 연결을 제공(문서 확인). Langfuse는 MCP/CLI/API를 동일 평가 워크플로에 노출. |
| **C. 무상태 MCP 프록시** | DB는 조회 대상일 뿐 자체 상태를 소유하지 않음 | 각종 `mcp-sqlite`, DB 커넥터 MCP 서버 | 자체 스키마가 없어 **참고 대상에서 제외** |
| **D. 스키마 방법론 참조** | 하이브리드는 아니나 "SQLite 기본 + Postgres 확장"을 대규모로 운영 | **Prefect** | `server/utilities/database.py`의 방언 TypeDecorator 3종 (소스 확인) |

Basic Memory가 우리 구조와 가장 가깝다: 로컬 마크다운 파일이 진실의 원천, SQLite는 인덱스, MCP는 에이전트 인터페이스, FastAPI는 사람 인터페이스 — Protokflow의 `DESIGN.md` / SQLite / MCP / `/admin` 대응 관계가 거의 1:1이다.

---

## 2. 발견 사항과 적용 판단

### F1. MCP는 HTTP의 상위가 아니라 **클라이언트**가 될 수 있다 — Basic Memory

Basic Memory의 MCP 도구는 코어를 직접 호출하지 않는다. `httpx.ASGITransport`로 **자기 프로세스 안의 FastAPI 앱에 HTTP 요청을 보낸다.** 네트워크는 타지 않으므로 비용은 함수 호출 수준이고, 로컬/클라우드 전환은 트랜스포트 교체(`BASIC_MEMORY_FORCE_CLOUD`)만으로 끝난다.

- **우리 KD1과의 차이**: 우리는 MCP 어댑터와 HTTP 어댑터가 **각자** 코어를 호출하는 Y자 구조다. Basic Memory는 MCP → HTTP → 코어의 직렬 구조다.
- **스키마 관점의 함의**: 직렬 구조에서는 DB 세션·트랜잭션 경계 소유자가 HTTP 서비스 계층 **하나**로 강제된다. Y자 구조는 두 어댑터가 각각 세션을 열 수 있어 "누가 커밋하는가"가 흐려진다.
- **판단**: 아키텍처는 KD1(Y자)을 유지한다 — 코어를 네트워크 목킹 없이 테스트한다는 SC5가 더 중요하다. 다만 **쓰기 트랜잭션의 소유권은 서비스 계층 한 곳으로 제한**하고, 어댑터는 세션을 직접 열지 않는다는 규칙을 스키마 문서 §6에 명시한다. *(채택 — 규칙)*

### F2. 파일↔DB 동기화에 다이제스트 하나는 부족하다 — Basic Memory ★가장 중요

우리 `design_systems.source_digest`(sha256 1개)에 대응하는 Basic Memory의 구조는 훨씬 두껍다.

```
entity:        file_path, checksum, mtime, size          -- 파일 → DB 인덱싱 상태
note_content:  db_version,   db_checksum                 -- DB 쪽 현재 내용
               file_version, file_checksum               -- 파일 쪽 마지막 관측 내용
               file_write_status ('pending' 기본값)      -- DB→파일 반영 대기 상태
               last_source                               -- 마지막 변경 주체
               last_materialization_error / _attempt_at  -- 쓰기 실패 원인과 재시도 시각
note_file_vacate: project_id, file_path, file_checksum   -- 이동/삭제된 경로의 툼스톤
```

읽어야 할 세 가지:

1. **양방향은 다이제스트 2개를 요구한다.** DB 쪽 값과 파일 쪽 값을 각각 들고 있어야 (a) 파일만 변함 (b) DB만 변함 (c) 둘 다 변함(충돌) (d) 동일 — 4가지 상태가 구분된다. 우리 단일 컬럼으로는 (b)를 표현할 수 없다. 즉 **`/admin`에서 토큰을 편집했지만 아직 `DESIGN.md`로 내보내지 않은 상태를 DB가 모른다.**
2. **`mtime`과 `size`는 해시 회피용 선(先)검사다.** 파일이 커질수록 sha256는 비싸다. `(mtime, size)`가 같으면 해시를 건너뛴다.
3. **쓰기는 실패할 수 있으므로 상태와 오류를 남긴다.** `file_write_status`, `last_materialization_error`가 그 역할이다.

- **판단(세션 후속 결정으로 축소됨)**: `/admin` 편집이 `DESIGN.md`로 **즉시 write-through**하는 것으로 확정되어, DB가 파일보다 앞선 상태가 지속될 수 없다. 따라서 `sync_state` 4상태 머신과 이중 다이제스트는 **불채택**이며 `source_digest` 하나로 충분하다.
  - 다만 **`mtime`/`size`는 채택**한다. 용도가 바뀌었다: Basic Memory에서는 "큰 파일 해싱 비용 회피"였으나, 우리에게는 **매 도구 호출마다 도는 상시 선검사를 공짜로 만드는 장치**다. 파일→DB 방향이 필요한 상황(`git pull`, 브랜치 전환, fresh clone, 에이전트의 파일 직접 편집)은 대부분 사용자가 의식하지 못한 채 발생하므로, 이 방향은 "import 기능"이 아니라 상시 규율이어야 한다.
  - 실패 로그 컬럼과 툼스톤(`note_file_vacate` 대응)은 미채택 — 파일 이동을 추적하지 않는다.
  - 최종 반영: `design_systems`에 `source_mtime`, `source_size` 2개 컬럼 추가. *(부분 채택 — 스키마 변경)*

### F3. 현재값 테이블 + 추가전용 이력은 표준 패턴이다 — MLflow

MLflow는 `metrics`(전체 이력)와 `latest_metrics`(`PRIMARY KEY (key, run_uuid)`, 현재값)를 **둘 다** 유지한다. 우리 `candidates.token_overrides`(현재) + `token_patches`(이력) 분리와 같은 판단이며, "로그 역재생으로 현재 상태를 계산하지 않는다"는 우리 규칙이 업계 표준임이 확인된다.

- **차이점**: MLflow의 현재값은 **테이블**(키 단위 조회·필터 가능), 우리는 **JSON 컬럼**이다.
- **판단**: JSON을 유지한다. 후보의 토큰 오버라이드는 항상 전량을 읽어 렌더링하므로 키 단위 인덱스 이득이 없다. 단 *"특정 토큰을 패치한 후보를 모두 찾아라"* 같은 질의가 요구사항이 되는 순간 테이블로 승격해야 하며, 이 전환 조건을 스키마 문서에 남긴다. *(유지 — 근거 보강)*

### F4. SQLite의 `AUTOINCREMENT` 누락은 단조 증가를 깨뜨린다 — Phoenix ★즉시 수정

Phoenix는 테이블마다 `__table_args__ = (dict(sqlite_autoincrement=True),)`를 붙인다. 이유는 SQLite가 `AUTOINCREMENT` 없이는 **삭제된 행의 rowid를 재사용**하기 때문이다.

우리 `token_patches.seq`는 `INTEGER PRIMARY KEY AUTOINCREMENT`로 이미 선언되어 있으나 이는 순전히 우연이며, **§9의 런 프루닝 정책과 정면으로 맞물리는 위험**이다. 프루닝으로 오래된 패치를 지운 뒤 재사용된 seq는 "적용 순서"라는 도메인 의미를 조용히 파괴한다.

- **판단**: SQLModel 모델에 `sqlite_autoincrement=True`를 **명시**하고, "seq는 적용 순서를 의미하므로 rowid 재사용을 금지한다"는 주석을 코드와 문서 양쪽에 남긴다. *(채택 — 명시화)*

### F5. 무명 CHECK 제약은 마이그레이션 드리프트를 만든다 — MLflow ★즉시 수정

MLflow 소스의 주석은 직접적이다:

> *Historical migrations generate this SQLite CHECK constraint without a stable name. Keep ORM metadata aligned with that schema so Alembic autogenerate sees no drift.*

우리 스키마 문서의 `CHECK (tier IN ('foundation','component'))`, `CHECK (status IN (...))`, `CHECK (format IN (...))`는 전부 **이름이 없다.** 나중에 Alembic을 도입(§9)하는 순간 autogenerate가 매번 가짜 변경을 제안하게 된다.

- **판단**: 모든 CHECK/UNIQUE/FK/Index에 이름을 부여하고, SQLAlchemy `MetaData(naming_convention=...)`를 도입해 규칙으로 강제한다. 첫 Alembic 도입 이전에 해야 비용이 0이다. *(채택 — 스키마 변경)*

### F6. 방언 이식은 "규칙"이 아니라 **타입 3종**으로 코드화한다 — Prefect, Phoenix ★즉시 수정

우리 스키마 문서 §8은 이식성을 산문 규칙으로 적어두었다. Prefect와 Phoenix는 이를 `TypeDecorator`로 캡슐화해 **위반이 불가능하게** 만든다.

```python
# Prefect: Timestamp — naive datetime을 아예 거부한다
if value.tzinfo is None:
    raise ValueError("Timestamps must have a timezone.")
elif dialect.name == "sqlite":
    return value.astimezone(ZoneInfo("UTC"))

# Prefect: UUID / JSON
postgresql -> postgresql.UUID()               | 그 외 -> CHAR(36)
postgresql -> postgresql.JSONB(none_as_null=True) | sqlite -> sqlite.JSON(none_as_null=True)

# Phoenix: 변형(variant) 방식 + SQLite JSONB
JSON_ = JSON().with_variant(postgresql.JSONB(), "postgresql").with_variant(JSONB(), "sqlite")
```

- **판단**: `protokflow.storage.types`에 `Timestamp`(UTC aware 강제), `Ulid`(TEXT 26자), `Json`(JSONB 변형) 3종을 정의하고 모든 모델이 이것만 쓰도록 한다. 특히 **naive datetime 거부**는 로컬 타임존이 섞여 들어가는 사고를 원천 차단하므로 그대로 가져온다. *(채택 — 구현 규약)*
- 부수 발견: Phoenix/Prefect는 부분 인덱스를 `postgresql_where=` 와 `sqlite_where=` 를 **동시에** 지정해 양쪽에서 동일하게 동작시키고, PG 전용 인덱스는 `.ddl_if(dialect="postgresql")`로 분기한다. 우리가 부분 인덱스를 쓰게 될 때의 정답. *(참고)*

### F7. blob + 승격 컬럼 vs 정규화 — Dagster

Dagster의 `runs` 테이블은 실행 전체를 `run_body`(직렬화 TEXT)로 저장하고, **필터링에 필요한 것만** 컬럼으로 승격한다(`status`, `pipeline_name`, `partition`, `start_time`, `end_time`). 태그는 별도 `run_tags` EAV 테이블 + `(key, value)` 복합 인덱스로 분리한다.

- **우리 대응**: `prototype_runs.token_snapshot`(JSON)이 사실상 blob이고, 승격 컬럼은 `layout_preset`/`status`/`design_system_id`뿐이다. 같은 구조이며 승격 폭도 적절하다. *(정합 — 변경 없음)*

### F8. 콘텐츠 주소화의 **정당한** 용례 — Dagster

우리는 §2에서 콘텐츠 주소 저장소를 배제했다. 그런데 Dagster는 `snapshots(snapshot_id UNIQUE, snapshot_body, snapshot_type)` 테이블을 두고 `runs.snapshot_id`가 이를 FK로 참조한다 — **동일 파이프라인 정의로 반복 실행할 때 스냅샷 중복을 제거**하기 위해서다.

이는 우리 시나리오와 정확히 겹친다. 디자인 시스템을 고치지 않고 후보만 바꿔가며 런을 20회 돌리면 동일한 `token_snapshot`이 20벌 복제된다.

- **판단**: 지금은 복제를 **허용**한다. 스냅샷 1개는 수 KB이고 프루닝(최근 50개)이 상한을 잡는다. 다만 §2의 "콘텐츠 주소화 배제"는 *권위/아티팩트 추적 목적*에 한정된 배제임을 명확히 하고, **중복 제거 목적의 도입은 열린 항목**으로 남긴다. 도입 시점의 판단 기준: 런 수가 수천 개 규모가 되거나 스냅샷이 수백 KB로 커질 때. *(배제 근거 정교화)*

### F9. 데몬 상태를 DB에 두는 반례 — Dagster

Dagster에는 `daemon_heartbeats(daemon_type UNIQUE, daemon_id, timestamp, body)` 테이블이 있다. 우리는 데몬 상태를 `.protokflow/daemon.json` **파일**에 두기로 했다(스키마 문서 §3).

- **차이의 근거**: Dagster의 데몬은 다중 프로세스이며 원격에서 관측되어야 한다. 우리는 KD2의 단일 프로세스 테더링이고, 프로세스와 함께 죽는 것이 **정확한 동작**이다. DB에 두면 좀비 행이 남는다.
- **판단**: 파일 방식 유지. 근거를 스키마 문서에 보강한다. *(유지 — 근거 보강)*

### F10. 스키마 마이그레이션과 **데이터** 마이그레이션은 다르다 — Dagster

Dagster는 `secondary_index_migration(name UNIQUE, create_timestamp, migration_completed)` 테이블로 "이 데이터 백필이 끝났는가"를 스키마 버전과 **별도로** 추적한다. `instance_info`, `kvs`(키-값) 테이블도 있는데, 후자는 우리 `schema_meta`와 같은 역할이다.

- **판단**: 0.1.0에는 불필요하다. 다만 `schema_meta`를 처음부터 **범용 키-값 스토어**로 설계해두면(현재 그렇다) 데이터 마이그레이션 완료 플래그를 테이블 추가 없이 수용할 수 있다. *(정합 — 변경 없음)*

### F11. 소프트 삭제 — MLflow

MLflow의 `runs.lifecycle_stage`(`active`/`deleted`)는 CHECK 제약이 걸린 소프트 삭제다. 우리 프루닝(§9)은 하드 삭제다.

- **판단**: 하드 삭제 유지. 프로토타입 런은 재생성 가능한 파생물이며, `status='archived'`가 이미 "보이지 않지만 남아있는" 중간 단계를 제공한다. 두 겹의 삭제 개념은 과하다. *(유지)*

### F12. 버전 + 라벨 포인터 — Phoenix, Langfuse (열린 질문 Q1의 검증된 해답)

우리 스키마 문서의 열린 질문 Q1("디자인 시스템 토큰 롤백이 필요한가")에 대해, 두 프로젝트가 같은 형태의 답을 제시한다.

```
Phoenix   : prompts ← prompt_versions ← prompt_version_tags(UNIQUE(name, prompt_id))
            + prompt_labels 다대다
Langfuse  : Prompt { version Int, labels String[], @@unique([projectId, name, version]) }
```

즉 **불변 버전 행 + 이동 가능한 라벨 포인터**(`production`, `latest`)다. 리비전 그래프나 부모 포인터 없이 정수 버전 하나로 충분하다.

- **판단**: 지금은 도입하지 않되(§2의 배제 유지), **필요해질 때의 형태를 확정**한다: `design_system_versions(design_system_id, version INT, tokens JSON, guide_markdown TEXT, created_at)` + `UNIQUE(design_system_id, version)`, 라벨이 필요하면 `workspace_version_tags`. 우리가 §2에서 배제한 것은 `authority_revision` + `authority_current` + `proposal` + `approval`의 **4테이블 승격 의례**이지, 버전 개념 자체가 아니다. *(배제 범위 정교화)*

### F13. 에이전트는 대화 중에 스코프를 바꾼다 — Basic Memory ★가정 재검토 필요

Basic Memory는 `project` 테이블을 두고 **모든** 도메인 행에 `project_id`를 붙인다(`entity`, `observation`, `relation`, `note_content` 전부). 문서의 설명이 결정적이다:

> *"각 클라이언트마다 프로젝트를 부여한다. **대화 도중에 클라이언트 사이를 전환할 수 있다.**"*
> *"프로젝트마다 로컬 DB와 클라우드 인스턴스 중 어디에 연결할지 독립적으로 결정한다."*

우리 스키마 문서의 열린 질문 Q3은 *"`.protokflow/`가 프로젝트별로 존재하므로 `projects` 테이블이 불필요하다"* 고 답했다. 이 가정의 취약점이 드러난다: **MCP 서버는 에이전트 세션당 하나인데, 사용자는 한 세션에서 여러 레포를 오간다.** 프로세스의 cwd가 프로젝트를 결정하는 모델은 이 상황에서 깨진다.

- **판단**: 0.1.0에서는 프로젝트당 DB를 **유지**한다(무설정 로컬 실행이라는 KD6의 목적에 부합). 대신 두 가지를 보험으로 건다.
  1. 모든 도구가 `design_system`을 **명시적 인자**로 받는다(이미 그러함). 프로세스 상태에 의존하는 암묵적 "현재 디자인 시스템"를 만들지 않는다.
  2. `design_systems`를 유일한 최상위 소유 엔티티로 유지한다(이미 §8에 명시). 나중에 `projects`가 필요해지면 디자인 시스템 위에 한 단계를 얹는 것으로 끝난다.
  - Q3의 답을 "불필요"에서 **"현재는 지연, 전환 조건은 다중 레포 세션 지원"**으로 수정한다. *(열린 질문 갱신)*

### F14. 내부 PK와 공개 ID의 분리 — Basic Memory

Basic Memory는 `id INTEGER PRIMARY KEY`(내부 조인용) + `external_id UUID UNIQUE`(외부 노출용) + `permalink UNIQUE`(사람이 읽는 주소)를 **셋 다** 유지한다.

- **우리 설계**: TEXT ULID PK 단일 + `design_systems.slug`. 조인 폭과 인덱스 크기 면에서는 정수 PK가 유리하다.
- **판단**: ULID 단일 유지. 우리 데이터 규모(디자인 시스템 수십 개, 런 수백 개)에서 정수 PK의 이점은 측정 불가능한 반면, 식별자 종류가 셋이 되면 "어느 ID를 반환해야 하는가"가 API 표면마다 반복되는 결정 비용이 된다. *(유지 — 근거 보강)*

---

## 3. 적용 요약

| # | 항목 | 출처 | 조치 |
|---|---|---|---|
| F2 | 디자인 시스템 동기화: `source_mtime`/`source_size` 추가 (상시 선검사용). `sync_state` 4상태 머신은 write-through 확정으로 철회 | Basic Memory | **부분 채택 — 반영 완료** |
| F5 | 모든 제약에 이름 부여 + `naming_convention` 도입 | MLflow | **스키마 변경** |
| F4 | `sqlite_autoincrement=True` 명시 (`token_patches.seq` 단조성) | Phoenix | **명시화** |
| F6 | 방언 타입 3종(`Timestamp`/`Ulid`/`Json`)으로 이식 규칙 코드화 | Prefect, Phoenix | **구현 규약** |
| F1 | 쓰기 트랜잭션 소유권을 서비스 계층으로 제한 | Basic Memory | **규칙 추가** |
| F13 | Q3 **종결** — 1 repo = 1 SQLite DB 확정, `projects` 테이블·소유권 컬럼 모두 불채택 | Basic Memory | **반영 완료** |
| F8 | 콘텐츠 주소화 배제의 범위를 "권위 추적 목적"으로 한정 | Dagster | **근거 정교화** |
| F12 | Q1의 도입 형태를 `design_system_versions` + 라벨로 사전 확정 | Phoenix, Langfuse | **열린 질문 갱신** |
| F3 | 현재값 JSON 유지 + 테이블 승격 조건 명시 | MLflow | 근거 보강 |
| F9 | 데몬 상태 파일 유지 | Dagster | 근거 보강 |
| F14 | ULID 단일 식별자 유지 | Basic Memory | 근거 보강 |
| F7, F10, F11 | blob+승격 컬럼 / `schema_meta` 범용성 / 하드 삭제 | Dagster, MLflow | 변경 없음 |

## 4. 조사에서 얻지 못한 것

- **디자인 토큰을 DB에 정규화한 선례**는 찾지 못했다. 조사한 도구들의 토큰/설정은 전부 JSON blob 또는 파일이다. 우리 `design_tokens` 행-단위 정규화(§5.3)는 `/admin`의 개별 토큰 편집이라는 요구(R18)에서 나온 고유 결정이며, 외부 검증 대상이 없다.
- **MCP 도구 호출 자체를 영속화하는 선례**도 없었다. 조사한 프로젝트들은 MCP를 기존 도메인 데이터에 대한 조회/조작 표면으로만 취급하며, "어떤 에이전트가 어떤 도구를 호출했는가"를 저장하지 않는다. 우리도 `token_patches.origin`(`agent`/`admin_ui`) 이상의 호출 감사 로그를 두지 않는 편이 일관적이다.

## 5. 참고 자료

- Basic Memory — [`mcp/async_client.py`](https://github.com/basicmachines-co/basic-memory/blob/main/src/basic_memory/mcp/async_client.py), [`models/knowledge.py`](https://github.com/basicmachines-co/basic-memory/blob/main/src/basic_memory/models/knowledge.py), [`models/project.py`](https://github.com/basicmachines-co/basic-memory/blob/main/src/basic_memory/models/project.py), [Projects and folders 문서](https://docs.basicmemory.com/concepts/projects-and-folders)
- MLflow — [`store/tracking/dbmodels/models.py`](https://github.com/mlflow/mlflow/blob/master/mlflow/store/tracking/dbmodels/models.py)
- Arize Phoenix — [`src/phoenix/db/models.py`](https://github.com/Arize-ai/phoenix/blob/main/src/phoenix/db/models.py), [저장소](https://github.com/Arize-ai/phoenix)
- Prefect — [`server/utilities/database.py`](https://github.com/PrefectHQ/prefect/blob/main/src/prefect/server/utilities/database.py), [`server/database/orm_models.py`](https://github.com/PrefectHQ/prefect/blob/main/src/prefect/server/database/orm_models.py)
- Dagster — [`_core/storage/runs/schema.py`](https://github.com/dagster-io/dagster/blob/master/python_modules/dagster/dagster/_core/storage/runs/schema.py)
- Langfuse — [`packages/shared/prisma/schema.prisma`](https://github.com/langfuse/langfuse/blob/main/packages/shared/prisma/schema.prisma)
