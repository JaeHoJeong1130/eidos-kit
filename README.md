# Eidos Kit

프로젝트의 개발 규칙·방향·작업 이력을 사람과 에이전트가 함께 활용하기 위한 공용 키트입니다.
현재는 **비공개 협업 시험 배포**입니다. 공개 오픈소스 라이선스는 아직 선택하지 않았습니다.

- **Harness 1.5.0:** 작업 진입점, 규칙 연결, 위험도별 검증·리뷰, 실패 예방 지식
- **Eidos 3.3.0:** Direction, Stage, Work, 현재 작업 조회와 로컬 claim

프로젝트별 일관성, 실수 재발 방지, 개발 이력, 방향 유지, Git 협업, 공용 구조의 버전 관리를 지원합니다.
제품 코드와 도메인 규칙은 각 프로젝트가 소유합니다. 실제 모델 성능이나 토큰 절감 효과는 아직 평가하지 않았습니다.

## 받아서 설치하기

Git과 Python 3.13을 준비합니다. Windows PowerShell 예시이며, 다른 환경에서는 `py -3.13`을 해당 Python 실행 명령으로 바꿉니다.
키트 저장소와 적용할 프로젝트는 서로 다른 디렉터리에 둡니다.

```powershell
# GitLab 프로젝트 화면의 Clone URL을 사용합니다.
git clone <Clone-URL> eidos-kit
cd eidos-kit

# 새 시험 프로젝트를 먼저 만들어 적용해볼 수 있습니다.
git init C:\project\eidos-demo
py -3.13 -B kits/harness/v1/harness_kit.py install `
  --root C:\project\eidos-demo `
  --project-id project:eidos-demo --project-name "Eidos Demo"

py -3.13 -B kits/harness/v1/harness_kit.py doctor --root C:\project\eidos-demo
```

`install`은 Git 저장소 최상위 디렉터리를 대상으로 하며, 기존 관리 대상 파일을 덮어쓰지 않습니다.
이미 `AGENTS.md`나 `.agents/`를 사용하는 프로젝트는 먼저 상태를 확인합니다.

```powershell
py -3.13 -B kits/harness/v1/harness_kit.py assess --root C:\project\existing-project
```

기존 규칙을 보존하는 이관에는 `migrate`, 신뢰 검증이 가능한 기존 키트 설치의 갱신에는 `upgrade`를 사용합니다.
충돌하는 파일을 삭제해서 강제로 설치하지 마세요. [설치·이관·업그레이드 조건](kits/harness/v1/README.md)을 먼저 확인합니다.

## 프로젝트 설정과 첫 Work

설치한 프로젝트에서 다음을 설정합니다.

1. `.agents/context.json`과 routing에 프로젝트의 규칙·코드·테스트 위치를 연결합니다.
2. `.agents/eidos/direction.md`에 목적·범위·Stage와 완료 기준을 작성합니다.
3. `.agents/eidos/identity.json`에 실제 작업 담당자를 등록합니다. 아래 ID와 표시 이름은 예시입니다.

```json
{
  "schema_version": 1,
  "status": "configured",
  "members": [
    {"id": "member:developer", "display_name": "Developer", "status": "active"}
  ],
  "aliases": []
}
```

프로젝트 루트에서 검증합니다. Git commit은 자동 생성되지 않습니다. 팀에서 설정을 확인한 뒤 일반 Git 절차로 공유하세요.

```powershell
py -3.13 -B .agents/tools/eidos.py validate --root .
py -3.13 -B .agents/tools/eidos.py focus --root . --summary --json
```

Work 시작에는 Git HEAD가 필요하므로 새 프로젝트는 먼저 초기 commit을 만들어야 합니다.
설치·프로젝트 설정을 검토하여 commit한 다음, 작업 범위에 맞는 `start.json`을 만듭니다.

