# Eidos Kit

![Eidos — 안전모를 쓴 새싹 캐릭터가 건축 현장을 관리하는 배너](assets/eidos-banner.png)

에이전트가 **우리 프로젝트의 규칙을 따르고, 지난 작업을 이어서 개발하도록 돕는 도구**입니다.

**Harness Kit만 설치하면 Eidos도 함께 설치됩니다.** Eidos를 먼저 따로 설치할 필요는 없습니다.

- **Harness:** 어떤 규칙을 읽고, 어떻게 작업하고 검증할지 안내합니다.
- **Eidos:** 프로젝트 목표, 할 일, 작업 결과를 기록합니다.

처음에는 **받기 → 설치 → 프로젝트에 맞게 정리 → 실제 Work로 확인 → 개발** 순서로 진행합니다.

**기존 프로젝트는 키트 적용만으로 완전히 최적화되지 않습니다.** 설치 후에도 기존 규칙과의 중복,
실제 목표·담당자, 변경 영향별 검증 범위를 맞춰야 합니다. GitLab·GitHub 어디에서 받았든
[설치 후 프로젝트에 맞게 정리하기](kits/harness/v1/ADOPTION.md)를 따라 운영 준비를 확인하세요.

## 프로젝트 폴더는 어떻게 나누나요?

Harness 1.8.1의 공통 계약과 [폴더 배치 가이드](kits/harness/v1/template/.agents/harness/repository-layout.md)에 기준과 예시가 들어 있습니다.
설치된 프로젝트에서는 `.agents/harness/repository-layout.md`를 읽으면 됩니다.

| 폴더 | 용도 |
| --- | --- |
| `_docs/` | 처음 보는 사람이 목적·현재 구조·동작·사용법·제약을 이해할 소수의 핵심 문서 |
| `_blueprint/` | 상세 설계·제작 명세·ADR·구체적인 구현 계획과 로드맵 |
| `_note/` | 검토 메모, 아이디어·계획 초안, 작업 중 논의 |
| `_reference/` | 외부 규격·매뉴얼·논문 등 출처가 있는 참고자료 |
| `_evidence/` | 검증·실험·인수 결과 등 판단을 뒷받침하는 증거 |
| `config/` | 코드·테스트·배포가 실제 사용하는 설정·스키마·시나리오 |
| `_meta/` | 문서판과 저장소 관리용 메타데이터 |
| `.cache/` | 재생성 가능한 캐시·임시 산출물; 내용은 Git에서 제외하고 명시적인 `.gitkeep` 예외는 보존 |
| `.agents/eidos/` | 프로젝트 방향과 실행 Work; 현재 작업 목록은 기록에서 도출 |

검토 중인 메모와 초안은 `_note/`, 확정된 프로젝트 설명은 `_docs/`, 구체적인 설계와 구현 계획은 `_blueprint/`에 정리합니다.
실행할 작업의 담당자·진행·결과는 Eidos Work로 관리합니다. 프로젝트 특성에 맞는 별도 폴더도 사용할 수 있습니다.
빈 Git 프로젝트에 신규 설치하면 기본 안내 폴더와 `_meta/layout.json`이 생성됩니다. 안내 파일은 프로젝트 소유이며 실제 프로젝트 설명으로 채워야 합니다.
기존 프로젝트는 명시적인 폴더 용도를 우선합니다. 기본 설치와 업그레이드는 기존 문서를 자동으로 이동하지 않습니다.
`install --layout none`은 안내 폴더를 만들지 않고, `--layout standard`는 기존 프로젝트에도 없는 기본 안내 파일만 추가합니다.

`_docs`는 인덱스와 필요한 핵심 문서 몇 개로 작게 유지합니다. 상세한 제작 계획은 `_blueprint`로 분리하고 링크합니다.
`_meta/layout.json`에 폴더 역할, 읽을 문서 목록, 문서 수 한도와 예외 이유를 선언합니다.
이미 설치된 프로젝트에서는 다음 명령으로 확인합니다.

```powershell
py -3.13 -B .agents/tools/layout.py check --root . --json
py -3.13 -B .agents/tools/layout.py preview --root . --json
```

기존 프로젝트에 기본 안내 파일이 필요하면 키트 폴더에서 먼저 미리보기를 확인합니다.

