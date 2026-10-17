# HANDOFF — 다른 IDE·환경에서 이어서 작업하기 위한 인계 문서

작성: 2026-10-17 (Python→Rust 전환 5개 슬라이스 완료 시점)
저장소: https://github.com/lzpxilfe/3d_scan_next_step (branch: main)
먼저 읽을 문서: `AGENTS.md`(운영 규칙)와 본 문서. 전체 문서 체계는 `00_README.md`부터.

---

## 1. 현재 상태 (한 문단)

제품 코어와 GUI를 **Rust**로 전면 전환한 단계
(결정 `docs/DECISIONS.md` D-2026-10-12-11). D-03(Python 중심)·D-08(GUI=PySide6)은
D-11에 의해 대체됨. Python 코드(`src/archphoto/`, 95테스트)는 삭제하지 않고
**이식의 참조 구현**으로 보존. egui 0.37 셸이 코어 계약과 연결되어 실행 검증됨.

- 전환 이유: 배포 단순성, 계약의 컴파일 타임 강제, 고속화 코어 성능 필요.
- 파이썬은 참조 구현 + 연구 실험(R01 학습식 깊이맵 등) 전용으로 남긴다.

---

## 2. 명령어 셰트 (그대로 복붙)

Rust (제품):

```bash
export PATH="$HOME/.cargo/bin:$PATH"   # rustc/cargo는 ~/.cargo/bin
cargo build --workspace
cargo test --workspace                 # 현재 81 passed (archphoto-core 77 + archphoto-gui 4)
cargo clippy --workspace --all-targets -- -D warnings
cargo fmt --check
./target/debug/archphoto-gui           # egui 셸 실행 확인용
```

Python (참조 구현·연구 실험):

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=src .venv/bin/python -m pytest tests -q   # 110 passed
```

GitHub 푸시 (설정 변경 없이 1회용 자격증명; gh는 lzpxilfe로 로그인 상태):

```bash
git -c credential.helper= -c credential.helper='!/opt/homebrew/bin/gh auth git-credential' push origin main
```

---

## 3. 코어 이식 현황 (Python → Rust 매핑)

| Python 참조 (src/archphoto/) | Rust (crates/archphoto-core/src/) | 상태 |
|---|---|---|
| geom/crs.py (LengthUnit·SpatialFrame) | `crs.rs` | ✅ `#[non_exhaustive]` + 공백 전용 `crs_id` 거부 + 빌더 |
| geom/crs.py (Transform3D·쿼터니언) | `transform.rs` | ✅ 축/단위/회전 5단계 규약, 데이터툼 혼합·비유한값 거부 |
| geom/plane.py | `plane.rs` | ✅ `#[non_exhaustive]` + 유한성 검증 + 단면 절단용 |
| sensing/control·observations·photos·cameras | `sensing.rs` | ✅ `SurveyRole` 타입 강제, `Photo::from_file`(순수 std SHA-256·PNG IHDR), `DerivedImage`, `Camera`/`Intrinsics`/`Extrinsics` |
| quality/ledger·checkpoints | `quality.rs` | ✅ GCP/CHECK 분리·장부 거부·프레임 일관성 검사·`evaluate_check` 통계 |
| recon/register.py | `register.rs` | ✅ Horn+Umeyama·Jacobi·RANSAC·공선(collinear) tie 거부·`SpatialFrame` 전체 일치 검사·면 인덱스 범위 검사 |
| mesh/product.py + archaeo/surface.py | `mesh.rs` | ✅ 정직성 2축 + `SurfaceProduct` + `HonestyReport` + `MeshSidecar`(`mesh_sidecar`, JSON 직렬화) |
| mesh/export.py | `export.rs` | ✅ OBJ/PLY(`double` 좌표 + `uchar observed`) + `.sidecar.json` 의무 동시 출력 |
| archaeo/measure.py | `measure.rs` | ✅ `Measurement`(`derived=true`), `measure_distance`, `length_residual` |
| archaeo/section.py | `section.rs` | ✅ `compute_section`(보간 정점 포함 삼각형 `Interpolated` 전파, 공면 삼각형 제외), `interpretation_line` |
| archaeo/ortho.py | `ortho.rs` | ✅ `OrthoSpec`(축 직교성 검사), `OrthoGrid`, `OrthoProduct`(프레임 일치 검사) |
| archaeo/targets.py | `targets.rs` | ✅ `TargetClass`(`Artifact`/`Feature`/`Site`), `TargetSpec` |
| project/manifest.py | `project.rs` | ✅ `RawItem::from_file`, `ProjectManifest`, 읽기 전용 `verify_raw_integrity` (Python/Rust 모두 구현) |
| runlog/record.py | `runlog.rs` | ✅ `ProcessState`·`ValidationState` 분리, 미측정 자원(`Option<f64> = None`) 보존 |
| reproducibility.py | `reproducibility.rs` | ✅ `DeterminismSettings`, `compare_point_sequences`, `compare_point_maps` |
| recon/baseline·pipeline·depth + engines/base | `baseline.rs` | ✅ `PipelineConfig`(GCP/CHECK 중복 거부), `DepthRepresentation`, `EngineInfo`, `BaselineEngine` 트레이트, `run_baseline` |
| preflight.py | `preflight.rs` | ✅ 중복 ID·고아 관측·검증점 부재·점 간 `inconsistent_frame` 검사 |
| GUI 셸/기준점·측정·사진뷰어 (PySide6) | crates/archphoto-gui `main.rs` | ✅ 대화형 프레임·기준점·거리 측정·사진 등록·무결성 검사·뷰어 픽셀 관측 + 합성 데모/영속 `PointUsageLedger` |

