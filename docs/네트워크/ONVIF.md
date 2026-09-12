# ONVIF — 업계 표준 연동

> 서로 다른 회사의 카메라와 녹화기가 붙게 하려고 만든 규격 묶음.
> 영상 전송은 RTSP 에 맡기고, **찾기 · 설정 · 제어**를 표준화한다.

## 왜 필요한가

조달 시장에서 「ONVIF 지원」은 사실상 입장 요건이다.
녹화 서버(VMS)는 카메라 회사마다 다른 API 를 붙일 수 없으므로
**ONVIF 로 말이 통하는 카메라만 목록에 올린다.**

기술적으로는 이런 문제를 푼다 — 네트워크에 카메라가 몇 대 있는지 어떻게 아는가,
그 카메라의 RTSP 주소가 무엇인지 어떻게 아는가, 해상도를 어떻게 바꾸는가.

## 최소 이해 수준

- **SOAP/XML 기반이다.** HTTP POST 로 XML 을 보내고 XML 을 받는다.
  REST 가 아니라 2000년대 중반 양식이다. 규격이 그때 만들어졌다.
- **프로파일 단위로 지원 여부를 말한다.** 전부 구현하는 제품은 없다.

  | 프로파일 | 내용 |
  |---|---|
  | **S** | 영상 스트리밍 · PTZ · 멀티캐스트. 카메라의 기본 |
  | **T** | H.265 · 움직임 감지 · 메타데이터 스트림 |
  | **G** | 기기 내 녹화와 재생 |
  | **C** / **A** / **D** | 출입 통제 관련 |
  | **M** | 분석 메타데이터 (객체 분류 등) |

- **WS-Discovery 로 찾는다.** UDP 멀티캐스트 `239.255.255.250:3702` 로
  `Probe` 를 뿌리면 카메라가 자기 서비스 주소를 답한다.
- **서비스가 여러 개다.** `device` · `media` · `ptz` · `imaging` · `events`.
  각각 별도 엔드포인트 URL 을 갖고, 그 목록을 `GetCapabilities` 로 받는다.
- **핵심 호출 순서.**
  ```
  GetCapabilities      어떤 서비스가 있는지
  GetProfiles          스트림 설정 묶음 목록 (주 스트림 · 부 스트림 …)
  GetStreamUri         그 프로파일의 RTSP 주소  ← 실제로 가장 많이 쓰는 것
  GetVideoEncoderConfiguration  해상도 · 비트레이트 · GOP 현재값
  SetVideoEncoderConfiguration  변경
  ```
- **인증은 WS-UsernameToken 이 기본이다.**
  비밀번호를 그대로 보내지 않고 `Base64(SHA1(nonce + created + password))` 를 보낸다.
  **SHA-1 이고, 평문 HTTP 로 오가면 재전송 공격 여지가 있다.**
  HTTPS 위에서 쓰거나 HTTP Digest 를 함께 지원하는 편이 낫다.
- **「프로파일」은 두 가지 뜻으로 쓰인다.** ONVIF 프로파일(S·T·G)과
  미디어 프로파일(스트림 설정 묶음)은 다른 것이다. 문서를 읽을 때 헷갈리는 지점이다.

## 직접 해보기

### 1. 네트워크에서 카메라 찾기

```bash
# python-onvif-zeep 또는 onvif-cli 계열 도구
pip install --user onvif-zeep wsdiscovery
```

```python
from wsdiscovery.discovery import ThreadedWSDiscovery
wsd = ThreadedWSDiscovery(); wsd.start()
for s in wsd.searchServices():
    print(s.getXAddrs(), s.getTypes())
wsd.stop()
```

`http://<IP>/onvif/device_service` 같은 주소가 나오면 그것이 진입점이다.

⚠ 멀티캐스트가 라우터를 넘지 않는다. **카메라와 같은 서브넷**에서 해야 한다.

### 2. SOAP 요청을 직접 보내기

도구 없이 원리를 보려면 `curl` 로도 된다.

```bash
cat > /tmp/req.xml <<'EOF'
<?xml version="1.0"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope">
 <s:Body>
  <GetDeviceInformation xmlns="http://www.onvif.org/ver10/device/wsdl"/>
 </s:Body>
</s:Envelope>
EOF

curl -sk -X POST 'https://<주소>/onvif/device_service' \
  -H 'Content-Type: application/soap+xml; charset=utf-8' \
  --data-binary @/tmp/req.xml | xmllint --format -
```

제조사 · 모델 · 펌웨어 버전이 돌아온다.
**인증 없이 이것이 돌아오면** 정보 노출이다 — 규격상 허용되기도 하지만
보안 요구사항에서는 문제가 될 수 있다.

### 3. RTSP 주소 알아내기

```python
from onvif import ONVIFCamera
cam = ONVIFCamera('192.168.0.10', 80, 'user', 'pass')
media = cam.create_media_service()
for p in media.GetProfiles():
    uri = media.GetStreamUri({'StreamSetup':
        {'Stream':'RTP-Unicast','Transport':{'Protocol':'RTSP'}},
        'ProfileToken': p.token})
    print(p.Name, p.token, uri.Uri)
```