```powershell
py -3.13 -B kits/harness/v1/harness_kit.py layout init --root C:\project\existing-project
# 미리보기를 검토한 뒤에만 적용: 기존 파일은 덮어쓰지 않음
py -3.13 -B kits/harness/v1/harness_kit.py layout init --root C:\project\existing-project --apply
```

검사와 preview는 문서를 옮기지 않습니다. 검사 통과만으로 문서 내용의 적절성이 보장되지는 않습니다.
기존 문서를 옮길 때는 연결된 코드·링크를 확인하고, 원본과 경로 대응표·해시를 보존한 뒤 독립 검토를 받습니다.

## 규칙이 빠지는 것을 어떻게 확인하나요?

Harness **1.7.0**에는 [규칙 보존 안내](kits/harness/v1/template/.agents/harness/requirements.md)와 읽기 전용 선택·검사 도구가 들어 있습니다.
프로젝트마다 기존 규칙과 근거를 조사해 `_meta/requirements/registry.json`을 만들고, 자신의 코드·문서·테스트 위치를 연결합니다.
설치되는 예시는 형식을 설명하기 위한 자료이며, 실제 규칙 목록은 자동 생성하거나 덮어쓰지 않습니다.

- 작업 전에는 목적과 변경 경로로 관련 규칙만 선택합니다. 배포 작업에서도 해당 분야의 규칙은 유지합니다.
- 작업 후에는 실제 변경 경로를 대조해 규칙 삭제, 근거 없는 변경, 끊어진 참조와 누락을 검사합니다.
- 적용한 규칙 ID와 처리 결과·검증 근거는 Eidos Work에 남깁니다. 의미상 충족 여부는 행동 테스트와 독립 검토로 확인합니다.

설치된 프로젝트에서 사용할 명령입니다. `--path`는 실제 변경할 프로젝트 경로로 바꿉니다.

```powershell
py -3.13 -B .agents/tools/requirements.py select --route change --path src
py -3.13 -B .agents/tools/requirements.py check --base HEAD --json
```

규칙 목록이 없으면 미설정 상태를 알립니다. 먼저 기존 지침을 검토하고 도입 여부를 기록합니다.
목록을 도입한 프로젝트는 `check`를 기존 공식 검증 명령의 빠른 사전 검사로 연결하면 됩니다.
이 배포는 Harness 1.9.1과 Eidos 3.4.0을 함께 제공합니다.

새 Work 파일은 `W-20260918-m-h-a1b2c3d4e5f6-iv3-manual.md`처럼 최초 멤버 ID와
12자리 무작위 값을 포함합니다. 같은 사람이 여러 창이나 PC에서 작업해도 공용 순번을
맞출 필요가 없습니다. 파일명은 `.md`를 포함해 최대 80자이며, 제목 부분만 최대 24자로
줄이고 문서 안의 전체 제목은 보존합니다. 긴 체크아웃 경로까지 보장하는 제한은 아닙니다.
기존 Work 파일과 참조는 그대로 유효합니다. 새 형식을 공유하기 전에 읽는 쪽도 키트를
업그레이드해야 하며, 작업 소스의 동시 수정 충돌은 기존 claim·Git 절차로 조정합니다.

## 1. 키트 받기

Git과 Python 3.13이 설치된 PC에서 PowerShell을 엽니다.
접근 권한이 있는 GitLab 또는 GitHub 키트 저장소에서 **Clone 주소**를 복사해 아래 `<Clone-URL>` 자리에 넣습니다.

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
이는 키트 구조와 계약 검사를 통과했다는 뜻입니다. 실제 운영 준비는 아래 설정과 Work 실행으로 별도 확인합니다.

