# Document Cleansing Patterns & Before/After Examples

이 문서는 `doc-cleanse` 스킬을 수행할 때 참고할 수 있는 일반적인 소프트웨어 공학 및 아키텍처 문서 대상의 대표적인 변환 패턴과 Before / After 사례 모음입니다.

---

## 1. 세션 메타 태그 변환 패턴

### 패턴 1-1: `session-settled` 태그 본문화
- **Before**:
  ```markdown
  - **ADR-01 (In-Memory Cache Layer)**: Redis를 채택한다. `(session-settled: user-directed — chosen over Memcached: eliminates separate PubSub infra and enables 100% unified session TTL management)` `Governs R3, R4`
  ```
- **After**:
  ```markdown
  - **ADR-01 (In-Memory Cache Layer)**: 인메모리 캐시 계층으로 Redis를 채택한다. 캐싱 기능과 더불어 분산 Pub/Sub 및 TTL 기반 세션 관리를 단일 인프라에서 수용하여 아키텍처 복잡도를 낮춘다. `Governs R3, R4`
  ```

### 패턴 1-2: 문서 상태 뱃지 및 인수인계 메타 정리
- **Before**:
  ```markdown
  > 상태: 설계 초안 (v0.2 — 세션 합의 및 요구사항 확정 결정 반영)
  이 문서는 이전 회의록이 초안인 점을 고려해 데이터 파이프라인 구성을 원점에서 재도출했습니다. 여기서 확정된 내용은 이후 상위 플랜 문서에 역반영됩니다.
  ```
- **After**:
  ```markdown
  > 상태: 확정 설계 (v1.0) · 대상 시스템: `data-pipeline`
  이 문서는 `data-pipeline` 계층의 영속 데이터 모델, 배치 처리 주기 및 서비스 간 동기화 정책을 정의하는 단일 소스 명세이다.
  ```

---

## 2. 구호형 슬로건 및 구어체 변환 패턴

### 패턴 2-1: 슬로건형 헤딩/명칭
- **Before**:
  ```markdown
  - **ADR-03 (One Queue = One Worker, Kafka is Overkill)**
  ```
- **After**:
  ```markdown
  - **ADR-03 (Sequential Queue Architecture for Single-Worker Processing)**
  ```

### 패턴 2-2: 구어적 비유 및 방어적 문구
- **Before**:
  ```markdown
  - `cache_mtime`은 **매 요청마다 도는 상시 선검사를 공짜로 만드는 장치**다.
  - **이 모듈에서 상속은 완전히 쥐약이다.**
  - `config.json`이 서버 몰래 바뀌는 경로는...
  - > 주의: "NoSQL 도입"은 **캐시 추가**에 대한 진술이지 **RDB 대체**에 대한 진술이 아닙니다(세션 중 오해 방지).
  ```
- **After**:
  ```markdown
  - `cache_mtime`은 요청 수신 시 파일 변경 여부를 저비용(`stat`)으로 선검사하여 해시 연산 오버헤드를 회피하는 메커니즘이다.
  - 모듈 간 결합도를 낮추고 독립성을 유지하기 위해 클래스 상속 대신 컴포지션 패턴을 적용한다.
  - 설정 파일은 애플리케이션 외부(CLI, 환경 변수 등)에서 직접 수정될 수 있으므로 매 실행 시 파일 상태를 검증한다.
  - > 주의: NoSQL 저장소는 메인 RDBMS의 트랜잭션 책임을 대체하지 않으며, 고빈도 읽기 부하 분산을 위한 보조 캐시 계층으로 운용된다.
  ```

---

## 3. 과거 초안 및 외부 시스템 비교 에세이 패턴

### 패턴 3-1: 구버전 용어 논쟁 흔적 제거
- **Before**:
  ```markdown
  | 용어 | 정의 | 아닌 것 |
  |---|---|---|
  | 테넌트 (`tenants`) | 클라우드 인프라 1개 범위 | 예전 문서의 "워크스페이스"나 "계정" |
  ```
- **After**:
  ```markdown
  | 용어 | 정의 | 비고 / 주의 |
  |---|---|---|
  | 테넌트 (`tenants`) | 단일 고객사에 할당된 논리적 리소스 및 데이터 격리 경계 | 서브도메인 및 전용 DB 스키마를 소유하는 기본 단위 |
  ```

### 패턴 3-2: 외부 프레임워크와의 장문 사변적 비교 에세이 배제
- **Before**:
  ```markdown
  Netflix Eureka나 Consul이 복잡한 가십 프로토콜을 쓰는 것과 달리, 우리 시스템은 노드 수가 적고 단순하므로 그 시맨틱을 우리가 통째로 떠안을 이유가 없다. 따라서 중앙 레지스트리 방식을 쓴다.
  ```
- **After**:
  ```markdown
  클러스터 노드 탐색은 중앙 집중식 서비스 레지스트리(Service Registry)를 통해 단순하고 결정론적인 토폴로지로 관리한다.
  ```

---

## 4. 취소선 종결 질문 및 동기화 작업 체크리스트

### 패턴 4-1: 취소선 표기 정리
- **Before**:
  ```markdown
  | # | 질문 | 현재 설계의 가정 |
  |---|---|---|
  | ~~Q1~~ | ~~MongoDB를 샤딩할 것인가?~~ | **종결.** 단일 레플리카셋으로 확정(ADR-05 참조). |
  | Q2 | 스냅샷 이미지의 보존 기간은? | 30일 보존 정책 적용 후 자동 삭제. |

  플랜 문서 갱신 시 반영할 항목:
  - R17 테이블명 구체화
  - 보존/프루닝 정책 신설 검토
  ```
- **After**:
  ```markdown
  | # | 질문 | 현재 설계의 가정 |
  |---|---|---|
  | Q2 | 스냅샷 이미지의 보존 기간은? | 30일 보존 정책 적용 후 자동 삭제(§9)하는 것으로 가정. |
  ```
