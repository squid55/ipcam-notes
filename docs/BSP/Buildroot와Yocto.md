# Buildroot · Yocto

> 부트로더 · 커널 · 루트 파일시스템을 한 번에 만들어 주는 빌드 시스템.
> Buildroot 는 단순하고 빠르고, Yocto 는 크고 유연하다.

## 왜 필요한가

임베디드 리눅스 이미지를 손으로 조립하면 재현되지 않는다.
누가 어떤 버전을 어떤 옵션으로 빌드했는지 아무도 모르게 되고,
**몇 달 뒤 같은 이미지를 다시 만들 수 없다.**

그것은 곧 「이 펌웨어가 이 소스에서 나왔음을 보일 수 없다」는 뜻이기도 하다.
인증·감사가 필요한 제품에서는 이 자체가 요구사항이 된다.
→ [무결성과 서명 업데이트](../보안/무결성과서명업데이트.md)

## 최소 이해 수준

- **둘 다 크로스 툴체인부터 만든다.** 컴파일러 · libc · 모든 패키지를
  대상 아키텍처로 빌드한다. 첫 빌드가 오래 걸리는 이유다.
  → [크로스 컴파일](크로스컴파일.md)
- **산출물은 같은 종류다.** 부트로더 이미지 · 커널 이미지 · 디바이스트리 ·
  루트 파일시스템 이미지(`.ubifs` · `.squashfs` · `.tar`).

### Buildroot

- **커널과 같은 방식이다.** `make menuconfig` 로 설정하고 `.config` 에 저장한다.
  커널 설정을 아는 사람이면 바로 시작할 수 있다.
- **패키지 하나가 `.mk` + `Config.in` 두 파일이다.**
  ```makefile
  MYAPP_VERSION = 1.2.0
  MYAPP_SITE = https://example.com/src
  MYAPP_LICENSE = GPL-2.0+
  MYAPP_DEPENDENCIES = openssl

  define MYAPP_BUILD_CMDS
      $(MAKE) CC="$(TARGET_CC)" -C $(@D)
  endef

  define MYAPP_INSTALL_TARGET_CMDS
      $(INSTALL) -D -m 0755 $(@D)/myapp $(TARGET_DIR)/usr/bin/myapp
  endef

  $(eval $(generic-package))
  ```
- **증분 빌드를 신뢰하지 않는다.** 설정을 바꾸면 전체 재빌드가 원칙이다.
  이것이 단점이지만, **재현성이 좋은 이유**이기도 하다.
- **`br2-external`** 로 제품 고유 패키지와 설정을 트리 밖에 둔다.
  Buildroot 본체를 고치지 않는 것이 유지보수의 핵심이다.

### Yocto (OpenEmbedded)

- **레시피(`.bb`)로 기술한다.** BitBake 가 의존 관계를 풀어 태스크를 실행한다.
  ```
  SUMMARY = "My app"
  LICENSE = "GPL-2.0-or-later"
  SRC_URI = "git://example.com/myapp.git;branch=main"
  SRCREV = "abc1234..."
  DEPENDS = "openssl"
  inherit cmake
  ```
- **레이어로 쌓는다.** `meta-`(코어) · `meta-poky` · 벤더 BSP 레이어 ·
  제품 레이어. **벤더가 BSP 를 Yocto 레이어로 주는 경우가 많다.**
- **태스크 단위 캐시(sstate).** 바꾼 것만 다시 빌드한다.
  두 번째 빌드부터는 훨씬 빠르다.
- **패키지 관리가 들어 있다.** `rpm`·`deb`·`ipk` 를 만들어
  기기에서 개별 업데이트가 가능하다.
- **배우는 비용이 크다.** 변수 오버라이드 · 클래스 상속 · 태스크 순서가 많아
  익숙해질 때까지 시간이 든다.

### 고르는 기준

