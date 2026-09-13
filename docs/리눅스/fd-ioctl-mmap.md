# 파일 디스크립터 · `ioctl` · `mmap`

> 리눅스에서 장치를 다루는 세 가지 도구.
> 「열고 → 설정하고 → 메모리를 공유한다」가 영상 캡처의 전부다.

## 왜 필요한가

카메라 · 인코더 · 네트워크 소켓이 전부 파일 디스크립터로 표현된다.
**`/dev/video0` 을 여는 것과 파일을 여는 것이 같은 함수**라는 점이
리눅스 프로그래밍의 출발점이다.

그리고 고해상도 영상에서 `mmap` 은 선택이 아니다.
프레임마다 3MB 를 복사하면 30fps 에 초당 90MB 를 옮기는 것이고,
그 비용이 CPU 를 먹는다.

## 최소 이해 수준

- **파일 디스크립터는 작은 정수다.** 프로세스마다 표가 있고
  fd 는 그 표의 색인이다. `0`·`1`·`2` 가 표준 입력·출력·오류다.
- **모든 것이 파일이다.** 정규 파일 · 디렉터리 · 소켓 · 파이프 · 장치 ·
  `epoll` 인스턴스 · `timerfd` · `eventfd` 가 모두 fd 다.
  **그래서 하나의 대기 함수로 전부 기다릴 수 있다.** → [비동기 I/O](비동기IO.md)
- **fd 는 유한하다.** 프로세스당 상한이 있고, 닫지 않으면 고갈된다.
  ```bash
  ulimit -n
  ```
  카메라 채널이 많은 관제 프로그램에서 실제로 부딪치는 한계다.
- **`ioctl` 은 「그 밖의 모든 것」이다.** `read`/`write` 로 표현되지 않는 장치 제어를
  담당한다. 형태는 하나다.
  ```c
  int ioctl(int fd, unsigned long request, void *arg);
  ```
  `request` 가 무엇을 할지 정하고, `arg` 로 구조체를 주고받는다.
- **`ioctl` 번호에 방향이 인코딩돼 있다.** `_IOR`·`_IOW`·`_IOWR` 로 정의되고,
  **구조체 크기까지 번호에 들어간다.** 그래서 헤더 버전이 다르면 `EINVAL` 이 난다.
- **`mmap` 은 파일이나 장치 메모리를 주소 공간에 붙인다.**
  ```c
  void *p = mmap(NULL, len, PROT_READ|PROT_WRITE, MAP_SHARED, fd, offset);
  ```
  이후 `p[i]` 로 읽으면 **시스템 콜 없이** 접근한다.
  → [커널 공간 vs 유저 공간](커널과유저공간.md)
- **`MAP_SHARED` 와 `MAP_PRIVATE`.** 공유는 변경이 원본에 반영되고,
  사설은 복사본을 만든다(CoW). **장치 메모리는 항상 `MAP_SHARED`** 다.
- **오류 처리 관례.** 시스템 콜은 `-1` 을 돌리고 `errno` 를 설정한다.
  `EINTR` 은 시그널에 끼인 것이므로 **재시도해야 한다** — 실패가 아니다.
  ```c
  do { n = read(fd, buf, len); } while (n < 0 && errno == EINTR);
  ```
- **`O_NONBLOCK`.** 논블로킹으로 열면 데이터가 없을 때 `EAGAIN` 을 돌린다.
  이벤트 루프 구조에서 필수다.
- **`O_CLOEXEC` 를 쓴다.** `fork`+`exec` 할 때 fd 가 자식에게 새는 것을 막는다.
  카메라 fd 가 자식 프로세스로 새면 **장치를 닫을 수 없게 된다.**

## 직접 해보기

### 1. 프로세스가 무엇을 열고 있는지 보기

```bash
ls -l /proc/<PID>/fd/ | head -20
lsof -p <PID> 2>/dev/null | head
```

숫자가 계속 늘어나면 **fd 누수**다.

```bash
watch -n1 'ls /proc/<PID>/fd | wc -l'
```

### 2. 장치를 열고 정보를 물어보기

