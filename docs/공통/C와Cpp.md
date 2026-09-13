# C / C++

> 임베디드 영상 시스템의 기본 언어.
> 하드웨어에 직접 닿는 부분은 C, 규모가 있는 응용은 C++ 가 많다.

## 왜 필요한가

커널 · 드라이버 · V4L2 응용 · RTSP 서버가 전부 C 나 C++ 다.
그리고 메모리를 직접 다루기 때문에 **실수의 대가가 크다** —
다른 언어에서는 예외가 나는 상황이 여기서는 조용히 잘못된 값을 만든다.

프레임 버퍼를 다룰 때 포인터와 크기를 정확히 이해하는 것이
곧 「화면이 왜 기울어졌는가」를 푸는 능력이 된다.

## 최소 이해 수준

- **메모리를 스스로 관리한다.** 할당한 것은 해제해야 하고,
  해제한 것을 다시 쓰면 안 되고, 두 번 해제해도 안 된다.
- **배열과 포인터.** 배열 이름은 첫 원소의 주소로 변환된다.
  함수에 배열을 넘기면 **크기 정보가 사라진다.**
  ```c
  void f(uint8_t buf[]) { sizeof(buf); }   /* 포인터 크기다. 배열 크기가 아니다 */
  void g(uint8_t *buf, size_t len);        /* 크기를 함께 넘겨야 한다 */
  ```
- **프레임 버퍼 계산.** 영상 코드에서 가장 자주 틀리는 부분이다.
  ```c
  /* NV12: Y 평면 + UV 평면 */
  size_t y_size  = (size_t)stride * height;         /* width 가 아니라 stride */
  size_t uv_size = y_size / 2;
  uint8_t *y  = buf;
  uint8_t *uv = buf + y_size;

  /* (x, y) 픽셀의 휘도 */
  uint8_t luma = y[(size_t)row * stride + col];
  ```
  **`width` 와 `stride` 를 혼동하면 화면이 비스듬히 기운다.**
  → [색공간](../영상/색공간.md)
- **정수 오버플로와 형 변환.** 곱셈은 승격 전에 일어난다.
  ```c
  int w = 4096, h = 2160;
  int wrong  = w * h * 3 / 2;                  /* int 범위를 넘을 수 있다 */
  size_t ok  = (size_t)w * h * 3 / 2;          /* 먼저 넓힌다 */
  ```
- **부호 있는/없는 비교.** `int` 와 `size_t` 를 비교하면 `int` 가 변환돼
  음수가 거대한 값이 된다. **경고를 켜면 잡힌다** (`-Wsign-compare`).
- **`const` 와 고정 폭 타입.** `uint8_t` · `uint32_t` · `size_t` · `ssize_t`.
  **`int` 가 32비트라고 가정하지 않는다.**
  ```c
  #include <stdint.h>
  #include <stddef.h>
  ```
- **구조체 초기화.** 시스템 콜에 넘기는 구조체는 반드시 0 으로 채운다.
  ```c
  struct v4l2_buffer b = {0};       /* 이것을 빠뜨리면 EINVAL */
  ```
- **문자열은 널로 끝난다.** 버퍼 크기와 문자열 길이는 다르다.
  `strcpy` 대신 `snprintf` 를 쓴다.
  ```c
  snprintf(path, sizeof path, "/dev/video%d", n);   /* 항상 널 종료 */
  ```
- **C 와 C++ 의 차이 (핵심만).**

  | | C | C++ |
  |---|---|---|
  | 자원 관리 | 손으로 | RAII (소멸자) |
  | 오류 처리 | 반환값 + errno | 예외 또는 반환값 |
  | 추상화 | 함수 포인터 | 클래스 · 템플릿 |
  | 커널 | 쓴다 | 안 쓴다 |

  **커널과 드라이버는 C 다.** C++ 은 응용 쪽이다.
  → [Modern C++](../관제/ModernCpp.md)
