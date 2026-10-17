# 아이콘 (원본 SVG)

이 폴더의 아이콘은 **직접 디자인한 원본**입니다. 기존 아이콘 세트를 복제하지 않았습니다.
프로젝트와 같은 Apache-2.0으로 배포됩니다.

## 형식

- 24×24 `viewBox`, `stroke="currentColor"`, 두께 2, 둥근 끝/모서리.
- 색은 테마에 따라 자동(테마색을 `currentColor`로 받음) — 라이트/다크 대응.
- **프레임워크 무관 SVG 원본.** Qt(QIcon)·웹·Dear PyGui(텍스처 변환) 어디든 사용 가능.
  필요하면 PNG로 래스터화.

## 아이콘 목록 (코어 워크플로)

| 파일 | 의미 | 대응 모듈 |
|---|---|---|
| `photos.svg` | 사진 가져오기 | `sensing.photos` |
| `camera.svg` | 카메라 보정 | `sensing.cameras` |
| `control.svg` | GCP·기준점 | `sensing.control` |
| `stitch.svg` | 블록·스캔 정합("붙이기") | `recon.register` |
| `section.svg` | 단면·프로파일 | `archaeo.section` |
| `mesh.svg` | 3D 메시 | `mesh.product` |
| `validate.svg` | 독립 검증 | `quality.checkpoints` |
| `export.svg` | 내보내기(정제 도구로) | `mesh.export` |

## 통합 방법 (프레임워크 확정 후)

아이콘은 모양만 있고 **위젯 결합은 GUI 프레임워크가 정해져야** 가능합니다. 프레임워크가
정해지면 `gui/`에서 위젯 액션에 이 SVG를 붙입니다. 현재 `gui/`는 스텁이며 프레임워크는 미확정 [O].