| | Buildroot | Yocto |
|---|---|---|
| 학습 시간 | 며칠 | 몇 주 |
| 첫 빌드 | 30분~2시간 | 2~8시간 |
| 재빌드 | 대개 전체 | 태스크 캐시로 빠르다 |
| 디스크 | 수 GB | 수십~100GB |
| 이미지 최소 크기 | 작다 (수 MB) | 조금 크다 |
| 패키지 관리자 | 기본 없음 | 있다 |
| 여러 제품 파생 | 어렵다 | 레이어로 쉽다 |
| 벤더 BSP | 드물다 | 흔하다 |

**단일 제품 · 작은 플래시 · 적은 인원이면 Buildroot,
제품군이 여럿이고 벤더가 레이어를 주면 Yocto** 가 대체로 맞다.

## 직접 해보기

### 1. Buildroot 로 QEMU 이미지 만들어 보기

실제 보드 없이 전 과정을 볼 수 있다.

```bash
git clone --depth 1 https://gitlab.com/buildroot.org/buildroot.git
cd buildroot
make list-defconfigs | grep -i qemu
make qemu_riscv64_virt_defconfig
make -j$(nproc)              # 시간이 걸린다
```

```bash
ls -l output/images/
cat board/qemu/*/readme.txt  # 실행 명령이 적혀 있다
```

### 2. 무엇이 들어갔는지 확인

```bash
# 파일 목록과 크기
du -sh output/target
find output/target -type f -size +200k | xargs ls -lS | head

# 라이선스와 의존성 보고서
make legal-info
ls output/legal-info/
```

`legal-info` 가 **라이선스 의무를 정리해 준다.**
제품을 출하할 때 이 산출물이 필요하다.

### 3. 설정을 저장하고 되살리기

```bash
make savedefconfig            # 최소 설정을 defconfig 로
cp defconfig ../myproduct_defconfig
```

⚠ `.config` 전체가 아니라 **`defconfig`(기본값과 다른 항목만)를 형상관리**한다.
`.config` 는 버전마다 바뀌는 항목이 많아 비교가 어렵다.

### 4. 패키지 하나 추가해 보기

```bash
mkdir -p package/myapp
# package/myapp/Config.in 과 myapp.mk 작성
# package/Config.in 에 source "package/myapp/Config.in" 한 줄 추가
make menuconfig               # Target packages 에서 켠다
make myapp-rebuild
ls output/target/usr/bin/myapp
```

### 5. Yocto 로 같은 것을 해 보기

```bash
git clone -b scarthgap git://git.yoctoproject.org/poky
cd poky && source oe-init-build-env
# conf/local.conf 에서 MACHINE 설정
bitbake core-image-minimal
ls tmp/deploy/images/*/
```

의존 관계와 레이어 확인:

```bash
bitbake-layers show-layers
bitbake -g core-image-minimal && head task-depends.dot
bitbake -e busybox | grep '^SRC_URI='    # 최종 변수값 확인
```

**`bitbake -e` 가 Yocto 디버깅의 핵심 도구다.**
변수가 여러 곳에서 덮어써지므로 최종값을 직접 봐야 한다.

### 6. 재현성 확인

같은 소스에서 두 번 빌드해 결과를 비교한다.

```bash
md5sum output/images/rootfs.ubifs
# 다시 빌드 후
md5sum output/images/rootfs.ubifs
```

⚠ **값이 달라도 내용이 같을 수 있다.** 파일시스템 이미지는
타임스탬프·압축·노드 배치 때문에 바이트가 흔들린다.
파일 단위로 대조해야 실제 차이를 안다.
→ [플래시 · 파일시스템](플래시와파일시스템.md)

바이트 단위 재현이 필요하면:

```bash
export SOURCE_DATE_EPOCH=1700000000
# 압축 옵션 고정, 빌드 경로 의존성 제거(-ffile-prefix-map)
```

### 7. 빌드 경로가 바이너리에 박히는지 확인