```c
#include <fcntl.h>
#include <sys/ioctl.h>
#include <linux/videodev2.h>
#include <stdio.h>
#include <unistd.h>

int main(void) {
    int fd = open("/dev/video0", O_RDWR | O_CLOEXEC);
    if (fd < 0) { perror("open"); return 1; }

    struct v4l2_capability cap = {0};
    if (ioctl(fd, VIDIOC_QUERYCAP, &cap) < 0) { perror("QUERYCAP"); return 1; }
    printf("드라이버=%s 카드=%s 기능=0x%08x\n", cap.driver, cap.card, cap.capabilities);

    close(fd);
}
```

```bash
gcc q.c -o q && ./q
```

**`perror` 를 꼭 쓴다.** `errno` 없이 「실패했다」만 알면 원인을 못 찾는다.

### 3. `mmap` 으로 프레임 버퍼 받기 (V4L2 흐름)

```c
/* ① 포맷 설정 */
struct v4l2_format f = { .type = V4L2_BUF_TYPE_VIDEO_CAPTURE };
f.fmt.pix.width = 1280; f.fmt.pix.height = 720;
f.fmt.pix.pixelformat = V4L2_PIX_FMT_NV12;
ioctl(fd, VIDIOC_S_FMT, &f);

/* ② 버퍼 요청 */
struct v4l2_requestbuffers r = { .count = 4,
    .type = V4L2_BUF_TYPE_VIDEO_CAPTURE, .memory = V4L2_MEMORY_MMAP };
ioctl(fd, VIDIOC_REQBUFS, &r);

/* ③ 각 버퍼를 주소 공간에 붙인다 */
void *addr[4]; size_t len[4];
for (unsigned i = 0; i < r.count; i++) {
    struct v4l2_buffer b = { .type = r.type, .memory = r.memory, .index = i };
    ioctl(fd, VIDIOC_QUERYBUF, &b);
    len[i]  = b.length;
    addr[i] = mmap(NULL, b.length, PROT_READ|PROT_WRITE, MAP_SHARED, fd, b.m.offset);
    ioctl(fd, VIDIOC_QBUF, &b);          /* 큐에 넣는다 */
}

/* ④ 스트리밍 시작 */
int type = r.type;
ioctl(fd, VIDIOC_STREAMON, &type);

/* ⑤ 프레임 꺼내기 — 복사 없다 */
struct v4l2_buffer b = { .type = r.type, .memory = r.memory };
ioctl(fd, VIDIOC_DQBUF, &b);
/* addr[b.index] 가 프레임 데이터. b.bytesused 만큼 유효하다 */
ioctl(fd, VIDIOC_QBUF, &b);              /* 다시 돌려준다 */
```

⚠ **꺼낸 버퍼를 다시 큐에 넣지 않으면** 몇 프레임 뒤에 큐가 비어 멈춘다.
「처음 4프레임만 나오고 멈춘다」의 전형적인 원인이다.

→ [V4L2](../영상/V4L2.md)

### 4. 복사 있는 경로와 없는 경로 비교

```bash
time v4l2-ctl -d /dev/video0 --stream-user --stream-count=300 >/dev/null
time v4l2-ctl -d /dev/video0 --stream-mmap --stream-count=300 >/dev/null
```

`--stream-user` 쪽의 `sys` 시간이 크게 나온다.

### 5. `ioctl` 호출을 추적해 실패 지점 찾기

```bash
strace -e trace=ioctl -s 200 ./q 2>&1 | tail -20
```

어느 `ioctl` 이 `-1 EINVAL` 을 냈는지 바로 보인다.
**헤더와 커널 버전이 맞지 않으면 여기서 잡힌다.**

### 6. fd 상태 확인

```bash
cat /proc/<PID>/fdinfo/3        # pos, flags
```

`flags` 의 `O_NONBLOCK`(`04000`) 여부를 확인할 수 있다.

### 7. 파일을 `mmap` 해서 다뤄 보기

장치가 없어도 원리를 볼 수 있다.