테스트: Rust **81 passed** (`archphoto-core` 77 + `archphoto-gui` 4), `cargo clippy -- -D warnings` 0건.
Python 참조 **110 passed** (`tests/test_export.py` 및 `ProjectManifest.verify_raw_integrity` 포함).

---

## 4. 이어서 할 일 (우선순위 순)

1. **네이티브 파일 대화상자 및 실제 비트맵 텍스처 디코딩** — 필요 시 외부 크레이트(`rfd`, 이미지 텍스처 업로더 등) 라이선스·영향 검토 후 egui에 연결.
2. **egui 아이콘 렌더링** — `assets/icons/*.svg` 9종을 egui 툴바에 연결.
3. **3D 메시 뷰포트 (`wgpu`) 및 실제 자료 수락 기준 검증** (`docs/BASELINE_T06.md`) — 사용자 실제 사진/측량 자료 도착 및 COLMAP 등 기준선 엔진 라이선스·설치 확정 후 진행.

---

## 5. 미결·[O] 항목 (주의)

- **COLMAP 등 엔진 설치는 보류**(D-05) — 실제 복원 기준선 실행 불가 상태. 수락 기준은 `docs/BASELINE_T06.md`.
- **Rust 크레이트 라이선스 미검증** — nalgebra/egui 등 도입 전 Apache-2.0 호환 확인 필요(T03 방법론 참조).
- **등록/기하에 nalgebra 필요 예정** — 새 외부 의존성; 영향 설명 후 추가 규칙 준수.
- **Windows 대상 크로스컴파일 배포 전략 미확정** — 개발기 mac arm64, 대상기 Windows+GTX 1060.
- RANSAC `inlier_threshold=0.1` 등 문턱값은 **[O]** — 합성용일 뿐, 실측 검증된 기본값이 아님.
- R01 학습식 깊이: 현장 실험은 대상기 CUDA 필요 — **미실행**을 미실행으로 유지. 가중치는 ONNX 경유 [O].

---

## 6. 함정·알아둘 것 (다음 세션용 결정 근거)

- **eframe 0.37 API 필수 사항**: `eframe::App`은 `fn update`가 아니라
  `fn ui(&mut self, ui: &mut egui::Ui, frame: &mut Frame)`; 패널은 통합형
  `egui::Panel::left/right/top/bottom(id)` + 항상 마지막에 `CentralPanel::default()`.
  구버전 SidePanel/TopBottomPanel은 없음. 근거: 설치 소스
  `~/.cargo/registry/src/index.crates.io-.../eframe-0.37.0/src/epi.rs`.
- **egui 클로저 반환형 일치**: `match` 양팔 간 반환 타입을 맞출 것
  (예: `Some..=> { ui.monospace(..); } None=> { ui.label(..); }` — 세미콜론으로 통일).
- **SpatialFrame::new는 ContractResult를 반환** — 빈 crs_id 거부. 새 코드에서 미반영해 에러가 나면 이것부터 확인.
- **Point3D는 `[f64; 3]` 타입 별칭** — `let OriginCounts(..) = ..`처럼 별칭 패턴 분해는 불가.
- **RANSAC RNG는 Rust 로컬결정론(SplitMix64)** — Python MT19937 스트림과 다름. 원자적 재현성은
  토론 언어별로만 보장(문서동일). `register.rs` 문서 참조.
- **커밋 메시지 토션**: fb3dfce에 "合成"(한자) 오탈자 — force-push 금지 원칙으로 유지, 이후 커밋부터 "합성"으로 교정.
- **AGENTS.md 원칙 재확인**: 원자료 무훼손, GCP/검증점 분리, 좌표계·단위·높이기준 명시,
  관측/보간·실측/전시 구분, "실행 성공 ≠ 측량 검증 통과", 가짜 벤치마크 금지.

---

## 7. 엔지니어링 로그 (Rust 전환분, 최신순)

| 커밋 | 내용 |
|---|---|
| fb3dfce | gui(egui): 코어 연결 — 합성 정합/평가/점검/병합 + 거부계약 시연 |
| bcfd2ee | rust: preflight 이식 (런타임 검사 유지, 계약검사 컴파일타임 승격) |
| 7797782 | rust: 정합/붙이기 이식 — Horn+Umeyama, Jacobi, RANSAC, MeshProduct 정직성축 |
| 44ac072 | rust: 기하계약 이식 — Transform3D(데이터툼혼합 거부), Plane |
| 0487db4 | rust: sensing+quality 이식 — 컴파일타임 역할 강제, 장부 거부 |
| 51919c4 | rust: cargo 워크스페이스 스캐폴드(결정 D-11), egui 0.37 셸 |
| 7d75d8d | gui(PySide6) 참조 셸 — 도킹·측정·사진뷰어·픽셀관측 (이식 원천) |
| 725a6ce | core(Python) 참조 계약 전체 (95테스트) |
| 3eac28f | docs: 요구 패키지·결정 로그·Apache-2.0 |

---

## 8. 다음 세션이 도입부에서 확인할 3가지

1. `git pull` 후 `cargo test -p archphoto-core` → 51 passed 여부.
2. 이 문서 §4의 1순위(`mesh_sidecar`)부터 — 목적·수정범위·입출력·수락기준을 먼저 정의.
3. 사용자가 제공할 예정인 실제 시험자료 도착 여부(아직 없음).
