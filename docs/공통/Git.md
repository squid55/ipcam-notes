# Git

> 변경 이력을 관리하는 도구.
> 펌웨어 제품에서는 **「이 이미지가 어느 소스에서 나왔는가」를 답하는 수단**이기도 하다.

## 왜 필요한가

혼자 개발해도 필요하다. 「어제는 됐는데」의 원인을 찾는 가장 빠른 방법이
`git bisect` 이고, 그것은 이력이 있어야 쓸 수 있다.

그리고 제품에서는 **출하한 펌웨어와 소스를 잇는 것**이 요구사항이 된다.
릴리스마다 태그를 달고 산출물 해시를 기록해 두지 않으면
나중에 「이 기기에 뭐가 들어 있나」에 답할 수 없다.

## 최소 이해 수준

- **세 영역.**
  ```
  작업 디렉터리  →  스테이지(index)  →  저장소(커밋)
                add                commit
  ```
  `git status` 가 세 영역의 차이를 보여준다.
- **매일 쓰는 명령.**
  ```
  git status              지금 상태
  git diff                작업 디렉터리 vs 스테이지
  git diff --staged       스테이지 vs 마지막 커밋
  git add -p              조각 단위로 골라 담기  ← 매우 유용
  git commit              기록
  git log --oneline --graph --decorate --all
  git show <커밋>          그 커밋의 변경 내용
  ```
- **`git add -p` 를 쓴다.** 한 커밋에 한 가지 변경만 담을 수 있다.
  **디버그 출력과 실제 수정이 한 커밋에 섞이면** 나중에 되돌리기 어렵다.
- **커밋 메시지.** 첫 줄은 요약(50자 내), 빈 줄, 그리고 **왜 그렇게 했는지.**
  무엇을 바꿨는지는 diff 가 말해 주므로 **이유를 적는 것**이 가치가 있다.
  ```
  fix: 스트림 종료 시 세션 유휴 만료를 확인하도록

  긴 연결이 한 번 인증을 통과한 뒤 다시 확인하지 않아
  관리 화면은 잠기는데 영상은 계속 흐르고 있었다.
  갱신하지 않는 읽기 전용 검사를 따로 두어 처리한다.
  ```
- **되돌리기 세 가지를 구분한다.**

  | 명령 | 무엇을 하는가 | 이력 |
  |---|---|---|
  | `git restore <파일>` | 작업 디렉터리를 마지막 커밋으로 | 변경 내용이 **사라진다** |
  | `git revert <커밋>` | 그 커밋을 취소하는 새 커밋 | 남는다 (안전) |
  | `git reset --hard` | 브랜치를 옮기고 작업 내용도 버린다 | **위험** |

  ⚠ **`git restore`(옛 `git checkout <파일>`)를 임시 되돌리기로 쓰지 않는다.**
  커밋하지 않은 변경이 복구 불가능하게 사라진다.
  잠시 치워 두려면 `git stash` 를 쓴다.
- **브랜치는 가볍다.** 포인터 하나다. 실험할 때는 항상 브랜치를 만든다.
  ```sh
  git switch -c try/new-encoder
  ```
- **원격과 동기.**
  ```sh
  git fetch                     가져오기만 (작업에 영향 없다)
  git pull --rebase             가져와 내 커밋을 위로 쌓는다
  git push origin <브랜치>
  ```
  **`git fetch` 는 안전하다.** 먼저 `fetch` 하고 `log` 로 확인한 뒤 합치는 습관이 낫다.
- **`.gitignore` 를 먼저 만든다.** 빌드 산출물과 비밀 파일이 들어가면
  나중에 지워도 **이력에 남는다.**
  ```
  build/
  output/
  *.o
  *.ko
  .config
  *.key
  *.pem
  ```
- **비밀을 커밋하면 되돌릴 수 없다고 생각한다.** 이력에서 지우려면
  전체 재작성이 필요하고, 이미 push 했으면 **그 값을 폐기하는 것이 유일한 대응**이다.

