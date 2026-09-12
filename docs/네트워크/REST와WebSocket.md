# REST API · WebSocket

> REST 는 「요청하면 답한다」는 단방향 구조, WebSocket 은 연결을 열어 두고
> 양쪽이 아무 때나 보내는 구조다. 카메라 웹 UI 는 대개 둘을 함께 쓴다.

## 왜 필요한가

카메라의 설정 화면과 상태 표시가 전부 이 위에서 돈다.
ONVIF 는 VMS 연동용이고, **사람이 브라우저로 쓰는 관리 화면은 자체 API** 가 맡는다.

그리고 「지금 이벤트가 났다」를 화면에 띄우려면 서버가 먼저 말을 걸어야 한다.
REST 만으로는 그것이 안 된다.

## 최소 이해 수준

- **REST 의 뼈대.** 자원을 URL 로 표현하고, 동작을 HTTP 메서드로 표현한다.

  ```
  GET    /api/streams          목록 조회
  GET    /api/streams/1        하나 조회
  PUT    /api/streams/1        전체 교체
  PATCH  /api/streams/1        일부 수정
  POST   /api/users            생성
  DELETE /api/users/3          삭제
  ```

- **상태 코드를 제대로 쓴다.** `200` 성공 · `201` 생성됨 · `400` 요청이 잘못됨 ·
  `401` 인증 없음 · `403` 권한 없음 · `404` 없음 · `409` 충돌 · `500` 서버 오류.
  **`401` 과 `403` 을 구분**해야 클라이언트가 「다시 로그인」과 「권한 요청」을 가를 수 있다.
- **멱등성(idempotent).** `GET`·`PUT`·`DELETE` 는 여러 번 해도 결과가 같아야 하고,
  `POST` 는 그렇지 않다. 재시도 로직이 이 구분에 의존한다.
- **WebSocket 은 HTTP 로 시작한다.**
  ```
  GET /ws HTTP/1.1
  Upgrade: websocket
  Connection: Upgrade
  Sec-WebSocket-Key: <base64 16바이트>
  Sec-WebSocket-Version: 13
  ```
  서버가 `101 Switching Protocols` 로 답하면 그 TCP 연결이 양방향 메시지 통로가 된다.
- **`wss://` 를 쓴다.** `ws://` 는 평문이다. HTTPS 페이지에서 `ws://` 를 열면
  브라우저가 막는다(혼합 콘텐츠).
- **언제 무엇을 쓰는가.**

  | | REST | WebSocket |
  |---|---|---|
  | 설정 읽기·쓰기 | 맞다 | 굳이 |
  | 주기적 상태 갱신 | 폴링으로 가능 | 더 낫다 |
  | 이벤트 알림 (서버 → 클라이언트) | 안 된다 | 맞다 |
  | 캐시 · 프록시 친화 | 좋다 | 없다 |
  | 디버깅 | `curl` 로 끝 | 도구가 필요 |

- **중간 대안이 있다.** **SSE**(Server-Sent Events)는 HTTP 위의 단방향 푸시다.
  서버 → 클라이언트만 필요하면 WebSocket 보다 훨씬 간단하다.
  구현이 `Content-Type: text/event-stream` + 텍스트 흘려보내기로 끝난다.

## 직접 해보기

### 1. REST 엔드포인트 훑기

```bash
curl -sk -o /dev/null -w '%{http_code} %{url_effective}\n' \
  https://<주소>/api/streams \
  https://<주소>/api/users \
  https://<주소>/api/system
```

**인증 없이 `200` 이 나오는 경로가 있는지**가 첫 점검이다.
→ [인증과 인가](../보안/인증과인가.md)

### 2. 쓰기 요청이 권한을 확인하는지

읽기 권한만 있는 계정으로 쓰기를 시도한다.

```bash
curl -sk -u viewer:<비밀번호> -X PATCH \
  -H 'Content-Type: application/json' \
  -d '{"bitrate":6000000}' \
  -w '\n%{http_code}\n' https://<주소>/api/streams/1
```

`403` 이어야 한다. `200` 이면 **권한 검사가 메서드별로 안 걸려 있는 것**이다.
화면에서 버튼을 숨기는 것과는 무관하다.

### 3. CSRF 방어 확인

브라우저 세션 쿠키로 인증하는 API 라면, 다른 출처에서 온 요청을 막아야 한다.

```bash
curl -sk -X POST -H 'Origin: https://evil.example' \
  -H 'Content-Type: application/json' -d '{}' \
  -b 'sid=<유효한 세션>' -w '\n%{http_code}\n' \
  https://<주소>/api/system/reboot
```

거부되어야 한다. 통과하면 **다른 사이트에 방문한 것만으로 카메라가 재부팅될 수 있다.**

### 4. WebSocket 핸드셰이크 직접 보기

```bash
curl -sk -i -N \
  -H 'Connection: Upgrade' -H 'Upgrade: websocket' \
  -H 'Sec-WebSocket-Version: 13' \
  -H 'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==' \
  https://<주소>/ws | head -10
```

`HTTP/1.1 101` 과 `Sec-WebSocket-Accept` 가 보이면 업그레이드가 된 것이다.

