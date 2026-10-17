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
| `ortho.svg` | 정사영상 투영·격자 | `archaeo.ortho` |
| `mesh.svg` | 3D 메시 | `mesh.product` |
| `validate.svg` | 독립 검증 | `quality.checkpoints` |
| `export.svg` | 내보내기(정제 도구로) | `mesh.export` |

## 통합 상태

- Python 참조 구현(`src/archphoto/gui/icons.py`)에서는 `QSvgRenderer`로 9종 모두 툴바 액션에 로드·검증됨 (`tests/test_gui.py`).
- Rust 제품 GUI(`crates/archphoto-gui`, `egui` — D-2026-10-12-11 확정)에는 추후 텍스처/벡터 렌더러로 연결 예정.
