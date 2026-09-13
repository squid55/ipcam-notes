# 객체지향(OOP) 설계

> 데이터와 그것을 다루는 코드를 묶고, 바뀔 만한 곳에 경계를 두는 방식.
> 목적은 「나중에 고치기 쉽게」이지 「클래스를 많이 만들기」가 아니다.

## 왜 필요한가

카메라 펌웨어에는 반드시 갈아치우는 부분이 있다 —
센서가 바뀌고, 인코더가 바뀌고, SoC 가 바뀐다.
**그 자리에 경계를 두지 않으면 전체를 다시 쓴다.**

실제 사례로, 프로토타입을 다른 보드에서 시작해 나중에 실제 SoC 로 옮기는 일이 흔하다.
그때 무엇을 추상화해 두었는지가 이식 비용을 결정한다.

## 최소 이해 수준

- **네 가지 개념.**
  - **캡슐화** — 내부 상태를 감추고 정해진 함수로만 만지게 한다
  - **추상화** — 「무엇을 하는가」만 드러내고 「어떻게」는 숨긴다
  - **상속** — 공통을 위로 뽑는다. **남용하기 쉬운 도구다**
  - **다형성** — 같은 호출이 대상에 따라 다르게 동작한다
- **경계는 「바뀔 곳」에 둔다.** 무엇이 바뀔지 모르면 추상화하지 않는다.
  ```
  바뀔 가능성이 높다:  센서 · 코덱 · 저장 방식 · 암호 구현 · 전송 프로토콜
  거의 안 바뀐다:      로그 형식 · 내부 유틸리티
  ```
  **추상화가 이르면 잘못된 경계가 굳는다.** 두 번째 구현이 나올 때 뽑는 편이 낫다.
- **SOLID 중 실제로 쓰는 둘.**
  - **단일 책임** — 한 클래스가 한 가지 이유로만 바뀌게
  - **의존 역전** — 상위 모듈이 하위 구현이 아니라 **인터페이스에 의존**하게

  나머지도 쓸모가 있지만, 이 둘만 지켜도 대부분의 이득이 나온다.
- **합성이 상속보다 낫다.** 상속은 부모의 모든 것을 물려받아 결합이 강하다.
  ```cpp
  /* 나쁨: RTSP 서버가 인코더를 상속 */
  class RtspServer : public H264Encoder { ... };

  /* 좋음: 인코더를 가진다 */
  class RtspServer {
      std::unique_ptr<IEncoder> enc_;
  };
  ```
- **인터페이스는 좁게.** 함수 20개짜리 인터페이스는 구현하기 어렵고
  가짜 구현(시험용)을 만들기도 어렵다.
- **C 에서도 할 수 있다.** 함수 포인터 구조체가 커널의 방식이다.
  ```c
  struct encoder_ops {
      int  (*open)(void *ctx, const struct enc_cfg *cfg);
      int  (*encode)(void *ctx, const struct frame *in, struct packet *out);
      void (*close)(void *ctx);
  };

  struct encoder {
      const struct encoder_ops *ops;
      void *ctx;
  };

  /* 호출하는 쪽은 구현을 모른다 */
  enc->ops->encode(enc->ctx, &frame, &pkt);
  ```
  **`file_operations` · `v4l2_subdev_ops` 가 정확히 이 형태다.**
  → [디바이스 드라이버](../BSP/디바이스드라이버.md)
- **C++ 라면 순수 가상 클래스.**
  ```cpp
  class IEncoder {
  public:
      virtual ~IEncoder() = default;                     /* 반드시 virtual */
      virtual bool open(const EncConfig&) = 0;
      virtual bool encode(const Frame&, Packet&) = 0;
  };
  ```
  ⚠ **소멸자를 `virtual` 로 하지 않으면** 기반 포인터로 삭제할 때
  파생 소멸자가 불리지 않아 자원이 누수된다.
- **소유권을 설계에 적는다.** 누가 만들고 누가 지우는지가 불분명하면
  이중 해제나 누수가 된다. → [Modern C++](../관제/ModernCpp.md)

## 직접 해보기

### 1. 경계를 하나 만들어 보기

인코더를 교체할 수 있게 만든다.

```cpp
// 인터페이스
class IEncoder {
public:
    virtual ~IEncoder() = default;
    virtual bool open(int w, int h, int bitrate) = 0;
    virtual bool encode(const uint8_t* nv12, std::vector<uint8_t>& out) = 0;
};

// 구현 둘
class HwEncoder : public IEncoder { /* V4L2 M2M */ };
class SwEncoder : public IEncoder { /* libx264 */ };

// 고르는 곳 — 여기만 구현을 안다
std::unique_ptr<IEncoder> makeEncoder() {
    if (hasHardwareEncoder()) return std::make_unique<HwEncoder>();
    return std::make_unique<SwEncoder>();
}
```

**「구현을 아는 곳을 한 군데로 모으는 것」**이 이 설계의 핵심이다.
→ [하드웨어 인코더](../압축/하드웨어인코더.md)

### 2. 경계가 제대로 그어졌는지 시험하기

가짜 구현을 만들 수 있으면 경계가 잘 그어진 것이다.

```cpp
class FakeEncoder : public IEncoder {
public:
    bool open(int, int, int) override { return true; }
    bool encode(const uint8_t*, std::vector<uint8_t>& out) override {
        out.assign(1024, 0xAB);          // 가짜 데이터
        return true;
    }
};
```