돌아온 주소를 그대로 재생해 본다.

```bash
ffplay -rtsp_transport tcp '<받은 URI>'
```

→ [RTSP](RTSP.md)

### 4. 인코더 설정 읽고 바꾸기

```python
cfg = media.GetVideoEncoderConfigurations()[0]
print(cfg.Encoding, cfg.Resolution, cfg.RateControl)
cfg.RateControl.BitrateLimit = 6000
media.SetVideoEncoderConfiguration({'Configuration': cfg, 'ForcePersistence': True})
```

바꾼 뒤 **실제 비트레이트를 재서 확인한다.** 설정을 받아들이고 무시하는 구현이 있다.
→ [하드웨어 인코더](../압축/하드웨어인코더.md)

### 5. 시각 확인

```python
dt = cam.devicemgmt.GetSystemDateAndTime()
print(dt.UTCDateTime)
```

카메라 시각이 틀어져 있으면 녹화 검색과 감사 기록이 전부 어긋난다.
→ [감사기록](../보안/감사기록.md)

### 6. 규격 준수 여부 확인

ONVIF 가 공식 시험 도구(Device Test Tool)를 배포한다.
**「ONVIF 지원」을 주장하려면 그 도구를 통과하는 것이 기준이다.**
자체 구현이 도구를 통과하는지 먼저 돌려 보는 편이 낫다.

## 더 들어가면

- **이벤트 서비스.** 움직임 감지 · 입출력 접점 변화 등을 구독한다.
  Pull-point(클라이언트가 주기적으로 가져감)와 Base notification(서버가 보냄)이 있고,
  **NAT 뒤에서는 Pull-point 만 현실적이다.**
- **메타데이터 스트림.** 객체 위치·분류를 RTP 의 별도 트랙으로 보낸다.
  Profile M 의 핵심이고, 영상 분석 결과를 VMS 로 넘기는 표준 경로다.
- **PTZ 좌표계.** 절대 위치(`AbsoluteMove`)와 상대 이동(`RelativeMove`),
  연속 이동(`ContinuousMove`)이 있다. 좌표 범위가 기기마다 정규화(-1~1)돼 있다.
- **`ForcePersistence`.** 설정을 재부팅 후에도 유지할지 여부.
  `False` 로 두면 전원 차단 때 되돌아간다.
- **WSDL 로 코드 생성.** 규격이 WSDL 로 배포되므로 클라이언트 스텁을 자동 생성할 수 있다.
  서버 쪽을 직접 구현하려면 `gsoap` 으로 스켈레톤을 만드는 방식이 흔하다.

## 흔한 오해

### 「ONVIF 지원이면 다 연동된다」

프로파일이 맞아야 하고, 같은 프로파일 안에서도 **선택 기능이 많다.**
현장에서 「ONVIF 카메라인데 VMS 에서 안 잡힌다」는 대개
필수가 아닌 호출을 VMS 가 기대했거나, 구현이 규격에서 조금 벗어난 경우다.

### 「ONVIF 가 영상을 전송한다」

전송하지 않는다. ONVIF 는 **RTSP 주소를 알려줄 뿐**이고
그 뒤는 RTSP·RTP 다. 영상이 안 나오면 ONVIF 가 아니라 그쪽을 봐야 한다.

### 「지원하지 않아도 RTSP 주소만 알려주면 된다」

실제로 많은 VMS 가 「수동 RTSP 입력」을 지원한다. 소규모라면 그것으로 충분하다.
다만 **조달 요건에 ONVIF 가 명시되면 대체가 안 된다.**
지원하지 않는데 문서에 지원한다고 적는 것이 가장 나쁜 선택이다.

### 「WS-UsernameToken 이면 안전하다」

SHA-1 다이제스트이고, nonce 재사용을 서버가 막지 않으면 재전송이 가능하다.
**HTTPS 를 전제로 삼아야** 실질적인 보호가 된다.
→ [TLS · X.509](../보안/TLS-X509.md) · [인증과 인가](../보안/인증과인가.md)

### 「WS-Discovery 는 편리하니 켜 두는 게 좋다」

같은 망의 누구나 카메라 목록과 모델명을 얻을 수 있다는 뜻이다.
보안 요구가 강한 설치에서는 **끄고 IP 를 직접 등록**하는 편이 맞다.
켜 둘 것인지는 설정 항목으로 두고, 기본값을 무엇으로 할지 정해야 한다.

## 참고

- **ONVIF Core Specification** — 서비스와 호출의 1차 출처
- **ONVIF Profile S / T Specification** — 무엇이 필수이고 무엇이 선택인지
- **ONVIF Device Test Tool** — 준수 여부 판정 기준
- 관련 항목: [RTSP](RTSP.md) · [REST API · WebSocket](REST와WebSocket.md) · [인증과 인가](../보안/인증과인가.md)
