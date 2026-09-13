# Qt · QML

> Qt 는 C++ 로 화면과 응용을 만드는 프레임워크,
> QML 은 그 화면을 선언적으로 기술하는 언어다.

## 왜 필요한가

관제 프로그램(VMS)의 화면이 대개 Qt 로 만들어진다.
윈도우·리눅스에서 같은 코드로 돌고, **영상 표시 성능이 필요한 곳에
OpenGL 표면을 직접 다룰 수 있기 때문**이다.

임베디드 쪽에서도 쓴다. 보드에 LCD 가 붙은 제품의 로컬 화면이나
설치 도구가 Qt 로 만들어진 경우가 많다.

## 최소 이해 수준

- **두 갈래가 있다.**

  | | Qt Widgets | Qt Quick (QML) |
  |---|---|---|
  | 기술 방식 | C++ 코드 | QML 선언 + JS |
  | 렌더링 | CPU (래스터) | GPU (OpenGL/Vulkan) |
  | 어울리는 곳 | 전통적 데스크톱 UI | 애니메이션 · 터치 · 커스텀 UI |
  | 학습 | C++ 만 알면 된다 | QML 을 따로 배운다 |

  **관제 클라이언트는 Widgets, 임베디드 터치 화면은 QML** 인 경우가 많다.
- **시그널과 슬롯.** Qt 의 이벤트 연결 방식이다.
  ```cpp
  connect(button, &QPushButton::clicked, this, &MainWindow::onClicked);
  ```
  **함수 포인터 방식(위)을 쓴다.** 옛 `SIGNAL()`/`SLOT()` 매크로 방식은
  오타를 런타임까지 못 잡는다.
- **이벤트 루프와 스레드 규칙.** GUI 객체는 **메인 스레드에서만** 만지는 것이 원칙이다.
  다른 스레드에서 화면을 고치면 간헐적으로 죽는다.
  ```cpp
  QMetaObject::invokeMethod(widget, [=]{ widget->setText(s); }, Qt::QueuedConnection);
  ```
- **부모-자식 소유권.** `QObject` 에 부모를 지정하면 부모가 지울 때 같이 지워진다.
  Qt 의 자원 관리는 스마트 포인터가 아니라 이 트리로 돌아간다.
  → [Modern C++](ModernCpp.md)
- **QML 의 골격.**
  ```qml
  import QtQuick
  Rectangle {
      width: 640; height: 480; color: "#202020"
      Text {
          anchors.centerIn: parent
          text: cameraModel.name          // C++ 에서 노출한 객체
          color: "white"
      }
      Behavior on opacity { NumberAnimation { duration: 150 } }
  }
  ```
- **프로퍼티 바인딩.** `width: parent.width / 2` 처럼 쓰면
  **parent 가 바뀔 때 자동으로 다시 계산된다.** QML 의 핵심 개념이다.
- **C++ ↔ QML 연결.**
  ```cpp
  // C++ 쪽: Q_PROPERTY 로 노출
  class CameraModel : public QObject {
      Q_OBJECT
      Q_PROPERTY(QString name READ name NOTIFY nameChanged)
      ...
  };
  engine.rootContext()->setContextProperty("cameraModel", &model);
  ```
  **`NOTIFY` 시그널이 없으면 값이 바뀌어도 화면이 갱신되지 않는다.**
- **빌드 시스템.** 최근에는 CMake 가 기본이고 `qmake` 는 유지 단계다.
  ```cmake
  find_package(Qt6 REQUIRED COMPONENTS Widgets)
  qt_add_executable(app main.cpp)
  target_link_libraries(app PRIVATE Qt6::Widgets)
  ```
- **라이선스가 중요하다.** LGPL 과 상업 라이선스가 있다.
  LGPL 로 쓰면 **동적 링크와 교체 가능성**을 보장해야 하고,
  정적 링크하는 임베디드 제품에서는 조건을 꼼꼼히 봐야 한다.

## 직접 해보기

### 1. 환경 확인

```bash
qmake6 --version 2>/dev/null || qmake --version
cmake --version
pkg-config --modversion Qt6Core 2>/dev/null
```

### 2. 최소 창 띄우기

```cpp
// main.cpp
#include <QApplication>
#include <QLabel>
int main(int argc, char** argv) {
    QApplication app(argc, argv);
    QLabel label("동작함");
    label.resize(240, 80);
    label.show();
    return app.exec();
}
```

```bash
cmake -B build -DCMAKE_PREFIX_PATH=$(qmake6 -query QT_INSTALL_PREFIX) .
cmake --build build && ./build/app
```

### 3. QML 을 파일만으로 실행해 보기

컴파일 없이 QML 을 바로 볼 수 있다. 시안을 만들 때 가장 빠르다.

```bash
cat > t.qml <<'EOF'
import QtQuick
Rectangle {
    width: 400; height: 200; color: "#111"
    Text { anchors.centerIn: parent; text: "안녕"; color: "#eee"; font.pixelSize: 32 }
}
EOF
qml6 t.qml   # 또는 qmlscene
```

### 4. 영상을 화면에 띄우는 경로 고르기

세 가지 방법이 있고 성능이 크게 다르다.

```
① QImage/QPixmap 으로 그리기      — 간단하지만 CPU 복사가 많다. 채널 수가 적을 때만
② QOpenGLWidget + 텍스처 업로드    — YUV 를 셰이더로 변환. 실질적인 표준
③ Qt Multimedia (QVideoSink)      — 편하지만 내부 동작 제어가 어렵다
```