```json
{
  "slug": "document-project-rules",
  "title": "Document project input rules",
  "owner": "member:developer",
  "stage": "S01",
  "write_scope": ["README.md"],
  "risk": "R1",
  "actor": "agent:codex",
  "intent": "Give contributors the same input and verification rules.",
  "completion_criteria": "README identifies accepted inputs and the verification command.",
  "verification_plan": "Check the documented rules against the parser and run the documented check."
}
```

```powershell
py -3.13 -B .agents/tools/eidos.py work start --root . --input start.json
```

반환된 `work_id`와 `claim_id`를 보관합니다. 실제 작업과 검증을 마친 후, 아래 `finish.json`에 두 ID와 결과를 넣습니다.
예시 결과를 실행하지 않은 검증 근거로 제출하지 마세요.

```json
{
  "work_id": "<returned-work-id>",
  "claim_id": "<returned-claim-id>",
  "actor": "agent:codex",
  "status": "done",
  "result": "Documented accepted inputs and the verification command.",
  "evidence": "Checked the input rules against the parser; the documented check passed."
}
```

```powershell
py -3.13 -B .agents/tools/eidos.py work finish --root . --input finish.json
```

시작·종료 명령은 테스트나 commit을 자동 실행하지 않습니다. 초기 claim은 1시간이며 장기 작업은 갱신해야 합니다.
정확한 입력·재시도·복구 규칙은 설치된 프로젝트의 `.agents/workflows/eidos-v3.md`를 따릅니다.

## 직원 간 협업

- 프로젝트의 규칙·Direction·Work는 해당 프로젝트의 Git 저장소에서 공유합니다.
- 키트 개선은 GitLab 브랜치와 Merge Request로 검토합니다. GitHub에는 검토한 동일 버전을 배포합니다.
- claim은 같은 Git common directory를 공유하는 worktree 사이의 조정 수단입니다. 직원별 PC를 잠그거나 원격 미공유 작업을 알려주지는 않습니다.
- 변경마다 작업 담당자와 범위를 나누고, 코드 충돌은 일반 Git 리뷰·병합 절차로 해결합니다.
- 키트 저장소를 pull해도 프로젝트 설치는 바뀌지 않습니다. 검토한 버전에서 아래 명령으로 명시적으로 갱신합니다.

```powershell
# 키트 저장소에서 실행
py -3.13 -B kits/harness/v1/harness_kit.py diff --root C:\project\existing-project
py -3.13 -B kits/harness/v1/harness_kit.py upgrade --root C:\project\existing-project
py -3.13 -B kits/harness/v1/harness_kit.py doctor --root C:\project\existing-project
```

관리 대상 파일을 직접 바꾼 경우 업그레이드가 거부될 수 있습니다. 프로젝트 소유 파일과 기존 기록은 보존합니다.

## 검증과 배포 범위

```powershell
py -3.13 -B scripts/verify.py
```

표준 라이브러리와 Git으로 키트 설치·업그레이드·복구·Work·claim·focus 회귀 테스트를 실행합니다.
EidosWeb의 업무 프로그램이나 개인 Codex 설치는 필요하지 않습니다. 각 테스트의 Git commit은 임시 저장소에서만 만듭니다.

이 초기 배포는 공용 키트와 가상 데이터를 사용하는 테스트만 포함합니다. EidosWeb의 팀 기록, 설치 registry,
프로젝트 identity, 내부 Work·Failure, 기존 Git 이력은 포함하지 않습니다.
`release-manifests/`는 이전 설치의 신뢰 검증에 필요하므로 과거 파일을 수정하지 않습니다.
체크아웃 시 줄바꿈 변환으로 hash가 달라지지 않도록 `.gitattributes`에서 자동 텍스트 변환을 끕니다.

- [Harness 상세 안내](kits/harness/v1/README.md)
- [Eidos 상세 안내](kits/eidos/v3/README.md)
- [향후 모델 평가 과제](kits/eidos/v3/evaluation/tasks.json): 정의만 포함하며 모델 실행 결과가 아닙니다.

공개 전환과 라이선스 지정, 자동 미러링은 이번 시험 배포에 포함하지 않습니다.
