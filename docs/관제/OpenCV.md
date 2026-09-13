# OpenCV

> 영상 처리와 컴퓨터 비전 함수를 모아 놓은 라이브러리.
> 프로토타입을 빠르게 만드는 데 강하고, 제품 파이프라인에서는 조심해서 써야 한다.

## 왜 필요한가

움직임 감지 · 영역 침입 · 번호판 위치 찾기 같은 기능을 만들 때
필터 · 배경 차분 · 윤곽선 검출을 처음부터 쓰지 않아도 된다.

그리고 **실험 속도가 압도적이다.** Python 으로 몇 줄 써서
「이 방법이 되는가」를 30분 안에 확인할 수 있다.
그 답을 얻은 다음에 C++ 로 옮기거나 다른 구현으로 바꾸면 된다.

## 최소 이해 수준

- **`cv::Mat` 이 중심이다.** 헤더 + 데이터 포인터 구조이고,
  **대입은 얕은 복사(참조 카운트)**다.
  ```cpp
  cv::Mat b = a;           // 같은 데이터를 가리킨다
  cv::Mat c = a.clone();   // 실제 복사
  ```
  이것을 모르면 「원본이 왜 바뀌었나」로 시간을 쓴다.
- **채널 순서가 BGR 이다.** RGB 가 아니다.
  다른 라이브러리와 주고받을 때 `cv::cvtColor` 로 맞춘다.
  → [색공간](../영상/색공간.md)
- **모듈 구성.**

  | 모듈 | 내용 |
  |---|---|
  | `core` | `Mat` · 기본 연산 |
  | `imgproc` | 필터 · 변환 · 윤곽선 · 모폴로지 |
  | `videoio` | 파일·카메라 입출력 (내부적으로 FFmpeg·V4L2 사용) |
  | `highgui` | 창 표시 (디버깅용) |
  | `video` | 배경 차분 · 광류 · 추적 |
  | `dnn` | 신경망 추론 |
  | `objdetect` | Haar/HOG 검출기 (지금은 DNN 쪽이 주류) |

- **`videoio` 는 얇은 포장이다.** `cv::VideoCapture("rtsp://...")` 는
  내부에서 FFmpeg 를 쓴다. **옵션 제어가 제한적**이므로
  타임아웃·전송 방식을 세밀하게 다뤄야 하면 FFmpeg 를 직접 쓴다.
  → [FFmpeg](FFmpeg.md)
- **`dnn` 모듈로 추론도 된다.** ONNX 모델을 읽어 돌린다.
  전용 런타임보다 느리지만 **의존성이 하나로 끝나는 이점**이 있다.
- **Python 과 C++ API 가 거의 같다.** Python 으로 검증하고 C++ 로 옮기는 흐름이
  자연스럽다. 함수 이름과 인자가 대응되기 때문이다.
- **임베디드에서는 크기가 문제다.** 전체 빌드가 수십 MB 다.
  필요한 모듈만 켜서 빌드해야 플래시에 들어간다.
  → [플래시 · 파일시스템](../BSP/플래시와파일시스템.md)

## 직접 해보기

### 1. 설치와 빌드 정보 확인

```bash
python3 -c "import cv2; print(cv2.__version__); print(cv2.getBuildInformation())" | head -40
```

`Video I/O` 절에서 **FFmpeg · V4L2 가 `YES` 인지** 본다.
`NO` 면 RTSP 나 카메라를 열 수 없다.

### 2. RTSP 스트림 열어 보기

```python
import cv2, time
cap = cv2.VideoCapture("rtsp://<주소>/stream", cv2.CAP_FFMPEG)
print("열림:", cap.isOpened())
n, t0 = 0, time.time()
while n < 100:
    ok, frame = cap.read()
    if not ok:
        print("읽기 실패"); break
    n += 1
print(f"{n}프레임 / {time.time()-t0:.1f}초 = {n/(time.time()-t0):.1f} fps")
print("크기:", frame.shape, "dtype:", frame.dtype)
cap.release()
```

⚠ **`read()` 에 타임아웃이 없다.** 카메라가 멈추면 그대로 블로킹된다.
환경변수로 일부 제어할 수 있다.

```bash
export OPENCV_FFMPEG_CAPTURE_OPTIONS="rtsp_transport;tcp|stimeout;5000000"
```

### 3. 움직임 감지를 가장 단순하게

```python
import cv2
cap = cv2.VideoCapture(0)
bg = cv2.createBackgroundSubtractorMOG2(history=300, varThreshold=25)
while True:
    ok, f = cap.read()
    if not ok: break
    mask = bg.apply(f)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,
                            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5,5)))
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in cnts:
        if cv2.contourArea(c) < 800:      # 작은 것은 무시
            continue
        x,y,w,h = cv2.boundingRect(c)
        cv2.rectangle(f, (x,y), (x+w,y+h), (0,255,0), 2)
    cv2.imshow("f", f)
    if cv2.waitKey(1) == 27: break
```

**임계값 두 개(`varThreshold`, 면적 하한)가 오검출률을 거의 전부 결정한다.**
나뭇잎·비·조명 변화에서 값을 조정해 봐야 감을 얻는다.

### 4. 처리 시간 재기