**이미 개발 중인 프로젝트에 적용하려면** 아래의 [기존 프로젝트에 적용하기](#기존-프로젝트에-적용하기)를 먼저 확인하세요.

## 3. 프로젝트에 맞게 정리하기

**이제 설치한 프로젝트 폴더를 Codex에서 엽니다.** 위 예시에서는 `C:\project\eidos-demo`입니다.
처음 한 번, 아래 내용을 우리 프로젝트에 맞게 채웁니다.

- **무엇을 만드는가:** `.agents/eidos/direction.md`에 목표와 진행 단계를 적습니다.
- **어떤 규칙을 따르는가:** `.agents/context.json`과 routing에 기존 규칙·코드·테스트 위치를 연결합니다.
- **누가 담당하는가:** `.agents/eidos/identity.json`에 팀원을 등록합니다.

기존 규칙의 정본·실패 기록 위치·변경 영향별 검증 절차도 함께 정리합니다.
[후속 정리 지침](kits/harness/v1/ADOPTION.md)에 보존할 항목, 검사를 줄일 때의 조건,
실제 Work로 확인하는 방법과 에이전트에게 전달할 요청문이 있습니다. 신규 프로젝트에도 실제 설정은 필요합니다.

팀원 등록은 아래 예시의 ID와 이름을 실제 담당자에 맞게 바꾸면 됩니다. 이미 등록된 팀원이 있으면 기존 목록을 보존합니다.

### U인 팀원이 자기 ID로 시작하는 예시

**참여자 목록은 프로젝트가 공유하고, 이번 작업의 담당자는 각자 선택합니다.**
H는 `member:h`, U는 `member:u`처럼 소문자 ID를 사용합니다. 이니셜이 같다면 서로 다른 ID를 정합니다.
`member:h`나 아래 예시의 `member:developer`는 모두가 함께 쓰는 기본값이 아닙니다.

U인 팀원은 에이전트에게 다음 요청을 전달하면 됩니다. 폴더 경로는 실제 위치로 바꿉니다.

```text
나는 팀원 U이고 Eidos ID는 member:u야.
받아 둔 키트 폴더는 <키트 폴더>, 적용할 프로젝트는 <내 프로젝트 폴더>야.
프로젝트 상태에 맞는 공식 도구로 Harness/Eidos 키트를 적용해줘.
내 프로젝트의 .agents/eidos/identity.json에 member:u가 활성 참여자로
등록되어 있는지 확인하고, 없으면 U로 추가해줘.
기존 참여자와 aliases, 과거 Work는 보존해줘.
이번 세션의 내 새 Work는 owner member:u, Codex actor agent:codex로 작성해줘.
```

`members`에 넣을 U의 항목은 다음과 같습니다. 신규 설치의 빈 목록은 `status`를 `configured`로 바꾸고
참여자를 넣습니다. 이미 설정된 파일은 기존 목록과 aliases를 유지한 채 필요한 항목만 추가합니다.

```json
{"id": "member:u", "display_name": "U", "status": "active"}
```

참여자 목록은 Git으로 공유합니다. 다른 팀원이 clone했다고 자기 정보만 남기도록 교체하지 않습니다.
이미 키트가 설치된 프로젝트를 clone했다면 재설치할 필요 없이 본인 등록 상태를 확인하고 시작합니다.

새 에이전트 세션에서도 **“나는 U야. 이번 작업은 member:u로 진행해줘.”**라고 알려주세요.
직접 Work 시작 JSON을 만들 때는 `"owner": "member:u"`를 사용합니다.
`actor`는 실행 에이전트라서 Codex를 쓰는 H와 U 모두 `agent:codex`일 수 있습니다.

현재는 GitHub·GitLab 로그인이나 Git 작성자에서 Eidos ID를 자동으로 선택하지 않으며,
PC별 기본 owner를 저장하는 전용 명령도 없습니다. ID를 모르면 에이전트가 확인해야 합니다.
공유 `AGENTS.md`에 “항상 U로 작업”을 적으면 다른 팀원에게도 적용되므로 개인 선택은 세션에서 전달합니다.
Git 커밋 작성자의 이름·이메일은 별도 설정이며, Eidos owner를 바꿔도 함께 바뀌지 않습니다.

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

적용이 끝나면 [설치 후 프로젝트에 맞게 정리하기](kits/harness/v1/ADOPTION.md)를 진행하세요.
기존 규칙과 새 진입점의 연결, 실제 Direction과 담당자, 검증 범위를 맞춘 뒤 필요한 Work 하나를 완료합니다.
업그레이드는 프로젝트 소유 설정을 보존하므로 낡거나 중복된 로컬 지침도 자동으로 최적화하지 않습니다.
설치 결과와 운영 준비 결과, 남은 미설정·추가 정리 항목을 구분해서 기록하세요.

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

현재 버전은 **Harness 1.9.1 / Eidos 3.4.0**입니다. 비공개 협업 시험 배포이며 공개 오픈소스 라이선스는 아직 선택하지 않았습니다.
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