```bash
grep -rc '/home/[a-z]*/' output/target/usr/bin/* 2>/dev/null | grep -v ':0'
strings output/target/usr/sbin/<프로그램> | grep '^/home/'
```

개발자의 홈 디렉터리 경로가 남아 있으면 **재현성도 깨지고 정보도 노출된다.**
`-ffile-prefix-map=$(PWD)=.` 으로 없앤다.

## 더 들어가면

- **BSP 통합.** 벤더가 준 커널·부트로더 소스를 레시피/패키지로 감싸
  빌드 시스템 안으로 끌어들인다. 이것을 하지 않으면 이미지 일부가
  **「어디서 왔는지 모르는 바이너리」**로 남는다.
- **SBOM 생성.** Yocto 는 SPDX 를, Buildroot 는 `legal-info` 를 낸다.
  CycloneDX 로 변환하는 도구도 있다. 취약점 대응의 출발점이다.
- **CVE 점검.** Yocto 는 `cve-check` 클래스가 있고, Buildroot 는
  `make pkg-stats` 가 알려진 CVE 를 표로 만들어 준다.
  **출하 전에 한 번은 돌려야 한다.**
- **overlayfs 구성.** 읽기 전용 루트 위에 쓰기 가능한 층을 얹어
  설정 변경을 별도 볼륨에 담는다. 공장 초기화가 간단해진다.
- **이미지 최소화.** `BR2_ENABLE_DEBUG` 끄기 · `strip` · locale 제거 ·
  불필요한 BusyBox 애플릿 끄기. 수 MB 단위로 줄어든다.
- **CI 에서 빌드.** 빌드를 사람 노트북에서만 하면 결국 재현되지 않는다.
  캐시(sstate / ccache)를 공유하면 CI 에서도 현실적인 시간이 나온다.

## 흔한 오해

### 「빌드 시스템은 초기 설정만 하면 된다」

커널 버전 올리기 · CVE 대응 · 패키지 교체가 계속 온다.
**빌드 시스템 자체가 유지보수 대상**이고, 그것을 고려해 구조를 잡아야 한다.
본체를 직접 고쳐 두면 업그레이드가 불가능해진다.

### 「Yocto 가 항상 더 낫다」

벤더 BSP 가 Yocto 레이어로 온다면 그렇다. 그렇지 않은데
제품이 하나뿐이라면 Buildroot 의 단순함이 실질적인 이득이다.
**팀이 유지할 수 있는 것을 고르는 것**이 기준이다.

### 「`make` 만 다시 돌리면 반영된다」

Buildroot 는 설정 변경을 증분으로 처리하지 않는다.
패키지를 뺐는데 이미지에 그대로 남아 있는 일이 흔하다.
확실히 하려면 `output/` 을 비우고 다시 빌드한다.

```bash
make clean        # output/ 대부분 제거 (다운로드 캐시는 유지)
```

### 「이미지가 작으니 안전하다」

크기와 보안은 별개다. 다만 **불필요한 도구를 넣지 않는 것**은
공격 표면을 줄이는 실제 조치다. `telnetd` · 컴파일러 · 디버그 셸이
출하 이미지에 들어 있는지 확인한다.

### 「이미지 해시가 재현되면 재현 가능한 빌드다」

바이트 재현은 강한 조건이고, 파일시스템 이미지에서는 대개 성립하지 않는다.
현실적인 기준은 **「모든 파일을 소스에서 다시 만들 수 있고 파일별 해시가 일치한다」**다.
그 선을 명시해 두면 불필요한 추적을 피할 수 있다.

## 참고

- **Buildroot Manual** — `make manual` 로 로컬 생성도 된다
- **Yocto Project Reference Manual · Mega-Manual**
- **`bitbake -e`** · **`make pkg-stats`** — 디버깅과 CVE 점검의 실무 도구
- 관련 항목: [크로스 컴파일](크로스컴파일.md) · [커널 구조](커널구조.md) · [플래시 · 파일시스템](플래시와파일시스템.md)
