# static-dive

알비온 온라인 파티를 생성하고 관리하는 웹 서비스를 설계합니다. 파티장이 파티와 슬롯을 구성하고, 공개/비공개 파티를 통해 파티원을 모집하거나 초대할 수 있도록 하는 것을 목표로 합니다.

## 서비스 개요
- **목적**: 알비온 온라인 파티 편성 과정을 웹으로 간소화하여 모집, 장비 관리, 참여 흐름을 일원화.
 - **대상 사용자**: 파티장(호스트)과 파티원.
 - **주요 가치**: 공개 파티의 빠른 매칭, 비공개 파티의 초대 코드 기반 관리, 슬롯별 장비 프리셋 공유.

## 핵심 기능
1. **파티 생성 및 관리**
   - 파티장은 공개/비공개 여부를 설정해 파티 생성.
   - 공개 파티: 공개된 목록에서 검색 및 필터 후 누구나 신청.
   - 비공개 파티: 파티장이 발급한 초대 코드로만 접근하며, 별도의 코드 기반 입장 흐름으로 신청.
   - 파티 기본 정보: 제목, 설명, 활동 시간, 인원 제한, 음성 채널 안내 등.

2. **파티 목록 및 참여 흐름**
   - 공개 파티 리스트: 카테고리/역할/장비 태그 등으로 필터링.
   - 파티 상세 보기: 슬롯 구성, 장비 요구사항, 현재 참여자 확인.
   - 참여 신청/확정: 파티장이 신청을 승인하거나 자동 확정 옵션 제공.

3. **비공개 초대 코드**
   - 파티 생성 시 초대 코드 자동 발급 및 재발급 기능.
   - 코드 공유용 단축 URL/QR 코드 고려.
   - 초대 코드 입력 후 파티 상세에 접근하고 슬롯 신청 가능.

4. **슬롯 및 장비 프리셋 관리**
   - 파티장은 역할(탱커, 힐러 등)별 슬롯 생성.
   - 슬롯별 장비 프리셋(무기/방어구/먹거리/마운트 등) 정의 및 저장.
   - 파티원은 슬롯 신청 시 자신의 장비 세트/빌드를 프리셋으로 공유.
   - 프리셋 검증: 아이템 파워 최소 기준, 필수 옵션 등 체크리스트 제공.

### 장비 프리셋 상세 (알비온 위키 기준 장비 타입)
- **기본 구조**: `무기 계열` + `방어구 3부위` + `오프핸드/케이프·가방` + `소모품(음식/물약)` + `마운트` + `목표 IP/특성`.
- **무기 계열**
  - 워리어 라인: 도끼(Axe), 도검(Sword), 둔기(Hammer), 철퇴(Mace).
  - 헌터 라인: 활(Bow), 석궁(Crossbow), 단검(Dagger), 장창(Spear) 계열 하위 분화 포함.
  - 메이지 라인: 아케인 스태프(Arcane Staff), 저주 스태프(Cursed Staff), 화염/서리 스태프(Fire/Frost Staff), 성직/자연 스태프(Holy/Nature Staff).
- **방어구**
  - 천/가죽/판금 헬멧, 아머, 부츠 각각 선택. 방어구 라인에 따라 공격/생존/유틸 스킬이 결정됨.
  - 케이프: 브리지워치/마르톡 등 도시 파생, 테트포트/리무스트라 등 각종 케이프 효과 명시.
  - 가방: 기본 배낭, 포션백, 체력 회복 가방 등 무게 감소 계열.
- **오프핸드**
  - 방패(Shield), 횃불/미스트콜러(Torch/Mistcaller), 책/마법서(Tome), 뮤식/리어링 케인(Muisak/Leering Cane) 등 스킬 대기시간·데미지 보조용.
- **소모품**
  - 음식: 오믈렛(쿨타임 감소), 소고기 스튜(공격력), 치킨 파이/샌드위치(생존/자원 효율) 등 역할별 선택.
  - 물약: 치유/에너지/독/투명 물약 등 특수 상황 대응.
- **마운트**
  - 기본 말/전투 말, 산악 소/황소(짐꾼), 빠른 이동용 늑대/스위프트클로/곰 계열 등.
- **프리셋 예시 필드**
  - `role`: 탱커/힐러/딜러/정찰.
  - `weapon`: 무기 라인 + 구체 모델(예: 브로드소드, 그레이트 해머 등).
  - `armor`: 헬멧/아머/부츠 + 티어/인챈트.
  - `offhand`: 방패/토치/책 등 필요 시 기재, 케이프/가방 옵션.
  - `consumables`: 음식/물약 종류와 티어.
  - `mount`: 마운트 종류.
  - `ip_target`: 최소 아이템 파워, 추천 특성 노드.

5. **알림 및 기록**
   - 파티 확정/변경/취소 알림(이메일 혹은 디스코드 웹훅 고려).
   - 과거 파티 기록과 프리셋 히스토리 저장으로 재사용성 제공.