### 5. 실제 메시지 주고받기

```bash
# websocat 설치 후
websocat -k wss://<주소>/ws
```

이벤트가 흘러오는지 본다. 인증이 필요하면 쿠키나 토큰을 헤더로 넣는다.

```bash
websocat -k -H='Cookie: sid=<세션>' wss://<주소>/ws
```

### 6. 브라우저에서

```js
const ws = new WebSocket('wss://' + location.host + '/ws');
ws.onopen    = () => console.log('열림');
ws.onmessage = e => console.log('받음', e.data);
ws.onclose   = e => console.log('닫힘', e.code, e.reason);
ws.onerror   = e => console.log('오류', e);
```

`onclose` 의 코드를 반드시 찍어 본다. `1006` 은 「비정상 종료」이고
**이유를 알려주지 않는다** — 서버 로그를 함께 봐야 원인이 나온다.

### 7. SSE 가 더 간단한지 비교

```bash
curl -skN https://<주소>/api/events
```

```
event: motion
data: {"zone":2,"at":1757740000}

```

빈 줄이 메시지 경계다. 이것만으로 알림이 되면 WebSocket 을 안 써도 된다.

## 더 들어가면

- **핑·퐁과 유휴 타임아웃.** WebSocket 연결은 중간 장비가 조용한 연결을 끊는다.
  주기적으로 핑을 보내야 유지된다. 프로토콜에 제어 프레임으로 들어 있다.
- **재연결 전략.** 끊기면 즉시 재시도하지 않고 **지수 백오프 + 지터**를 둔다.
  카메라 수십 대가 서버 재시작 때 동시에 몰리는 것을 막는다.
- **메시지 형식을 정해 둔다.** `{"type":"...","payload":{...}}` 처럼
  타입 필드를 앞에 두는 관례가 흔하다. 없으면 분기 코드가 금방 지저분해진다.
- **버전 관리.** `/api/v1/...` 로 경로에 넣거나 헤더로 협상한다.
  펌웨어 업데이트로 API 가 바뀌면 **옛 클라이언트가 깨진다.**
- **OpenAPI 명세.** API 를 YAML 로 적어 두면 문서 · 클라이언트 코드 · 시험을
  거기서 생성할 수 있다. 제출 문서가 필요한 제품에서 특히 값이 있다.
- **Rate limiting.** 로그인 API 에 초당 요청 제한을 두지 않으면
  비밀번호 대입 속도를 막을 수 없다. 계정 잠금과 별개로 필요하다.

## 흔한 오해

### 「REST 는 JSON 을 쓰는 HTTP API 다」

형식이 아니라 **자원 중심 설계**가 핵심이다.
`POST /api/doAction?name=reboot` 만 잔뜩 있는 API 는 JSON 을 써도 REST 가 아니다.
동작이 메서드에, 대상이 URL 에 있어야 클라이언트가 예측할 수 있다.

### 「WebSocket 이 REST 보다 좋다」

용도가 다르다. 설정 조회를 WebSocket 으로 하면 캐시도 못 쓰고
`curl` 로 확인도 못 하고, 상태 코드로 오류를 구분할 수도 없다.
**푸시가 필요한 곳에만** 쓴다.

### 「WebSocket 연결이 열렸으니 인증은 끝났다」

연결 시점에 한 번 확인했을 뿐이다. 세션이 만료돼도 **연결은 살아 있다.**
긴 연결에서는 주기적으로 세션을 다시 확인하고, 만료되면 서버가 끊어야 한다.
이때 **확인이 세션을 갱신하지 않게** 주의해야 한다 —
갱신하면 연결이 열려 있는 동안 세션이 영원히 살아난다.
→ [인증과 인가](../보안/인증과인가.md)

### 「같은 출처에서만 요청이 올 것이다」

브라우저는 다른 출처에서도 요청을 보낸다. 쿠키 기반 인증이라면
`Origin` 검사나 CSRF 토큰이 필요하다. **WebSocket 은 CORS 가 적용되지 않으므로
서버가 `Origin` 을 직접 검사해야 한다** — 이것을 빠뜨리는 경우가 많다.

### 「폴링은 나쁘고 푸시는 좋다」

1초 주기 폴링이 필요한 상황이면 푸시가 낫지만, 30초 주기 상태 갱신이라면
폴링이 훨씬 단순하고 실패에 강하다. **연결 하나를 관리하지 않아도 되는 것**이
생각보다 큰 이점이다.

⚠ 다만 폴링이 세션을 계속 갱신하면 유휴 만료 시험이 성립하지 않는다.
읽기 전용 확인 경로를 따로 두어야 한다.

## 참고

- **RFC 9110** — HTTP 시맨틱스 (메서드 · 상태 코드)
- **RFC 6455** — WebSocket 프로토콜
- **WHATWG HTML: Server-sent events** — SSE 규격
- **OWASP CSRF Prevention Cheat Sheet**
- 관련 항목: [TLS · X.509](../보안/TLS-X509.md) · [인증과 인가](../보안/인증과인가.md) · [ONVIF](ONVIF.md)