**하드웨어 없이 상위 논리를 시험할 수 있게 된다.**
이것이 안 되면 경계가 잘못된 자리에 있다는 신호다.

### 3. 결합도를 눈으로 확인

```bash
# 헤더 의존 관계 보기
gcc -MM *.c 2>/dev/null | head -20
```

상위 모듈의 `.c` 가 하위 구현 헤더를 직접 포함하고 있으면
**의존 역전이 안 된 것**이다.

```bash
grep -n '#include "hw_encoder.h"' *.c    # 여러 곳에 나오면 문제
```

### 4. C 로 같은 것을 만들어 보기

```c
/* encoder.h — 인터페이스만 */
struct encoder;
struct encoder *encoder_create(void);                 /* 어느 구현인지 감춘다 */
int  encoder_encode(struct encoder *, const struct frame *, struct packet *);
void encoder_destroy(struct encoder *);
```

구조체 정의를 헤더에 두지 않는 것(불완전 타입)이 **C 의 캡슐화 방법**이다.
호출하는 쪽이 내부 필드를 만질 수 없다.

### 5. 상속을 잘못 쓴 곳 찾기

```
자문 ①: 파생이 기반의 모든 함수를 의미 있게 쓸 수 있는가
자문 ②: 기반 포인터로 파생을 다룰 때 놀랄 일이 없는가
자문 ③: 「~는 ~의 일종이다」가 자연스러운가
```

셋 중 하나라도 아니면 **합성으로 바꾼다.**

### 6. 이식 경계를 미리 정해 보기

플랫폼을 옮길 가능성이 있다면 미리 목록을 만든다.

```
추상화한다:  암호 구현 · 부팅·검증 · 플래시 접근 · 센서 제어 · 인코더
그대로 둔다:  웹 UI · 설정 파일 형식 · 감사 기록 형식 · 프로토콜 처리
```

**전부 추상화하면 코드가 두 배가 되고 아무 이득이 없다.**
바뀔 것만 고른다.

## 더 들어가면

- **ADR (Architecture Decision Record).** 왜 그 경계를 골랐는지 한 장으로 남긴다.
  나중에 「이건 왜 이렇게 됐나」에 답할 수 있다.
  한 결정에 한 문서, 되돌릴 수 없는 선택 위주로 적는다.
- **육각형 아키텍처 / 포트-어댑터.** 핵심 논리를 가운데 두고
  외부 연결을 어댑터로 감싼다. **하드웨어 의존을 바깥으로 미는** 구조다.
- **의존성 주입.** 객체가 필요한 것을 스스로 만들지 않고 받아 쓴다.
  시험용 가짜를 넣기 쉬워진다.
- **상태 기계.** 연결 · 세션 · PTZ 이동처럼 상태가 있는 것은
  상태 기계로 명시하면 「있을 수 없는 전이」를 코드가 막아 준다.
- **PIMPL.** 구현 세부를 헤더에서 감춘다. 컴파일 의존을 줄이고
  ABI 안정성을 얻는다. 라이브러리를 배포할 때 유용하다.
- **가상 호출 비용.** 프레임마다 수만 번 부르는 자리에서는 측정해 본다.
  대개 무시할 수 있지만, **내부 루프 안**이면 다르다.

## 흔한 오해

### 「클래스를 많이 만들면 객체지향이다」

경계가 잘못된 자리에 많으면 오히려 따라가기 어렵다.
**클래스 수가 아니라 「바뀔 때 몇 군데를 고치는가」**로 판단한다.

### 「상속으로 코드를 재사용한다」

상속은 재사용 도구가 아니라 **다형성 도구**다.
코드를 재사용하려면 함수로 빼거나 합성한다.
상속으로 재사용하면 부모를 고칠 때 자식이 전부 깨진다.

### 「인터페이스를 미리 다 만들어 두면 유연하다」

구현이 하나뿐인 인터페이스는 대개 잘못 그어져 있다.
**두 번째 구현이 나올 때 공통을 뽑는 편**이 정확한 경계를 준다.

### 「추상화하면 성능이 떨어진다」

함수 포인터 한 번 거치는 비용은 프레임 처리 비용에 비해 무시할 수준이다.
성능 문제는 대개 **복사와 동기화**에서 나온다.

### 「설계는 문서 작업이다」

설계가 잘 됐는지 확인하는 방법이 있다 — **가짜 구현으로 시험이 되는가.**
그것이 안 되면 문서가 아무리 예뻐도 경계가 잘못된 것이다.

### 「전부 추상화하면 이식이 쉽다」

추상화한 것마다 유지 비용이 든다. 그리고 **하나의 구현만 보고 만든 인터페이스는
두 번째 플랫폼에서 맞지 않는 경우가 많다.**
정말 바뀌는 곳(암호 · 부팅 · 하드웨어 접근)에 집중한다.

## 참고

- **Design Patterns (GoF)** — 용어의 출처. 전부 쓸 필요는 없다
- **C++ Core Guidelines** 의 인터페이스 · 클래스 계층 절
- **`Documentation/driver-api/`** — C 로 된 다형성의 실제 예시
- 관련 항목: [Modern C++](../관제/ModernCpp.md) · [C / C++](C와Cpp.md) · [디바이스 드라이버](../BSP/디바이스드라이버.md)
