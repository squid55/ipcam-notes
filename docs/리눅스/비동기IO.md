# 비동기 I/O (`select` · `poll` · `epoll`)

> 여러 파일 디스크립터를 한 스레드에서 기다리는 방법.
> 「누군가 준비되면 알려 달라」를 커널에 부탁한다.

## 왜 필요한가

카메라 한 대에 접속한 시청자가 여러 명이면 연결이 여러 개다.
연결마다 스레드를 만들면 **동시 접속 수가 곧 스레드 수**가 되고,
메모리와 문맥 전환이 한계에 닿는다.

그리고 영상 스트리밍은 대기 시간이 대부분이다.
CPU 를 쓰는 시간보다 **「다음 프레임이 오기를 기다리는 시간」**이 훨씬 길다.
그 대기를 한 곳에 모으는 것이 이벤트 루프다.

## 최소 이해 수준

- **모든 것이 fd 이므로 함께 기다릴 수 있다.**
  소켓 · 카메라 · 타이머(`timerfd`) · 시그널(`signalfd`) · 이벤트(`eventfd`)가
  전부 같은 함수로 대기된다. → [파일 디스크립터 · ioctl · mmap](fd-ioctl-mmap.md)
- **세 가지 비교.**

  | | `select` | `poll` | `epoll` |
  |---|---|---|---|
  | fd 개수 상한 | `FD_SETSIZE`(보통 1024) | 없다 | 없다 |
  | 호출당 비용 | O(n) — 매번 전체 전달 | O(n) | **O(1)** — 커널이 목록을 유지 |
  | 이식성 | POSIX · 어디서나 | POSIX | **리눅스 전용** |
  | 쓰는 곳 | 소수 fd · 이식성 필요 | 중간 | 다수 연결 |

  **연결이 수십 개를 넘으면 `epoll` 이다.**
- **`epoll` 의 기본 흐름.**
  ```c
  int ep = epoll_create1(EPOLL_CLOEXEC);

  struct epoll_event ev = { .events = EPOLLIN, .data.fd = sock };
  epoll_ctl(ep, EPOLL_CTL_ADD, sock, &ev);

  struct epoll_event out[64];
  int n = epoll_wait(ep, out, 64, 1000);        /* 1000ms 타임아웃 */
  for (int i = 0; i < n; i++) {
      if (out[i].events & EPOLLIN)  /* 읽을 수 있다 */ ;
      if (out[i].events & EPOLLOUT) /* 쓸 수 있다 */ ;
      if (out[i].events & (EPOLLHUP | EPOLLERR)) /* 끊겼다 */ ;
  }
  ```
- **레벨 트리거(LT)와 에지 트리거(ET).**
  - **LT** (기본) — 데이터가 남아 있으면 계속 알려준다. **안전하다.**
  - **ET** (`EPOLLET`) — 상태가 바뀔 때 한 번만 알려준다. 빠르지만
    **`EAGAIN` 이 날 때까지 반복해서 다 읽어야** 한다. 안 하면 데이터가 멈춘다.

  **처음에는 LT 를 쓴다.** ET 의 성능 이득은 연결이 매우 많을 때만 유의미하다.
- **논블로킹이 전제다.** `O_NONBLOCK` 없이 이벤트 루프를 만들면
  한 번의 `read` 가 블로킹되어 **모든 연결이 멈춘다.**
- **`EAGAIN` 은 정상이다.** 「지금은 없다」는 뜻이므로 루프로 돌아간다.
  오류로 처리하면 연결을 끊게 된다.
- **부분 쓰기를 처리해야 한다.** `write` 가 요청한 만큼 다 쓰지 못할 수 있다.
  남은 것을 버퍼에 두고 `EPOLLOUT` 을 기다려 이어 쓴다.
  **영상 스트리밍에서 반드시 필요하다** — 느린 시청자가 있으면 바로 발생한다.
- **`SIGPIPE` 를 막는다.** 끊긴 소켓에 쓰면 기본 동작이 프로세스 종료다.
  ```c
  signal(SIGPIPE, SIG_IGN);
  /* 또는 send(fd, buf, len, MSG_NOSIGNAL) */
  ```
  **이것을 빠뜨리면 시청자가 창을 닫을 때 서버가 죽는다.**
- **타임아웃을 항상 둔다.** 응답 없는 연결을 정리하지 않으면 fd 가 쌓인다.

## 직접 해보기

### 1. 가장 작은 이벤트 루프

