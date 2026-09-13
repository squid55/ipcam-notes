# Modern C++ (C++11 이상)

> C++11 을 기점으로 언어가 크게 달라졌다.
> 자원 관리를 사람이 손으로 맞추지 않게 만든 것이 가장 큰 변화다.

## 왜 필요한가

관제 소프트웨어는 카메라 수십~수백 대의 연결·디코딩·표시를 동시에 다룬다.
객체가 계속 생기고 사라지는데 **해제를 손으로 맞추면 반드시 어긋난다.**
누수는 메모리를 먹고, 이중 해제는 프로세스를 죽인다.

그리고 이 계층은 성능이 곧 채널 수다. 불필요한 복사 한 번이
프레임마다 수 MB 를 옮기는 비용이 된다.

## 최소 이해 수준

- **RAII.** 자원의 수명을 객체의 수명에 묶는다. 소멸자가 해제를 책임진다.
  `new`/`delete` 를 직접 쓰는 코드는 대개 잘못된 신호다.
- **스마트 포인터 세 개.**

  | | 뜻 | 쓰는 곳 |
  |---|---|---|
  | `std::unique_ptr` | 소유자가 하나 | 기본값. 대부분 이것 |
  | `std::shared_ptr` | 참조 카운트로 공유 | 정말 공유가 필요할 때만 |
  | `std::weak_ptr` | 소유하지 않는 관찰 | `shared_ptr` 순환 끊기 |

  ```cpp
  auto dec = std::make_unique<Decoder>(cfg);   // new 없이
  ```
  `shared_ptr` 을 기본으로 쓰면 **누가 소유자인지 코드에서 사라진다.**
- **이동 의미론(move).** 복사하지 않고 소유권을 넘긴다.
  프레임 버퍼처럼 큰 객체에서 결정적이다.
  ```cpp
  std::vector<uint8_t> buf = decode();        // 복사 아님 (이동)
  queue.push(std::move(buf));                 // buf 는 이후 비어 있다
  ```
- **`auto` 는 타입을 숨기는 게 아니라 반복을 줄이는 것이다.**
  반복자·람다·템플릿 반환값에 쓴다. 의미가 불분명해지는 곳에는 쓰지 않는다.
- **람다와 `std::function`.** 콜백을 자유롭게 넘길 수 있다.
  캡처 방식을 반드시 의식한다 — `[&]` 는 참조라서 **객체가 먼저 죽으면 매달린 참조**가 된다.
  비동기 콜백에는 값 캡처나 `shared_ptr` 캡처를 쓴다.
- **범위 기반 `for`.**
  ```cpp
  for (const auto& cam : cameras) { ... }   // 복사 없이 읽기
  ```
- **`nullptr` · `override` · `= delete` · `enum class`.**
  작은 것들이지만 **컴파일 시점에 실수를 잡아 준다.** 특히 `override` 는
  가상 함수 서명을 잘못 적은 것을 즉시 알려준다.
- **표준 스레드.** `std::thread` · `std::mutex` · `std::lock_guard` ·
  `std::condition_variable` · `std::atomic`.
  잠금은 항상 `lock_guard`/`unique_lock` 으로 잡는다 — 예외가 나도 풀린다.
- **버전별 실무에서 쓰는 것.**
  - C++14 — `make_unique`, 제네릭 람다
  - C++17 — `std::optional` · `std::string_view` · `if` 초기화문 · 구조분해
  - C++20 — `std::span` · 개념(concepts) · `std::format`
  **툴체인이 지원하는 표준이 상한이다.** 임베디드 쪽은 특히 확인이 필요하다.

## 직접 해보기

### 1. 표준 버전과 컴파일러 확인

```bash
g++ --version
echo '__cplusplus' | g++ -x c++ -std=c++17 -E - | tail -1
```

`201703` 이 나오면 C++17 이다. 크로스 툴체인에서도 같이 확인한다.
→ [크로스 컴파일](../BSP/크로스컴파일.md)

### 2. 이동이 실제로 일어나는지 눈으로 보기

```cpp
#include <cstdio>
#include <vector>
#include <utility>

struct Big {
    std::vector<int> d;
    Big() : d(1'000'000) { puts("생성"); }
    Big(const Big&)            { puts("복사"); }
    Big(Big&&) noexcept        { puts("이동"); }
};

int main() {
    Big a;
    Big b = a;              // 복사
    Big c = std::move(a);   // 이동
    std::vector<Big> v;
    v.push_back(Big{});     // 임시 → 이동
}
```

```bash
g++ -std=c++17 -O2 move.cpp -o move && ./move
```

**어디서 복사가 일어나는지 출력으로 확인**하는 것이 최고의 학습법이다.

### 3. 누수와 매달린 참조를 도구로 잡기

```bash
# 주소 오류 · 누수
g++ -std=c++17 -g -fsanitize=address,undefined t.cpp -o t && ./t

# 경쟁 조건
g++ -std=c++17 -g -fsanitize=thread t.cpp -o t && ./t
```