## 직접 해보기

### 1. 무엇이 들어갈지 확인하고 커밋

```sh
git status
git diff                     # 아직 담지 않은 변경
git add -p                   # 조각 단위로 확인하며 담기
git diff --staged            # 담은 것을 다시 확인  ← 이 단계를 빠뜨리지 않는다
git commit
```

**`git diff --staged` 로 마지막 확인**하는 습관이 사고를 막는다.

### 2. 비밀 파일이 들어가지 않는지 점검

커밋 전에 돌려 볼 수 있다.

```sh
git diff --staged --name-only
git diff --staged | grep -nEi 'password|secret|BEGIN .*PRIVATE KEY|api[_-]?key' | head
```

이미 추적 중인 파일을 빼려면:

```sh
git rm --cached path/to/secret
printf 'path/to/secret\n' >> .gitignore
```

⚠ **이력에서는 사라지지 않는다.** 이미 커밋했다면 그 값을 교체한다.

### 3. 언제 깨졌는지 찾기

```sh
git bisect start
git bisect bad                        # 지금은 깨졌다
git bisect good <잘 되던 태그나 커밋>
# 시험 → git bisect good 또는 bad 반복
git bisect reset
```

자동화:

```sh
git bisect run sh -c 'make -s && ./scripts/smoke-test.sh'
```

커밋 100개에서 **7번만 시험**한다. → [디버깅](디버깅.md)

### 4. 누가 왜 이 줄을 바꿨는지

```sh
git blame -L 120,140 src/live.c
git log -L 120,140:src/live.c         # 그 구간의 변경 이력만
git log -S 'session_peek' --oneline   # 그 문자열이 추가·삭제된 커밋
```

**`git log -S` 가 「이 함수가 언제 왜 생겼나」를 찾는 가장 빠른 방법**이다.

### 5. 잠시 치워 두기

```sh
git stash push -m "인코더 실험"
git stash list
git stash pop                         # 되돌린다
```

`restore` 로 버리는 것보다 안전하다.

### 6. 릴리스를 소스와 잇기

펌웨어 제품에서 실제로 필요한 절차다.

```sh
# 태그를 달고
git tag -a v1.01.00 -m "첫 양산 베이스라인"
git push origin v1.01.00

# 산출물 해시를 함께 기록
md5sum output/images/rootfs.ubifs >> RELEASES.md
sha256sum output/images/rootfs.ubifs >> RELEASES.md
git log -1 --format='%H %ci' >> RELEASES.md
```

**태그 · 커밋 해시 · 이미지 해시 세 개를 묶어 두면**
나중에 「이 기기의 펌웨어가 어느 소스인가」에 답할 수 있다.
→ [무결성과 서명 업데이트](../보안/무결성과서명업데이트.md)

### 7. 실제 보드와 저장소가 같은지 확인

```sh
# 보드에서 파일별 해시
find /App -type f | sort | while read -r f; do md5sum "$f"; done > /tmp/board.md5

# 호스트에서 같은 방식으로 만들어 대조
diff <(sort -k2 board.md5) <(sort -k2 host.md5)
```

**이미지 전체 해시가 달라도 파일별로는 같을 수 있다** —
파일시스템 컨테이너의 비결정성 때문이다.
그래서 대조는 파일 단위로 한다.
→ [플래시 · 파일시스템](../BSP/플래시와파일시스템.md)

### 8. 대용량 파일과 바이너리

```sh
# 저장소에서 큰 것 찾기
git rev-list --objects --all | \
  git cat-file --batch-check='%(objecttype) %(objectname) %(objectsize) %(rest)' | \
  awk '$1=="blob" && $3 > 5000000 {print $3, $4}' | sort -rn | head
```

펌웨어 이미지를 저장소에 넣으면 **클론이 급격히 무거워진다.**
릴리스 자산으로 올리거나 별도 저장소를 쓴다.

## 더 들어가면