- **C 코드를 C++ 에서 부를 때.**
  ```cpp
  extern "C" {
  #include "camera.h"
  }
  ```

## 직접 해보기

### 1. 경고를 전부 켜고 빌드

가장 값싸게 버그를 잡는 방법이다.

```bash
gcc -std=c11 -Wall -Wextra -Wpedantic -Wshadow -Wconversion \
    -Wstrict-prototypes -Wvla -O2 -g prog.c -o prog
```

**경고가 쌓인 프로젝트에서는 새 경고가 묻힌다.** 0 으로 유지한다.

```bash
gcc ... -Werror      # 경고를 오류로 (CI 에서)
```

### 2. 메모리 오류를 재현하고 잡기

```c
#include <stdlib.h>
#include <string.h>
int main(void) {
    char *p = malloc(10);
    strcpy(p, "12345678901234");   /* 넘침 */
    free(p);
    return p[0];                   /* 해제 후 사용 */
}
```

```bash
gcc -g -fsanitize=address bad.c -o bad && ./bad
```

`heap-buffer-overflow` 와 `heap-use-after-free` 가 정확한 줄과 함께 나온다.
**경고 없이 컴파일되는 코드가 이렇게 잡힌다.**

### 3. `stride` 를 틀리게 해서 증상 보기

```c
/* 일부러 stride 대신 width 를 쓴다 */
for (int r = 0; r < height; r++)
    memcpy(dst + r * width, src + r * width, width);   /* stride != width 면 기운다 */
```

실제 값을 확인하는 것이 먼저다.

```c
struct v4l2_format f = { .type = V4L2_BUF_TYPE_VIDEO_CAPTURE };
ioctl(fd, VIDIOC_G_FMT, &f);
printf("width=%u height=%u bytesperline=%u sizeimage=%u\n",
       f.fmt.pix.width, f.fmt.pix.height,
       f.fmt.pix.bytesperline, f.fmt.pix.sizeimage);
```

**`bytesperline` 이 stride 다.** `width` 와 다른 값이 나오는지 확인한다.
→ [V4L2](../영상/V4L2.md)

### 4. 정수 오버플로 보기

```c
#include <stdio.h>
#include <stdint.h>
int main(void) {
    int w = 4096, h = 2160;
    printf("int:    %d\n", w * h * 3 / 2);
    printf("size_t: %zu\n", (size_t)w * h * 3 / 2);
}
```

```bash
gcc -fsanitize=undefined ov.c -o ov && ./ov
```

`signed integer overflow` 가 보고된다.

### 5. 오류 처리를 빠뜨리지 않게

```c
#define TRY(expr) do { \
    if ((expr) < 0) { \
        fprintf(stderr, "%s:%d %s 실패: %s(%d)\n", \
                __FILE__, __LINE__, #expr, strerror(errno), errno); \
        goto fail; \
    } \
} while (0)

/* 사용 */
TRY(ioctl(fd, VIDIOC_S_FMT, &f));
TRY(ioctl(fd, VIDIOC_REQBUFS, &r));
```

**`errno` 를 이름과 숫자로 함께 남긴다.** → [디버깅](디버깅.md)

### 6. 해제 경로를 한 곳으로 모으기

C 에서 흔한 패턴이다.

```c
int setup(void) {
    int fd = -1; void *buf = NULL; int rc = -1;

    fd = open("/dev/video0", O_RDWR | O_CLOEXEC);
    if (fd < 0) goto out;
    buf = malloc(SIZE);
    if (!buf) goto out;
    /* ... */
    rc = 0;
out:
    free(buf);                 /* NULL 에 free 는 안전하다 */
    if (fd >= 0) close(fd);
    return rc;
}
```

**`goto out` 패턴은 커널 코드의 표준**이다. 중첩된 `if` 보다 누락이 적다.

### 7. 정적 분석 돌리기

```bash
gcc -fanalyzer -c prog.c            # GCC 내장 (13 이상)
clang --analyze prog.c
cppcheck --enable=all --inconclusive prog.c
```