⚠ `address` 와 `thread` 는 **함께 켤 수 없다.** 따로 돌린다.

```bash
valgrind --leak-check=full ./t
```

### 4. 매달린 람다 캡처를 재현해 보기

```cpp
#include <functional>
#include <cstdio>
std::function<void()> f;
void setup() {
    int local = 42;
    f = [&]{ printf("%d\n", local); };   // 위험: local 은 곧 사라진다
}
int main() { setup(); f(); }
```

`-fsanitize=address` 로 빌드해 돌리면 `stack-use-after-return` 이 잡힌다.
**이 실수가 비동기 콜백에서 가장 흔하다.**

### 5. 잠금 없이 공유하면 어떻게 되는지

```cpp
#include <thread>
#include <vector>
#include <cstdio>
int counter = 0;   // 보호 없음
int main() {
    std::vector<std::thread> ts;
    for (int i = 0; i < 8; ++i)
        ts.emplace_back([]{ for (int j = 0; j < 100000; ++j) ++counter; });
    for (auto& t : ts) t.join();
    printf("%d (기대 800000)\n", counter);
}
```

값이 매번 다르게 나온다. `std::atomic<int>` 로 바꾸면 맞는다.

### 6. 정적 분석

```bash
clang-tidy t.cpp -- -std=c++17
cppcheck --enable=all t.cpp
```

`clang-tidy` 의 `modernize-*` 규칙이 옛 코드를 고칠 지점을 알려준다.

## 더 들어가면

- **복사 생략과 RVO.** 반환값은 대개 복사되지 않는다.
  `return std::move(local);` 은 오히려 최적화를 막는 경우가 있다.
- **`std::shared_ptr` 의 비용.** 참조 카운트가 원자적 연산이라
  프레임마다 수만 번 복사하면 눈에 띈다. 함수 인자로는 `const&` 로 받는다.
- **`std::string_view` · `std::span`.** 복사 없이 구간만 가리킨다.
  **원본보다 오래 살면 안 된다**는 제약이 따라온다.
- **예외를 쓸지 말지.** 임베디드는 `-fno-exceptions` 로 빌드하는 경우가 있다.
  그러면 표준 컨테이너의 오류 처리 전략이 달라지므로 미리 정해야 한다.
- **`std::optional` 과 오류 반환.** 「값이 없을 수 있음」을 타입으로 표현한다.
  `-1` 이나 널 포인터로 표현하는 관례를 줄일 수 있다.
- **코루틴 (C++20).** 비동기 I/O 를 동기 코드처럼 쓸 수 있다.
  다만 툴체인 지원과 학습 비용이 있어 도입 판단이 필요하다.
- **빌드 위생.** `-Wall -Wextra -Wpedantic` 을 켜고, 경고를 남기지 않는다.
  경고가 수백 개 쌓인 프로젝트에서는 **새로 생긴 진짜 경고가 묻힌다.**

## 흔한 오해

### 「`shared_ptr` 을 쓰면 안전하다」

순환 참조가 생기면 절대 해제되지 않는다. 카메라 → 세션 → 카메라 같은
양방향 관계에서 쉽게 발생한다. 한쪽을 `weak_ptr` 로 만들어 끊어야 한다.

### 「`std::move` 를 붙이면 빨라진다」

이동 생성자가 없는 타입에서는 그냥 복사다. 그리고 `move` 는
**대상을 비우는 약속**이므로 그 뒤에 원본을 쓰면 정의되지 않은 상태를 읽는다.

### 「스마트 포인터를 쓰면 스레드 안전하다」

참조 카운트만 원자적이다. **가리키는 객체의 내용은 보호되지 않는다.**
여러 스레드가 같은 객체를 고치면 별도 잠금이 필요하다.

### 「최신 표준을 쓰면 코드가 좋아진다」

새 기능을 쓰는 것과 설계가 좋아지는 것은 별개다.
소유권이 명확한지, 수명이 추적 가능한지가 핵심이고
그것은 C++11 만으로도 충분히 표현된다.

### 「최적화는 나중에」

프레임 경로에서는 구조가 성능을 결정한다. 큐에 무엇을 넣는지
(버퍼 자체인가, 핸들인가)를 나중에 바꾸려면 전체를 고쳐야 한다.
**복사가 일어나는 경계만 미리 설계**하고 나머지는 나중에 해도 된다.

## 참고

- **C++ Core Guidelines** — 실무 규칙 모음 (소유권 · 수명 절이 특히 유용)
- **cppreference.com** — 표준 라이브러리 1차 참조
- `clang-tidy` `modernize-*` — 옛 코드를 옮길 때의 점검 목록
- 관련 항목: [FFmpeg](FFmpeg.md) · [Qt · QML](Qt-QML.md) · [크로스 컴파일](../BSP/크로스컴파일.md)