```python
import cv2, time
img = cv2.imread("t.png")
for name, fn in [("blur", lambda: cv2.GaussianBlur(img,(15,15),0)),
                 ("gray", lambda: cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)),
                 ("resize", lambda: cv2.resize(img,(640,360)))]:
    t=time.perf_counter()
    for _ in range(100): fn()
    print(f"{name}: {(time.perf_counter()-t)*10:.2f} ms/회")
```

**30fps 라면 프레임당 예산이 33ms 다.** 이 숫자와 비교해서
어느 연산까지 넣을 수 있는지 판단한다.

### 5. 얕은 복사를 눈으로 확인

```python
import numpy as np, cv2
a = np.zeros((4,4), np.uint8)
b = a          # 얕은 복사
c = a.copy()   # 깊은 복사
a[0,0] = 9
print(b[0,0], c[0,0])    # 9 0
```

C++ 의 `cv::Mat` 도 같다.

### 6. DNN 추론 돌려 보기

```python
import cv2
net = cv2.dnn.readNetFromONNX("model.onnx")
blob = cv2.dnn.blobFromImage(img, 1/255.0, (640,640), swapRB=True, crop=False)
net.setInput(blob)
out = net.forward()
print(out.shape)
```

`swapRB=True` 를 빠뜨리면 **BGR 을 RGB 로 학습한 모델에 잘못 넣는 것**이라
정확도가 조용히 떨어진다. 오류가 안 나기 때문에 찾기 어렵다.

### 7. 임베디드용으로 작게 빌드

```bash
cmake -B build -S opencv \
  -DBUILD_LIST=core,imgproc,imgcodecs,video \
  -DBUILD_SHARED_LIBS=OFF -DBUILD_TESTS=OFF -DBUILD_PERF_TESTS=OFF \
  -DBUILD_EXAMPLES=OFF -DWITH_GTK=OFF -DWITH_QT=OFF \
  -DCMAKE_TOOLCHAIN_FILE=<툴체인 파일>
cmake --build build -j$(nproc)
```

`BUILD_LIST` 로 모듈을 줄이는 것이 크기를 가장 크게 줄인다.
→ [크로스 컴파일](../BSP/크로스컴파일.md)

## 더 들어가면

- **`cv::UMat` 과 OpenCL.** `Mat` 대신 `UMat` 을 쓰면 가능한 연산이 GPU 로 간다.
  다만 전송 비용이 있어 **작은 이미지에서는 오히려 느리다.**
- **광류(optical flow).** 픽셀이 어디로 움직였는지 계산한다.
  추적과 속도 추정에 쓰지만 계산이 무겁다.
- **추적기(tracker).** 검출을 매 프레임 하지 않고 중간을 추적으로 메운다.
  추론 비용을 크게 줄이는 실전 기법이다.
- **호모그래피와 보정.** 어안 렌즈 왜곡 보정, 평면 시점 변환.
  주차장·출입구처럼 **바닥 평면에서 좌표를 재야 할 때** 쓴다.
- **관심 영역(ROI).** `img(cv::Rect(...))` 는 복사 없이 부분만 가리킨다.
  전체 프레임을 처리하는 대신 ROI 만 보면 비용이 크게 줄어든다.
- **스레드 설정.** OpenCV 는 내부적으로 병렬 처리를 한다.
  채널마다 프로세스를 띄우는 구조라면 `cv::setNumThreads(1)` 로 제한하는 편이
  전체 처리량이 낫다.

## 흔한 오해

### 「OpenCV 로 만들면 제품에 바로 쓸 수 있다」

프로토타입과 제품은 다르다. 실시간 제약 · 메모리 상한 · 오류 복구 ·
타임아웃이 전부 추가로 필요하다. **OpenCV 는 「된다」를 확인하는 데 최적이고,
「계속 돈다」를 보장하는 것은 별개의 일**이다.

### 「`VideoCapture` 로 RTSP 를 받으면 된다」

옵션 제어가 제한적이고 타임아웃 처리가 약하다. 관제 제품에서
**한 채널이 멈추면 전체가 멈추는 문제**가 여기서 나온다.
FFmpeg 를 직접 쓰거나 별도 프로세스로 격리한다.

### 「`imshow` 로 확인하면 충분하다」

`highgui` 는 디버깅 도구다. 제품 화면에는 쓰지 않는다 —
성능도, 레이아웃 제어도 부족하다. 표시는 Qt 쪽으로 넘긴다.
→ [Qt · QML](Qt-QML.md)

### 「배경 차분으로 움직임 감지가 끝난다」

조명 변화 · 흔들리는 나뭇잎 · 비 · 그림자 · 자동 노출 변화가 전부
움직임으로 잡힌다. 실제 제품은 **최소 면적 · 지속 시간 · 영역 마스크 ·
시간대별 임계값**을 조합해야 오검출을 줄일 수 있다.

### 「해상도를 그대로 처리해야 정확하다」

대부분의 검출은 축소한 프레임에서 해도 결과가 비슷하고 **비용은 제곱으로 줄어든다.**
1080p 를 480p 로 줄여 검출하고, 좌표만 원본 비율로 되돌리는 것이 표준 기법이다.

## 참고

- **OpenCV Documentation** — 모듈별 튜토리얼이 충실하다
- `cv2.getBuildInformation()` — 무엇이 켜져 빌드됐는지의 1차 확인
- 관련 항목: [Video Analytics](VideoAnalytics.md) · [FFmpeg](FFmpeg.md) · [색공간](../영상/색공간.md)