- **커밋 서명.** `git commit -S` 로 GPG 서명한다.
  「누가 만든 커밋인가」를 검증할 수 있어 공급망 관점에서 값이 있다.
- **브랜치 보호.** `main` 에 직접 push 를 막고 리뷰를 거치게 한다.
  ⚠ **비공개 저장소에서는 유료 요금제가 필요한 경우가 있다.**
  그때는 규칙으로 운영하거나 자체 호스팅을 고려한다.
- **모노레포 vs 분리.** 펌웨어 · 문서 · 도구를 한 저장소에 둘지.
  릴리스 단위가 같으면 한곳이 편하고, 공개 범위가 다르면 나눠야 한다.
- **서브모듈과 서브트리.** 벤더 BSP 를 포함하는 방법.
  서브모듈은 버전만 가리키고, 서브트리는 내용을 복사한다.
  **서브모듈은 클론할 때 잊기 쉬워** 빌드 실패의 원인이 된다.
- **훅.** `pre-commit` 으로 `shellcheck` 나 비밀 검사를 자동으로 돌린다.
  ```sh
  # .git/hooks/pre-commit (실행 권한 필요)
  git diff --cached --name-only -z | xargs -0 -r shellcheck -s sh 2>/dev/null
  ```
  훅은 저장소에 자동 공유되지 않는다 — `core.hooksPath` 로 디렉터리를 지정한다.
- **`git worktree`.** 같은 저장소의 여러 브랜치를 각각 다른 디렉터리에 둔다.
  빌드 산출물이 섞이지 않아 임베디드 작업에 유용하다.
- **라이선스와 공개 범위.** 공개 저장소에 올릴 때 무엇이 들어가는지 확인한다.
  벤더 NDA 자료 · 고객 정보 · 취약점 상세가 섞이기 쉽다.

## 흔한 오해

### 「커밋하지 않아도 되돌릴 수 있다」

커밋하지 않은 변경은 git 이 모른다. `git restore` 나 `git checkout --` 은
**그것을 복구 없이 지운다.** 조금이라도 아까운 것은 먼저 커밋하거나 `stash` 한다.

### 「push 하기 전이면 무엇이든 고칠 수 있다」

맞지만 `reset --hard` 로 버린 커밋은 찾기 어렵다.
`git reflog` 에 잠시 남지만 영구적이지 않다.

```sh
git reflog | head -20        # 최근 HEAD 이동 기록
```

### 「`git pull` 이 기본이다」

`pull` 은 `fetch` + 병합이고, 예상치 못한 병합 커밋이 생긴다.
**`fetch` 로 먼저 보고 결정**하는 편이 안전하다.

```sh
git fetch && git log --oneline HEAD..@{u}    # 원격에 뭐가 새로 왔는지
```

### 「비밀을 지우고 커밋하면 없어진다」

이력에 남는다. 그리고 이미 push 했으면 다른 사람이나 캐시에 복제됐을 수 있다.
**유일한 안전한 대응은 그 값을 폐기하고 새로 만드는 것**이다.

### 「커밋 메시지는 나중에 정리하면 된다」

나중에 왜 그랬는지 기억하지 못한다. 특히 **하드웨어 관련 결정**은
근거가 회로도나 데이터시트에 있는데, 그 맥락이 메시지에 없으면
반년 뒤에 같은 조사를 다시 한다.

### 「빌드 산출물도 넣어 두면 편하다」

저장소가 급격히 커지고, 이력에서 지울 수 없다.
그리고 **산출물이 소스와 일치한다는 보장도 없다.**
태그 + 해시 기록으로 잇는 것이 맞다.

## 참고

- **Pro Git** (무료 공개) — 내부 동작 설명이 특히 좋다
- `git help <명령>` — 각 명령의 1차 문서
- `git bisect` · `git log -S` · `git worktree` — 실무에서 가장 값이 큰 셋
- 관련 항목: [디버깅](디버깅.md) · [Linux 개발환경 · 셸](리눅스셸.md) · [Buildroot · Yocto](../BSP/Buildroot와Yocto.md)