**실행하지 않고 찾아 주는 버그**가 있다. 특히 해제 경로 누락에 강하다.

## 더 들어가면

- **엄격한 앨리어싱(strict aliasing).** 서로 다른 타입의 포인터로 같은 메모리를
  보면 최적화가 깨질 수 있다. 바이트 단위 재해석은 `memcpy` 로 한다.
  ```c
  uint32_t v; memcpy(&v, buf, 4);       /* 안전 */
  uint32_t v = *(uint32_t*)buf;          /* 정렬·앨리어싱 문제 가능 */
  ```
- **정렬(alignment).** 일부 아키텍처는 정렬되지 않은 접근에서 예외가 난다.
  x86 에서 동작하던 코드가 **보드에서 죽는** 전형적인 원인이다.
- **엔디안.** 파일 형식이나 프로토콜을 파싱할 때 명시적으로 변환한다.
  → [소켓 · TCP/UDP](소켓.md)
- **`volatile`.** 하드웨어 레지스터 접근에 쓴다.
  **스레드 동기화 용도가 아니다.** → [멀티스레드](../리눅스/멀티스레드.md)
- **빌드 재현성.** `-ffile-prefix-map=$(PWD)=.` 로 빌드 경로가
  바이너리에 박히는 것을 막는다.
  ```bash
  strings ./prog | grep '^/home/'      # 남아 있으면 제거 대상
  ```
  → [Buildroot · Yocto](../BSP/Buildroot와Yocto.md)
- **C 표준 버전.** `c99` · `c11` · `c17`. 임베디드 툴체인이 지원하는 범위를 확인한다.
- **MISRA 같은 코딩 규약.** 안전 관련 제품에서 요구된다.
  동적 할당 금지 · `goto` 금지 등 제약이 강해 설계가 달라진다.

## 흔한 오해

### 「컴파일되면 맞는 코드다」

C 는 잘못된 것을 대부분 그냥 통과시킨다. **경고를 켜는 것이 사실상의 타입 검사**다.
`-Wall -Wextra` 만으로도 상당수가 잡힌다.

### 「`malloc` 실패는 일어나지 않는다」

임베디드에서는 일어난다. 메모리가 수십 MB 뿐이고,
프레임 버퍼 몇 개면 금방 찬다. **반환값을 확인하지 않으면 널 참조로 죽는다.**

### 「해상도만 알면 버퍼 크기를 안다」

포맷과 stride 를 함께 알아야 한다. `sizeimage` 를 드라이버에서 받아 쓰는 것이
가장 안전하다. 직접 계산하면 **stride 정렬 때문에 틀린다.**

### 「C++ 를 쓰면 C 보다 느리다」

추상화 비용은 대개 0 이다(zero-cost abstraction).
느려지는 것은 **잘못 쓸 때**다 — 불필요한 복사, `shared_ptr` 남용, 가상 호출 남용.

### 「문자열은 `strcpy` 로 충분하다」

대상 크기를 모르므로 넘칠 수 있다. `snprintf` 를 쓴다.
`strncpy` 는 **널 종료를 보장하지 않아** 오히려 위험하다.

### 「해제를 안 해도 프로그램이 끝나면 회수된다」

짧은 도구라면 맞다. 하지만 **하루 종일 도는 데몬에서는 누수가 쌓인다.**
카메라 펌웨어는 몇 달을 재부팅 없이 도는 것이 요구사항이다.

```bash
# 장시간 메모리 증가 확인
while :; do grep VmRSS /proc/<PID>/status; sleep 60; done
```

## 참고

- **`man 3 <함수명>`** — 표준 라이브러리 1차 참조
- **cppreference.com** — C 와 C++ 둘 다 정확하다
- **CERT C Coding Standard** — 흔한 취약 패턴 목록
- 관련 항목: [Modern C++](../관제/ModernCpp.md) · [디버깅](디버깅.md) · [자료구조 · 알고리즘](자료구조와알고리즘.md)