**16채널 이상이면 ②가 사실상 유일한 답이다.**
NV12 를 그대로 텍스처 두 장으로 올리고 셰이더에서 RGB 로 바꾼다 —
CPU 색변환을 없앨 수 있다. → [색공간](../영상/색공간.md)

### 5. GUI 가 멈추는지 확인

무거운 작업을 메인 스레드에서 하면 화면이 굳는다.

```cpp
// 나쁜 예: 버튼 누르면 3초간 창이 반응하지 않는다
connect(btn, &QPushButton::clicked, [] {
    std::this_thread::sleep_for(std::chrono::seconds(3));
});
```

디코딩·파일 I/O·네트워크는 **별도 스레드나 비동기로** 옮긴다.

### 6. 스레드 규칙 위반 잡기

```bash
QT_FATAL_WARNINGS=1 ./build/app
```

Qt 가 내는 경고에서 바로 죽게 만든다. 스레드 오용은 경고로 먼저 나타나므로
**개발 중에는 이것을 켜 두는 편이 낫다.**

### 7. 렌더링 성능 보기

```bash
QSG_RENDER_TIMING=1 qml6 t.qml
QSG_INFO=1 qml6 t.qml          # 어떤 렌더 백엔드인지
```

소프트웨어 렌더러로 떨어져 있으면 성능이 나오지 않는다.

### 8. 임베디드에서 띄우기

X11 이나 Wayland 없이 프레임버퍼로 바로 그릴 수 있다.

```bash
./app -platform linuxfb
./app -platform eglfs
```

`eglfs` 가 GPU 가속 경로다. **보드에 어느 플랫폼 플러그인이 빌드됐는지** 먼저 확인한다.

```bash
./app -platform help
```

## 더 들어가면

- **모델/뷰.** 카메라 목록처럼 데이터가 많은 화면은 `QAbstractItemModel` 을 구현해
  뷰에 연결한다. QML 에서는 `QAbstractListModel` + `Repeater`/`ListView`.
  **데이터를 복사해 뷰에 밀어 넣는 방식은 채널이 늘면 무너진다.**
- **커스텀 렌더링.** `QQuickFramebufferObject` 나 `QSGRenderNode` 로
  QML 장면 안에 직접 그린다. 영상 타일을 QML UI 와 섞을 때 쓴다.
- **다중 화면 레이아웃.** 4·9·16·32 분할을 동적으로 바꾸려면
  타일마다 디코더 수명을 관리해야 한다. **화면에서 사라진 타일의 디코더를
  멈추는 것**이 CPU 를 가장 크게 아낀다.
- **국제화.** `tr()` 로 감싸고 `.ts`/`.qm` 으로 번역을 분리한다.
  나중에 붙이려면 전체 문자열을 다시 훑어야 하므로 처음부터 감싸는 편이 싸다.
- **배포.** `windeployqt` · `linuxdeployqt` 로 의존 라이브러리를 모은다.
  플러그인(이미지 포맷 · 플랫폼)이 빠지면 **개발 PC 에서만 동작**한다.
- **Qt for Python (PySide).** 도구나 시험 스크립트를 빠르게 만들 때 유용하다.
  제품 화면과 별개로 진단 도구를 만드는 용도로 값이 있다.

## 흔한 오해

### 「QML 이 항상 더 낫다」

GPU 가 없거나 드라이버가 부실한 보드에서는 소프트웨어 렌더링으로 떨어져
Widgets 보다 느려진다. **보드에서 먼저 재보고** 결정한다.

### 「시그널·슬롯은 스레드 문제를 알아서 해결한다」

`Qt::QueuedConnection` 이면 수신자의 스레드에서 실행되므로 안전하다.
하지만 `Qt::DirectConnection` 이면 **호출한 스레드에서 그대로 실행**된다.
기본값은 같은 스레드면 Direct, 다른 스레드면 Queued 다 — 의도를 명시하는 편이 낫다.

### 「`QThread` 를 상속해서 `run()` 에 로직을 넣는다」

옛 방식이다. 지금은 작업 객체를 만들고 `moveToThread()` 로 옮기는 방식을 권한다.
상속 방식은 **어느 코드가 어느 스레드에서 도는지 헷갈리기 쉽다.**

### 「영상은 `QLabel` 에 `QPixmap` 으로 띄우면 된다」

1~2채널이면 된다. 그 이상은 프레임마다 색변환 + CPU→GPU 복사가 쌓여
**채널 수에 비례해 CPU 가 포화**한다. 텍스처 경로로 가야 한다.

### 「LGPL 이니 그냥 써도 된다」

정적 링크 · 플러그인 포함 · 임베디드 배포에서 조건이 달라진다.
제품 출하 전에 라이선스 형태를 확정해야 하고, **나중에 바꾸려면 비용이 크다.**

## 참고

- **Qt Documentation** — 클래스별 문서가 1차 출처
- **Qt Quick Best Practices** — QML 성능 지침
- **`QT_FATAL_WARNINGS`** · **`QSG_RENDER_TIMING`** — 실무 디버깅 환경변수
- 관련 항목: [Modern C++](ModernCpp.md) · [FFmpeg](FFmpeg.md) · [색공간](../영상/색공간.md)
