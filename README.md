# Eidos Kit

에이전트가 **우리 프로젝트의 규칙을 따르고, 지난 작업을 이어서 개발하도록 돕는 도구**입니다.

**Harness Kit만 설치하면 Eidos도 함께 설치됩니다.** Eidos를 먼저 따로 설치할 필요는 없습니다.

- **Harness:** 어떤 규칙을 읽고, 어떻게 작업하고 검증할지 안내합니다.
- **Eidos:** 프로젝트 목표, 할 일, 작업 결과를 기록합니다.

처음에는 **받기 → 설치 → 목표·담당자 설정 → 개발**의 네 단계만 따라가면 됩니다.

## 1. 키트 받기

Git과 Python 3.13이 설치된 PC에서 PowerShell을 엽니다.
GitLab 프로젝트 화면에서 **Clone 주소**를 복사해 아래 `<Clone-URL>` 자리에 넣습니다.

```powershell
git clone <Clone-URL> eidos-kit
cd eidos-kit
```

이제 `eidos-kit` 폴더에 설치 도구가 준비됐습니다. 실제 개발할 프로젝트는 별도 폴더에 둡니다.

```text
eidos-kit/     설치·업데이트 도구가 있는 폴더
eidos-demo/    규칙과 작업 기록을 적용할 프로젝트 폴더
```

## 2. 시험 프로젝트에 설치하기

처음이라면 새 `eidos-demo` 프로젝트로 먼저 확인해보세요.
**지금 있는 `eidos-kit` 폴더에서** 다음 명령을 실행합니다.

```powershell
git init C:\project\eidos-demo
py -3.13 -B kits/harness/v1/harness_kit.py install `
  --root C:\project\eidos-demo `
  --project-id project:eidos-demo --project-name "Eidos Demo"
```

`--root`는 **설치할 프로젝트 폴더**, `--project-id`는 **프로젝트의 고유 ID**, `--project-name`은 **표시할 이름**입니다.
이 한 번의 설치로 Harness와 Eidos가 함께 들어갑니다. 설치가 끝나면 다음 명령으로 확인합니다.

```powershell
py -3.13 -B kits/harness/v1/harness_kit.py doctor --root C:\project\eidos-demo
```

오류 없이 `doctor: ok`가 나오면 설치 확인이 끝난 것입니다.

**이미 개발 중인 프로젝트에 적용하려면** 아래의 [기존 프로젝트에 적용하기](#기존-프로젝트에-적용하기)를 먼저 확인하세요.

## 3. 목표와 담당자 설정하기

**이제 설치한 프로젝트 폴더를 Codex에서 엽니다.** 위 예시에서는 `C:\project\eidos-demo`입니다.
처음 한 번, 아래 내용을 우리 프로젝트에 맞게 채웁니다.

- **무엇을 만드는가:** `.agents/eidos/direction.md`에 목표와 진행 단계를 적습니다.
- **어떤 규칙을 따르는가:** `.agents/context.json`과 routing에 기존 규칙·코드·테스트 위치를 연결합니다.
- **누가 담당하는가:** `.agents/eidos/identity.json`에 팀원을 등록합니다.

팀원 등록은 아래 예시의 ID와 이름을 실제 담당자에 맞게 바꾸면 됩니다. 이미 등록된 팀원이 있으면 기존 목록을 보존합니다.

<details>
<summary>팀원 등록 JSON 예시 보기</summary>

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

</details>

프로젝트 폴더의 PowerShell에서 설정을 검사합니다.

```powershell
py -3.13 -B .agents/tools/eidos.py validate --root .
```

설정을 확인한 뒤 Git에 commit하여 팀과 공유합니다. **새 Git 프로젝트는 첫 Work를 시작하기 전에 초기 commit이 필요합니다.**
설치나 설정 검사 명령이 commit까지 자동으로 만들지는 않습니다.

## 4. 개발 시작하기

이제 Codex에 원하는 개발 작업을 요청하면 됩니다. 예를 들면 다음과 같습니다.

> AGENTS.md를 읽고, CSV 파일을 읽는 기능을 추가해줘.
> 현재 목표와 관련 규칙을 확인하고, 작업 계획과 검증 결과를 Work에 남겨줘.

**Work는 한 번의 개발 작업을 남기는 기록**입니다. 무엇을 왜 바꿨는지, 검증 결과가 무엇인지 다음 작업에서도 확인할 수 있습니다.
현재 진행 중인 작업은 아래 명령으로 확인합니다.

```powershell
py -3.13 -B .agents/tools/eidos.py focus --root . --summary --json
```

일반적인 개발 요청은 에이전트와 진행하면 됩니다. 직접 명령을 사용하려는 경우에만 아래 예시를 참고하세요.

<details>
<summary>Work를 직접 시작하고 종료하는 명령 보기</summary>

프로젝트 폴더에서 작업 범위에 맞는 `start.json`을 만듭니다. owner와 Stage는 프로젝트 설정에 맞춰 바꿉니다.

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

</details>

## 기존 프로젝트에 적용하기

키트 폴더에서 대상 프로젝트의 상태를 먼저 확인합니다.

```powershell
py -3.13 -B kits/harness/v1/harness_kit.py assess --root C:\project\existing-project
```

| 프로젝트 상태 | 사용할 절차 |
| --- | --- |
| 처음 설치하며 기존 관리 대상 파일과 충돌이 없음 | `install` |
| 기존 `AGENTS.md`·`.agents/` 규칙을 보존하며 합치거나, Eidos 단독 설치에 Harness를 추가함 | 조건을 확인한 뒤 `migrate` |
| Harness/Eidos 키트가 이미 설치되어 있음 | 설치 형태에 맞는 키트의 `upgrade` |

기존 파일을 삭제해서 강제로 설치하지 마세요. 이관 조건과 명령은 [상세 설치 안내](kits/harness/v1/README.md)에 있습니다.

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

현재 버전은 **Harness 1.5.0 / Eidos 3.3.0**입니다. 비공개 협업 시험 배포이며 공개 오픈소스 라이선스는 아직 선택하지 않았습니다.
제품 코드와 도메인 규칙은 각 프로젝트가 소유합니다. 실제 모델 성능이나 토큰 절감 효과는 아직 평가하지 않았습니다.

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
