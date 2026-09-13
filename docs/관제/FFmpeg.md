# FFmpeg

> 영상·음성을 다루는 사실상의 표준 도구이자 라이브러리 묶음.
> 명령행 도구로도 쓰고, 코드에 링크해서도 쓴다.

## 왜 필요한가

관제 소프트웨어에서 디코딩 · 트랜스코딩 · 녹화 · 포맷 변환을 직접 구현하는 일은
거의 없다. **FFmpeg 를 쓴다.** 코덱과 컨테이너의 예외 처리를
스스로 따라잡는 것이 현실적이지 않기 때문이다.

그리고 진단 도구로서의 값이 크다. 카메라 스트림에 문제가 있을 때
`ffprobe` 한 번이면 **해상도 · 코덱 · GOP · 비트레이트 · 타임스탬프 이상**이 다 보인다.

## 최소 이해 수준

- **도구 세 개.**
  ```
  ffmpeg    변환 · 녹화 · 스트리밍
  ffprobe   분석 (사람용 · 기계용 출력 둘 다)
  ffplay    재생 (디버깅용)
  ```
- **라이브러리 구성.**

  | 라이브러리 | 역할 |
  |---|---|
  | `libavformat` | 컨테이너 (MP4 · TS · RTSP · HLS) |
  | `libavcodec` | 코덱 (H.264 · H.265 · JPEG) |
  | `libavutil` | 공통 (프레임 · 버퍼 · 로그) |
  | `libswscale` | 크기 변환 · 색공간 변환 |
  | `libswresample` | 음성 리샘플 |
  | `libavfilter` | 필터 그래프 |

- **처리 흐름.**
  ```
  입력 열기 → 스트림 찾기 → 패킷 읽기(AVPacket)
      → 디코딩(AVFrame) → [처리] → 인코딩(AVPacket) → 컨테이너에 쓰기
  ```
  `AVPacket` 은 압축된 데이터, `AVFrame` 은 픽셀이다. 이 구분이 기본이다.
- **`-c copy` 가 가장 중요한 옵션이다.** 디코딩·인코딩을 건너뛰고
  패킷을 그대로 옮긴다. 녹화에서는 **CPU 를 거의 안 쓰고 화질 손실도 없다.**
  ```bash
  ffmpeg -i rtsp://... -c copy out.mp4      # 트랜스코딩 없음
  ```
- **옵션의 위치가 의미를 바꾼다.** `-i` 앞의 옵션은 입력에, 뒤의 옵션은 출력에 적용된다.
  ```bash
  ffmpeg -rtsp_transport tcp -i rtsp://...  -c:v libx264 out.mp4
  #      └─ 입력 옵션 ─┘              └─ 출력 옵션 ─┘
  ```
  **이것을 뒤바꿔 「옵션이 안 먹는다」고 하는 경우가 가장 흔하다.**
- **타임스탬프(PTS/DTS)를 의식한다.** 라이브 스트림을 받아 파일로 쓸 때
  타임스탬프가 튀면 재생이 깨진다. `-fflags +genpts` 나 `-vsync` 로 다룬다.
- **로그 레벨을 올려서 본다.** 기본 출력은 요약이다.
  ```bash
  ffmpeg -loglevel debug ...
  ```

## 직접 해보기

### 1. 스트림을 분석하기

```bash
ffprobe -v error -show_streams -show_format rtsp://<주소>/stream
```

기계가 읽을 형태로:

```bash
ffprobe -v error -select_streams v:0 \
  -show_entries stream=codec_name,width,height,r_frame_rate,bit_rate \
  -of json rtsp://<주소>/stream
```

**스크립트로 점검할 때는 `-of json` 이나 `-of csv` 를 쓴다.**

### 2. GOP 구조 확인

```bash
ffprobe -v error -select_streams v -show_frames \
  -show_entries frame=pict_type,pkt_size,pts_time \
  -read_intervals '%+#120' -of csv rtsp://<주소>/stream | head -40
```

`I` 가 몇 프레임마다 나오는지 세면 GOP 길이다.
**새 시청자의 첫 화면 지연이 이 값에 비례한다.** → [H.264](../압축/H264.md)

### 3. 실제 비트레이트 재기

```bash
timeout 30 ffmpeg -v error -rtsp_transport tcp -i rtsp://<주소>/stream \
  -c copy -f mp4 /tmp/t.mp4
ls -l /tmp/t.mp4
ffprobe -v error -show_entries format=duration,bit_rate -of default=nw=1 /tmp/t.mp4
```

설정한 비트레이트와 다르면 인코더가 설정을 무시한 것이다.
→ [하드웨어 인코더](../압축/하드웨어인코더.md)

### 4. 녹화를 시간 단위로 자르기

```bash
ffmpeg -rtsp_transport tcp -i rtsp://<주소>/stream -c copy \
  -f segment -segment_time 600 -reset_timestamps 1 \
  -strftime 1 '/rec/%Y%m%d_%H%M%S.mp4'
```

`-c copy` 이므로 CPU 부담이 거의 없다.
**조각 경계가 키프레임에 맞아야** 각 파일이 독립적으로 재생된다.

### 5. 프레임 유실·오류 감지

```bash
ffmpeg -v error -rtsp_transport udp -i rtsp://<주소>/stream \
  -t 60 -f null - 2>&1 | sort | uniq -c | sort -rn | head
```

`corrupt decoded frame` · `missing picture` 가 쌓이면 전송 유실이다.
TCP 로 바꿔서 사라지면 네트워크 문제가 확정된다. → [RTP](../네트워크/RTP.md)