```c
#include <sys/mman.h>
#include <fcntl.h>
#include <unistd.h>
#include <stdio.h>
int main(void) {
    int fd = open("/tmp/t.bin", O_RDWR | O_CREAT, 0644);
    ftruncate(fd, 4096);
    char *p = mmap(NULL, 4096, PROT_READ|PROT_WRITE, MAP_SHARED, fd, 0);
    p[0] = 'A';                  /* write() 없이 파일이 바뀐다 */
    msync(p, 4096, MS_SYNC);     /* 디스크로 내린다 */
    munmap(p, 4096); close(fd);
}
```

```bash
gcc m.c -o m && ./m && head -c1 /tmp/t.bin; echo
```

## 더 들어가면

- **DMABUF.** 버퍼를 fd 로 표현해 **장치 사이에 그대로 넘긴다.**
  캡처 장치에서 받은 버퍼를 인코더에 주면 복사가 완전히 사라진다.
  임베디드 영상 파이프라인에서 가장 중요한 최적화다.
  → [하드웨어 인코더](../압축/하드웨어인코더.md)
- **`dup` · `dup2`.** fd 를 복제한다. 같은 파일을 가리키고 오프셋을 공유한다.
  파이프라인 구성(`exec` 전에 표준 출력 바꾸기)에 쓴다.
- **`fcntl`.** fd 의 속성을 바꾼다. `O_NONBLOCK` 추가, 레코드 잠금(`F_SETLK`).
  **`flock` 은 파일 단위, `fcntl` 잠금은 구간 단위**다.
- **`splice` · `sendfile`.** 커널 안에서 fd 사이로 데이터를 옮긴다.
  유저 공간을 거치지 않아 파일 전송이 빠르다.
- **캐시 일관성.** 장치가 DMA 로 쓴 버퍼를 CPU 가 읽을 때
  캐시를 무효화해야 한다. V4L2 는 드라이버가 처리하지만,
  직접 매핑한 장치 메모리는 `volatile` 이나 배리어가 필요할 수 있다.
- **`/dev/mem`.** 물리 메모리를 직접 매핑한다. 레지스터를 눈으로 볼 때 쓴다.
  **매우 위험하고 최근 커널은 제한한다.**

## 흔한 오해

### 「`read()` 로 프레임을 받으면 된다」

되지만 커널→유저 복사가 프레임마다 일어난다.
1080p NV12 는 프레임당 3MB 이고, 30fps 면 **초당 90MB 복사**다.
저해상도 시험에서는 차이가 안 보이다가 해상도를 올리면 드러난다.

### 「`mmap` 하면 무조건 빠르다」

작은 데이터를 자주 읽으면 페이지 폴트와 TLB 비용이 `read` 보다 클 수 있다.
**큰 버퍼를 반복해서 접근할 때** 이득이 있다.

### 「`ioctl` 이 실패하면 장치가 지원하지 않는 것이다」

`EINVAL` 은 인자가 틀렸을 때도 나온다. 구조체를 `{0}` 으로 초기화하지 않으면
쓰레기 값이 들어가 실패한다. **구조체를 반드시 0 으로 채우고** 필요한 필드만 채운다.

### 「`close` 는 오류를 확인할 필요 없다」

`close` 가 실패할 수 있고(`EIO`), 그때 데이터가 유실된다.
그리고 **실패했다고 다시 `close` 하면 안 된다** — fd 는 이미 해제됐고
다른 스레드가 그 번호를 재사용했을 수 있다.

### 「fd 는 스레드마다 따로다」

프로세스 전체가 공유한다. 한 스레드가 닫으면 다른 스레드가 쓰던 fd 가 사라진다.
**닫는 시점을 한 곳에서 관리**해야 한다. → [멀티스레드](멀티스레드.md)

### 「`EAGAIN` 은 오류다」

논블로킹에서 「지금은 데이터가 없다」는 정상 응답이다.
오류로 처리하면 이벤트 루프가 그때마다 연결을 끊는다.

## 참고

- **`man 2 ioctl`** · **`man 2 mmap`** · **`man 2 open`** — 1차 출처
- **`Documentation/userspace-api/ioctl/ioctl-number.rst`** — `ioctl` 번호 규약
- **`Documentation/driver-api/dma-buf.rst`** — DMABUF
- 관련 항목: [V4L2](../영상/V4L2.md) · [비동기 I/O](비동기IO.md) · [커널과 유저 공간](커널과유저공간.md)