```c
#include <sys/epoll.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <fcntl.h>
#include <unistd.h>
#include <string.h>
#include <stdio.h>
#include <errno.h>
#include <signal.h>

static void nonblock(int fd) { fcntl(fd, F_SETFL, fcntl(fd, F_GETFL) | O_NONBLOCK); }

int main(void) {
    signal(SIGPIPE, SIG_IGN);

    int ls = socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0);
    int on = 1; setsockopt(ls, SOL_SOCKET, SO_REUSEADDR, &on, sizeof on);
    struct sockaddr_in a = { .sin_family = AF_INET, .sin_port = htons(9000),
                             .sin_addr.s_addr = htonl(INADDR_ANY) };
    bind(ls, (struct sockaddr*)&a, sizeof a);
    listen(ls, 64);
    nonblock(ls);

    int ep = epoll_create1(EPOLL_CLOEXEC);
    struct epoll_event ev = { .events = EPOLLIN, .data.fd = ls };
    epoll_ctl(ep, EPOLL_CTL_ADD, ls, &ev);

    struct epoll_event out[64];
    for (;;) {
        int n = epoll_wait(ep, out, 64, 5000);
        if (n == 0) { printf("5초간 조용함\n"); continue; }
        for (int i = 0; i < n; i++) {
            int fd = out[i].data.fd;
            if (fd == ls) {
                int c;
                while ((c = accept(ls, NULL, NULL)) >= 0) {   /* 한 번에 여러 개 */
                    nonblock(c);
                    struct epoll_event e = { .events = EPOLLIN, .data.fd = c };
                    epoll_ctl(ep, EPOLL_CTL_ADD, c, &e);
                    printf("접속 fd=%d\n", c);
                }
            } else if (out[i].events & (EPOLLHUP | EPOLLERR)) {
                epoll_ctl(ep, EPOLL_CTL_DEL, fd, NULL); close(fd);
                printf("종료 fd=%d\n", fd);
            } else if (out[i].events & EPOLLIN) {
                char buf[1024];
                ssize_t r = read(fd, buf, sizeof buf);
                if (r > 0)  { write(fd, buf, r); }            /* 되돌려 보낸다 */
                else if (r == 0) { epoll_ctl(ep, EPOLL_CTL_DEL, fd, NULL); close(fd); }
                else if (errno != EAGAIN) { close(fd); }
            }
        }
    }
}
```

```bash
gcc -O2 ev.c -o ev && ./ev &
nc localhost 9000          # 여러 터미널에서 동시에
```

**하나의 스레드가 여러 연결을 처리하는 것**을 직접 확인한다.

### 2. 카메라와 소켓을 함께 기다리기

영상 서버의 핵심 구조다.

```c
epoll_ctl(ep, EPOLL_CTL_ADD, video_fd, &(struct epoll_event){
    .events = EPOLLIN, .data.fd = video_fd });   /* /dev/video0 도 fd 다 */
```

`video_fd` 가 준비되면 `VIDIOC_DQBUF` 로 프레임을 꺼내고,
소켓이 `EPOLLOUT` 이면 밀린 데이터를 이어 쓴다.
→ [V4L2](../영상/V4L2.md)

### 3. 타이머를 fd 로 만들기

`sleep` 을 쓰지 않고 주기 작업을 넣는 방법이다.

```c
#include <sys/timerfd.h>
int tf = timerfd_create(CLOCK_MONOTONIC, TFD_CLOEXEC | TFD_NONBLOCK);
struct itimerspec its = { .it_interval = {1, 0}, .it_value = {1, 0} };  /* 1초 */
timerfd_settime(tf, 0, &its, NULL);
/* epoll 에 추가. 만료되면 EPOLLIN 이 온다 — read() 로 8바이트를 비워야 한다 */
```

⚠ **`read` 로 비우지 않으면 LT 모드에서 계속 깨어난다** — CPU 가 100% 가 된다.

### 4. 시그널도 fd 로

```c
#include <sys/signalfd.h>
sigset_t ss; sigemptyset(&ss); sigaddset(&ss, SIGTERM); sigaddset(&ss, SIGINT);
sigprocmask(SIG_BLOCK, &ss, NULL);                    /* 반드시 막아야 한다 */
int sf = signalfd(-1, &ss, SFD_CLOEXEC | SFD_NONBLOCK);
/* epoll 에 추가 → 종료 신호를 루프 안에서 안전하게 처리 */
```

**시그널 핸들러 안에서 할 수 있는 일이 극히 제한적**이기 때문에
이 방식이 훨씬 안전하다.

### 5. fd 누수 감시

```bash
watch -n1 'ls /proc/$(pgrep -f ./ev)/fd | wc -l'
```