### 6. 지연 낮추기

```bash
ffplay -fflags nobuffer -flags low_delay -framedrop \
  -rtsp_transport tcp rtsp://<주소>/stream
```

기본 설정은 안정적인 재생을 위해 버퍼를 둔다.
**「카메라 지연이 크다」고 판단하기 전에 재생 쪽 버퍼를 먼저 빼고 재본다.**

### 7. 하드웨어 가속 확인

```bash
ffmpeg -hwaccels
ffmpeg -decoders | grep -iE 'h264|hevc' | head
```

관제 PC 에서 32채널을 디코딩하려면 하드웨어 디코더가 필요하다.

```bash
ffmpeg -hwaccel vaapi -i in.mp4 -f null -     # 리눅스 인텔/AMD
```

### 8. 코드로 쓸 때의 최소 골격

```c
AVFormatContext *fc = NULL;
AVDictionary *opt = NULL;
av_dict_set(&opt, "rtsp_transport", "tcp", 0);
av_dict_set(&opt, "stimeout", "5000000", 0);   /* 5초, 마이크로초 단위 */

if (avformat_open_input(&fc, url, NULL, &opt) < 0) return -1;
avformat_find_stream_info(fc, NULL);
int vs = av_find_best_stream(fc, AVMEDIA_TYPE_VIDEO, -1, -1, NULL, 0);

AVPacket *pkt = av_packet_alloc();
while (av_read_frame(fc, pkt) >= 0) {
    if (pkt->stream_index == vs) { /* 디코딩 또는 그대로 저장 */ }
    av_packet_unref(pkt);          /* 매번 해제해야 한다 */
}
```

⚠ **`stimeout` 을 주지 않으면 카메라가 응답을 멈출 때 영원히 블로킹된다.**
관제 소프트웨어의 「한 채널이 멈추자 전체가 멈췄다」의 흔한 원인이다.

## 더 들어가면

- **필터 그래프.** `-vf` / `-filter_complex` 로 크기 변경 · 겹치기 · 타일 배치를 한다.
  ```bash
  ffmpeg -i a -i b -filter_complex 'hstack' out.mp4
  ```
  다중 화면 합성을 여기서 처리할 수 있지만 CPU 를 많이 쓴다.
- **`libswscale` 의 비용.** 색공간·크기 변환은 생각보다 무겁다.
  파이프라인 전체를 같은 포맷으로 맞춰 변환을 없애는 편이 낫다.
  → [색공간](../영상/색공간.md)
- **비트스트림 필터.** 디코딩 없이 패킷만 손본다.
  `h264_mp4toannexb` 는 MP4 안의 H.264 를 스트림 형태로 바꿀 때 반드시 필요하다.
- **`-re` 옵션.** 파일을 실시간 속도로 읽는다. 라이브 스트리밍 시험에 쓰고,
  **실제 라이브 입력에는 쓰지 않는다** — 붙이면 오히려 지연이 쌓인다.
- **스레드 설정.** `-threads` 와 `thread_type`. 지연을 줄이려면
  프레임 단위 병렬(`frame`)을 끄고 슬라이스 단위만 쓴다.
- **라이선스.** LGPL 빌드와 GPL 빌드가 다르다. `--enable-gpl` 로 빌드하면
  전체가 GPL 이 된다. **제품에 넣을 때 확인이 필요하다.**
  ```bash
  ffmpeg -version | head -3    # 빌드 설정이 보인다
  ```

## 흔한 오해

### 「`-c copy` 가 안 되면 트랜스코딩할 수밖에 없다」

대개 컨테이너가 그 코덱을 못 담는 경우다. 컨테이너를 바꿔 보면 된다
(`.mp4` → `.mkv` 또는 `.ts`). 트랜스코딩은 **마지막 수단**이다.

### 「ffprobe 가 보여주는 비트레이트가 실제 비트레이트다」

컨테이너 헤더에 적힌 값일 수 있고, 라이브 스트림에서는 비어 있거나 부정확하다.
**받은 바이트를 시간으로 나눠서** 재는 것이 확실하다.

### 「FFmpeg 로 받으면 카메라 문제를 다 알 수 있다」

FFmpeg 는 관대해서 규격에서 벗어난 스트림도 재생한다.
**FFmpeg 로 잘 나오는데 다른 클라이언트에서 안 되는** 경우가 실제로 있다.
호환성 판단은 여러 클라이언트로 해야 한다. → [RTSP](../네트워크/RTSP.md)

### 「라이브러리를 쓰면 명령행보다 빠르다」

같은 코드가 돈다. 라이브러리를 쓰는 이유는 속도가 아니라
**프로세스 내에서 프레임을 직접 다루고 오류를 세밀하게 처리하기 위한 것**이다.
단순 녹화라면 `ffmpeg` 프로세스를 띄우는 편이 안전하고 격리도 된다.

### 「타임아웃은 기본값이 있다」

RTSP 입력에서 읽기 타임아웃은 기본적으로 무한이다.
`stimeout`(또는 최신 버전의 `timeout`)을 명시해야 한다.
**이것을 빠뜨린 코드는 언젠가 멈춘다.**

## 참고

- **FFmpeg Documentation** — `ffmpeg -h full` 이 가장 정확한 옵션 목록
- **`doc/examples/`** — 라이브러리 사용 예제 (소스 트리에 포함)
- `ffprobe -of json` — 자동화할 때의 출력 형식
- 관련 항목: [H.264](../압축/H264.md) · [RTSP](../네트워크/RTSP.md) · [OpenCV](OpenCV.md)