## 정보 구조 및 화면 아이디어
- **홈/공개 파티 목록**: 파티 카드, 필터(역할, 시간대, IP 요구치 등), 정렬.
- **파티 생성/편집**: 공개 여부, 초대 코드 확인, 기본 정보 입력, 슬롯/프리셋 설정.
- **파티 상세**: 슬롯별 장비 요구사항, 신청자 리스트, 승인 대기/확정 상태 표시.
- **비공개 입장**: 초대 코드 입력 폼 → 파티 상세 진입.

## 기술 메모(초안)
- **인증/권한**: 호스트/참가자 권한 분리, 초대 코드 기반 접근 제어.
- **데이터 모델 초안**:
  - Party: id, host_id, title, description, visibility(public/private), invite_code, schedule, capacity, voice_channel_link, status.
  - PartySlot: id, party_id, role, preset, requirements.
  - PartyMember: id, party_id, slot_id, user_id, gear_preset, state(applied/accepted/locked).
  - Notification: id, party_id, type, target, payload.
- **향후 과제**: 실시간 업데이트(웹소켓), 디스코드 연동, 모바일 UI 고려.

## 일정/우선순위 초안
1. 파티 생성/목록/상세 기본 흐름 UI 와 데이터 모델 정립.
2. 공개 파티 신청/승인, 비공개 초대 코드 입장 플로우 구현.
3. 슬롯/장비 프리셋 생성 및 검증 UI.
4. 알림 채널(이메일/웹훅) 연동 및 로그/기록 뷰.

이 문서는 기획 진척에 따라 계속 업데이트됩니다.

## 로컬 실행 가이드
- Python 3.11+ 환경을 사용합니다.
- 의존성 설치: `python -m pip install -r requirements.txt`
- 개발 서버 실행: `uvicorn app.main:app --reload`
- 기본 SQLite 데이터베이스(`app.db`)는 자동 생성됩니다.
- 웹 UI는 `/` 경로에서 제공되며, 파티 생성/슬롯 추가/참여 신청/초대코드 재발급을 바로 테스트할 수 있습니다. 헬스체크는 `/health` 입니다.

## Docker 배포
- 이미지 빌드: `docker build -t albion-party .`
- 컨테이너 실행: `docker run -p 8000:8000 albion-party`
- 커스텀 데이터 경로를 사용하려면 환경 변수 `DATABASE_URL`을 넘겨주세요. 예) `-e DATABASE_URL=sqlite:////data/app.db`

### docker-compose 예시
```bash
docker compose up --build -d
```
- 서비스는 `http://localhost:8000` 으로 노출되며, SQLite 파일은 네임드 볼륨(`party_data`) 아래 `/data/app.db`에 저장됩니다.

## GitHub Pages 배포
- `main` 브랜치에 푸시되면 `.github/workflows/deploy-pages.yml`이 정적 파일(`app/static`)을 `gh-pages` 환경에 자동 배포합니다.
- API 엔드포인트가 GitHub Pages 도메인과 다를 경우 `app/static/config.js`에서 `window.STATIC_DIVE_API_BASE` 값을 원하는 API 주소로 설정하세요.
- 예시: `window.STATIC_DIVE_API_BASE = "https://your-api.example.com";`

## API 요약
- **헬스체크**: `GET /health` → `{ "status": "ok" }`
- **파티 생성**: `POST /parties`
  - 필수: `title`, `host_name`, `visibility`(public/private)
  - 비공개 파티는 초대 코드를 자동 생성하거나 `invite_code`로 직접 설정 가능.
- **파티 목록/검색**: `GET /parties?visibility=public&role=힐러&q=던전`
- **파티 상세**: `GET /parties/{party_id}`
- **슬롯 추가/조회**: `POST /parties/{party_id}/slots`, `GET /parties/{party_id}/slots`
- **비공개 파티 입장**: `POST /parties/join-by-code`
  - 입력: `invite_code`, `applicant_name`, 필요시 `slot_id`, `gear_preset`
  - 코드로 비공개 파티를 조회 후 지원자 레코드를 대기 상태로 생성하고 파티 정보 반환
- **공개 파티 신청**: `POST /parties/{party_id}/apply`
  - 공개 파티 전용 신청 엔드포인트
  - `slot_id`, `gear_preset`(프리셋 JSON) 전달 가능
- **파티원 상태 갱신**: `POST /parties/{party_id}/members/{member_id}/state`
  - 상태: applied → accepted → locked / rejected / kicked
  - 정원(capacity)이 찼을 때 accepted/locked 전환 시 409 반환
- **파티원 추방**: `DELETE /parties/{party_id}/members/{member_id}?host_name=파티장` (파티장 이름 확인 후 추방)
- **초대 코드 재발급**: `POST /parties/{party_id}/invite-code` (비공개 파티 전용, `join-by-code` 흐름에서 사용)

### 예시 gear_preset JSON
```json
{
  "role": "힐러",
  "weapon": {"line": "Holy Staff", "item": "Great Holy Staff", "tier": 7},
  "armor": {
    "helmet": {"type": "Cleric Cowl", "tier": 6},
    "chest": {"type": "Cleric Robe", "tier": 6},
    "boots": {"type": "Scholar Sandals", "tier": 6}
  },
  "offhand": {"type": "Mistcaller", "tier": 6},
  "consumables": {"food": "Omelette", "potion": "Major Healing"},
  "mount": "Swiftclaw",
  "ip_target": 1200
}
```