연결을 맺고 끊으며 숫자가 제자리로 돌아오는지 본다.
**`epoll_ctl(DEL)` 만 하고 `close` 를 빠뜨리면** 여기서 드러난다.

### 6. 무엇을 기다리는지 확인

```bash
strace -p <PID> -e trace=epoll_wait,read,write -T 2>&1 | head -20
cat /proc/<PID>/wchan; echo
```

`epoll_wait` 에서 대기 중이면 정상, 다른 곳에서 멈춰 있으면
**블로킹 호출이 루프 안에 들어간 것**이다.

### 7. 부하를 걸어 보기

```bash
# 동시 연결 100개
for i in $(seq 1 100); do (nc localhost 9000 &) ; done
ls /proc/$(pgrep -f ./ev)/fd | wc -l
```

`ulimit -n` 에 닿으면 `accept` 가 `EMFILE` 로 실패한다.
**그때 루프가 멈추지 않고 계속 도는지** 확인해야 한다 —
실패를 무시하면 CPU 를 태우는 무한 루프가 된다.

## 더 들어가면

- **`io_uring`.** 요청과 완료를 링 버퍼로 주고받아 시스템 콜 횟수를 줄인다.
  `epoll` 보다 빠르지만 커널 버전 요구가 있고 API 가 복잡하다.
- **`EPOLLEXCLUSIVE`.** 여러 스레드가 같은 리스닝 소켓을 기다릴 때
  하나만 깨우게 한다. 천둥 소리(thundering herd) 문제를 줄인다.
- **스레드당 이벤트 루프.** 코어 수만큼 루프를 두고 연결을 나눠 맡긴다.
  `SO_REUSEPORT` 로 커널이 분배하게 할 수 있다.
- **백프레셔.** 느린 시청자에게 맞춰 인코더를 늦출지, 프레임을 버릴지.
  영상에서는 **버리는 것이 정답**인 경우가 많다.
  → [멀티스레드](멀티스레드.md) 의 큐 정책
- **`EPOLLRDHUP`.** 상대가 쓰기를 닫은 것을 감지한다.
  `EPOLLIN` + `read == 0` 으로도 알 수 있지만 이 플래그가 더 명확하다.
- **라이브러리.** `libuv` · `libevent` · Boost.Asio.
  플랫폼 차이와 잔가지 처리를 대신해 준다.
  직접 쓰는 것은 **원리를 이해하기 위한 연습**으로 가치가 있다.

## 흔한 오해

### 「연결마다 스레드가 가장 단순하다」

수십 개까지는 그렇다. 하지만 스레드마다 스택이 필요하고,
임베디드에서는 **동시 접속 10명에서 이미 메모리가 부담**이 된다.
그리고 공유 상태가 생기면 잠금 문제가 따라온다.

### 「`epoll` 이 알려줬으니 데이터가 있다」

`EPOLLIN` 이 왔는데 `read` 가 `0` 을 돌리면 **연결이 닫힌 것**이다.
`EAGAIN` 이 나올 수도 있다(가짜 깨어남). 항상 반환값을 확인한다.

### 「에지 트리거가 빠르니 써야 한다」

ET 로 바꾸면 **한 번에 다 읽지 않으면 데이터가 멈춘다.**
그 버그는 부하가 높을 때만 나타나 찾기 어렵다.
연결이 수천 개가 아니라면 LT 로 충분하다.

### 「`write` 는 요청한 만큼 쓴다」

소켓 버퍼가 차면 일부만 쓰거나 `EAGAIN` 을 돌린다.
반환값을 확인하지 않는 코드는 **느린 네트워크에서 영상이 깨진다.**

### 「블로킹 호출 하나쯤은 괜찮다」

이벤트 루프 안의 블로킹 호출 하나가 **모든 연결을 멈춘다.**
파일 읽기 · DNS 조회 · 데이터베이스 질의가 흔한 범인이다.
이런 일은 별도 스레드로 옮긴다.

### 「fd 를 닫으면 `epoll` 에서 자동으로 빠진다」

대개 그렇지만 **`close` 전에 `EPOLL_CTL_DEL` 을 하는 것**이 안전하다.
fd 번호가 곧바로 재사용되면 옛 등록이 새 fd 에 적용되는 혼란이 생긴다.

## 참고

- **`man 7 epoll`** — 특히 「Level-triggered and edge-triggered」 절
- **`man 2 timerfd_create`** · **`man 2 signalfd`**
- **The C10K problem** — 이 문제의 역사적 배경
- 관련 항목: [파일 디스크립터 · ioctl · mmap](fd-ioctl-mmap.md) · [멀티스레드](멀티스레드.md) · [소켓 · TCP/UDP](../공통/소켓.md)
