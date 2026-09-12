# RTSP · RTSPS

> RTSP(Real Time Streaming Protocol, RFC 2326 / 7826)는 영상 스트림을 **제어**하는 규약이다.
> 영상 데이터 자체는 대개 RTP 로 따로 흐른다.

## 왜 필요한가

IP카메라와 NVR·VMS 를 잇는 사실상의 표준이다. 「카메라를 연동한다」는 말은 대개
**RTSP URL 을 주고받는다**는 뜻이다.

```
rtsp://카메라주소:554/경로
```

그리고 보안 요구가 붙는 순간 두 가지를 답해야 한다 — **누가 볼 수 있는가**(인증)와
**중간에서 볼 수 있는가**(암호화). RTSP 자체는 둘 다 제공하지 않으므로 별도로 얹는다.

## 최소 이해 수준

- **제어와 전송이 분리된다.**
  RTSP 는 「재생해라 / 멈춰라」를 주고받는 채널이고, 실제 프레임은 RTP 로 간다.
  그래서 방화벽 설정이 까다롭다 — 제어는 TCP 554, 전송은 UDP 임의 포트가 기본이다.
- **주요 메서드.**
  `OPTIONS` → `DESCRIBE` → `SETUP` → `PLAY` → `TEARDOWN`.
  `DESCRIBE` 의 응답이 **SDP** 이고, 거기에 코덱·해상도·파라미터셋이 들어 있다.
- **Transport 헤더가 전송 방식을 정한다.**
  `RTP/AVP` (UDP) · `RTP/AVP/TCP` (TCP 인터리브) · `RTP/SAVP` (SRTP).
  NAT·방화벽 뒤에서는 TCP 인터리브가 현실적이다.
- **인증은 HTTP 방식을 그대로 쓴다.**
  Basic 은 평문이라 실사용 불가. Digest 가 기본이고, 응답 헤더에
  `algorithm`·`qop` 가 없으면 RFC 2617 의 MD5 계열이다 —
  **최신 규격(RFC 7616)이 아니며 강도 요구를 만족하지 못할 수 있다.**
- **RTSPS 는 RTSP 를 TLS 로 감싼 것이다.**
  제어 채널이 암호화되고, TCP 인터리브를 쓰면 **미디어까지 같은 TLS 안으로 들어온다.**
  포트는 관례적으로 322 또는 임의 포트를 쓴다.
- **SRTP 는 미디어만 암호화한다.**
  제어는 별도다. RTSPS + TCP 인터리브와 목적이 겹치므로 둘 중 하나를 고른다.

## 직접 해보기

### 1. 인증 없이 접근해 보기

```bash
# 인증이 걸려 있으면 401 이 와야 한다
curl -v --max-time 5 rtsp://카메라주소:554/경로 2>&1 | head -20
```

`401 Unauthorized` 와 함께 `WWW-Authenticate` 헤더가 오는지 본다.
**그 헤더의 내용이 인증 강도를 말해준다.**

```
WWW-Authenticate: Digest realm="...", nonce="..."
        → algorithm·qop 없음 = MD5 계열
WWW-Authenticate: Digest realm="...", algorithm=SHA-256, qop="auth"
        → RFC 7616
```

⚠ `realm` 에 구현체 이름(`LIVE555 Streaming Media` 등)이 그대로 노출되는 경우가 많다.
제품 이름으로 바꾸는 것이 좋다.

### 2. SDP 받아보기

```bash
ffprobe -v verbose -rtsp_transport tcp rtsp://계정:비번@주소:554/경로 2>&1 | head -40
```

코덱·해상도·프로파일이 SDP 에서 나온다. `sprop-parameter-sets` 가 있으면
SPS/PPS 가 SDP 에 실려 온 것이다 — 스트림 중간에 붙어도 디코딩이 시작된다.

### 3. 실제로 받아 저장

```bash
ffmpeg -rtsp_transport tcp -i rtsp://계정:비번@주소:554/경로 \
       -t 10 -c copy out.mp4
```

`-c copy` 로 재인코딩 없이 받는다. 파일이 정상 재생되면 전송·디코딩 경로가 성립한 것이다.

### 4. TLS 구간 확인 (RTSPS)

```bash
openssl s_client -connect <주소>:<RTSPS포트> -brief </dev/null
```

프로토콜 버전과 암호군이 나온다. `TLSv1.3` 과 AEAD 계열 암호군을 기대한다.
`TLSv1.0`·`TLSv1.1` 이 협상되면 제품 쪽에서 막아야 한다.

⚠ 호스트의 `openssl` 판본이 옛 프로토콜을 제거했으면 **「협상 안 됨」이 서버 설정이 아니라
내 도구의 한계**일 수 있다. 이 구분을 놓치면 잘못된 결론이 남는다.

## 더 들어가면

- **RTCP** — 손실률·지터를 되보고해 송신 측이 조절하게 한다. 실시간 품질 진단의 근거.
- **RTP 페이로드 포맷** — H.264 는 RFC 6184, H.265 는 RFC 7798.
  NAL 이 MTU 를 넘으면 FU-A 로 조각내는 규칙이 여기 있다.
- **ONVIF** — RTSP 위에 「장치 발견·설정·이벤트」를 표준화한 것.
  NVR 자동 검색이 되려면 이것이 필요하다.
- **인터리브 모드의 프레이밍** — TCP 한 연결에 제어와 미디어를 섞을 때
  `$` + 채널번호 + 길이 헤더로 구분한다.

## 흔한 오해

### 「RTSP 는 영상을 전송하는 프로토콜이다」

제어 프로토콜이다. 전송은 RTP 가 한다. 이 구분을 놓치면 방화벽·NAT 문제를
진단할 수 없다.

### 「RTSPS 를 쓰면 미디어도 자동으로 암호화된다」

전송 방식에 달렸다. TCP 인터리브면 미디어가 같은 TLS 연결로 들어오므로 보호되지만,
UDP 로 RTP 를 따로 보내면 **제어만 암호화되고 영상은 평문이다.**

### 「같은 라이브러리로 만든 서버와 클라이언트는 당연히 붙는다」

실측: live555 서버의 `parseTransportHeader()` 는 `RTP/AVP{,/TCP,/SAVP}` 만 인식하는데,
같은 라이브러리의 클라이언트는 RFC 3711 표준 이름인 **`RTP/SAVP/TCP`** 를 보낸다.
결과는 `461 Unsupported Transport` 다. VLC 도 내부적으로 live555 를 쓰므로 같이 실패한다.

**증상만으로는 서버 문제인지 클라이언트 문제인지 구분되지 않는다.**
SETUP 의 Transport 헤더를 직접 봐야 갈린다.

### 「서버 옵션은 서로 독립이다」

실측: live555 기반 서버에서 수신 인터페이스를 지정하면 그 값이 라이브러리 전역
변수에 들어가고 **HTTP 터널링 바인딩까지 따라간다.**
"RTSP 는 외부, HTTP 는 루프백"처럼 나누려는 구성이 구조적으로 막힌다.

## 참고

- **RFC 7826** — RTSP 2.0. 구버전은 RFC 2326
- **RFC 3550** — RTP / RTCP
- **RFC 6184** — RTP 에 H.264 를 싣는 방법
- **RFC 7616** — HTTP Digest 인증(SHA-256). 구버전은 RFC 2617
- 관련 항목: [H.264](../압축/H264.md) · [TLS · X.509](../보안/TLS-X509.md) · [인증과 인가](../보안/인증과인가.md)
