# T06. 작은 자료 기준선 — 실행 준비(런북·작업카드)

작성일: 2026-10-12.
**상태: 준비 완료, 실행 안 함(BLOCKED).** 사용자 결정(D-2026-10-12-05)으로 엔진 설치를
**보류**했고, 시험자료는 **사용자 제공** 예정이다. 따라서 실제 기준선을 돌리지 않았다.
이 문서는 재현 가능한 설정·명령·기록 템플릿과 중단 조건, 자료 인계 체크리스트만 정의한다.
속도·정확도·성공 결과를 기록하지 않았다(AGENTS: 가짜 벤치마크 금지).

관련: [엔진 조사](ENGINES.md) · [라이선스 결정](DECISIONS.md) · [검증 요구](../05_ACCURACY_DATA_AND_VALIDATION.md) ·
[데이터 계약](../data/schemas/) · [런기록](../src/archphoto/runlog/record.py) · [공간](../04_HARDWARE_STORAGE_AND_BUDGET.md)

## 1. 작업 카드

```markdown
# T06: 작은 자료 기존 엔진 기준선
## 목적
고고학 소형 자료 하나에 대해, 기존 엔진(COLMAP 계열)로 사진→카메라 해→점군/메시까지
재현 가능한 기준선을 만든다. 이후 학습형 경로(R01) 비교의 대조군(A)이 된다.
## 선행 조건
- [ ] 기준선 엔진 설치 + 설치 허가 + 디스크 여유 확인 (04). 미충족 → BLOCKED.
- [ ] 작은 시험자료(사진 + GCP + 독립 검증점) 확보. 실제 자료는 반출·사용 권한 확인.
- [ ] 좌표계·단위·높이 기준 확정 (현재 미정 [O]).
## 읽을 문서와 코드
ENGINES.md, 05_ACCURACY..., data/schemas/, sensing/control.py, runlog/record.py
## 입력 / 출력
입력: photo_manifest.json, control_points.json, observations.json (스키마 준수).
출력: sparse/dense 모델, 점군, 메시 + RunRecord(재현 기록).
단위·좌표는 입력 SpatialFrame을 따르며 명시.
## 수정 허용 범위
실행 스크립트/런북, 기록 템플릿. 원자료·엔진 코드 수정 없음.
## 구현 지시
1) 입력 검사(스키마·GCP/검증점 분리·좌표) → 2) 기준선 실행 → 3) 기록·검증 분리 보고.
이번에 하지 않을 일: GUI, 학습형 경로, 대규모 자료, 성능 튜닝.
## 힌트·근거
엔진 선택 근거는 ENGINES.md(COLMAP=BSD, Apache 호환 유력). 명령명은 공식 문서에서 확인,
플래그는 설치 버전에서 재확인.
## 수락 기준
재현 가능한 설정·명령·기록이 남고, 처리 성공과 측량 검증 통과가 분리 표시됨.
## 검증
합성 테스트(계약)와 실제 자료 테스트 분리. 실제 자료는 권한 확보 후.
## 자원·보안
설치·다운로드·GPU·외부 전송 없이 준비만. 실제 자료 외부 업로드 금지.
## 중단 조건
엔진 설치 불가, 자료 없음, 좌표계 미정, 공간 부족, 반출 권한 없음 → 현재 이 상태.
## 인계
준비물·미실행 사유·다음 한 작업.
```

## 2. 재현 가능한 기준선 런북 (미실행)

기준선 엔진은 **COLMAP**을 후보로 택한다(근거: [ENGINES.md](ENGINES.md) — BSD-3이라
Apache-2.0 배포와 호환 유력, GCP는 카메라 중심 정합 위주). 아래 명령명은 COLMAP 공식
문서/FAQ에서 확인한 것이다. **정확한 플래그·경로는 설치된 버전에서 반드시 재확인**하고,
아래는 실행 결과가 아니라 **재현용 레시피**다.

```bash
# 0) 입력 검사 (구현됨: archphoto.preflight.preflight_control)
#    스키마·GCP-검증점 분리·좌표/단위를 실행 전에 확인. 오류가 있으면 중단.

# 1) 특징 추출·매칭
colmap feature_extractor --database_path $DB --image_path $IMAGES
colmap exhaustive_matcher  --database_path $DB     # 소형: exhaustive / 대형: vocab_tree

# 2) SfM (카메라 해)
colmap mapper --database_path $DB --image_path $IMAGES --output_path $SPARSE

# 3) (선택) 지리정합 — COLMAP은 카메라 중심 좌표 기준 (ENGINES.md 2.1)
colmap model_aligner --input_path $SPARSE/0 --output_path $SPARSE/1 \
  --ref_images_path $CAM_CENTERS --ref_is_gps 0 --alignment_type custom \
  --robust_alignment_max_error 3.0
#   ※ 이미지 GCP(픽셀↔지상) 번들 조정은 main 포함 여부 미확인 [O]. 카메라 위치 자료 필요.

# 4) 왜곡보정·고밀화·메시
colmap image_undistorter --image_path $IMAGES --input_path $SPARSE/1 \
  --output_path $DENSE --output_type COLMAP --max_image_size 4000
colmap patch_match_stereo --workspace_path $DENSE --workspace_format COLMAP \
  --PatchMatchStereo.geom_consistency true
colmap stereo_fusion --workspace_path $DENSE --workspace_format COLMAP \
  --input_type geometric --output_path $DENSE/fused.ply
colmap poisson_mesher --input_path $DENSE/fused.ply --output_path $DENSE/meshed.ply
colmap delaunay_mesher --input_path $DENSE --output_path $DENSE/meshed-delaunay.ply
```

- **GCP 주의:** 위 `model_aligner`는 카메라 중심 정합이다. 전통적 GCP(사진 픽셀↔지상 좌표)는
  별도 도구/추가 작업 필요(ENGINES.md 2.1). 검증점(CHECK)은 어떤 정합·보정에도 쓰지 않는다.
- **재현 기록:** 아래 §3 템플릿에 설정 전체·버전·시간·자원·출력을 기록한다.

## 3. RunRecord 템플릿 (실행 시 채울 것)

```yaml
run_id: T06-baseline-001
process_state: not_started     # succeeded/failed/partial — 처리 성공만 의미
validation_state: not_run      # passed/failed/inconclusive — 검증점 기반, 별개
engine_version: ""             # 예: colmap <version>  (확정 후 기록)
code_version: "archphoto 0.0.1"
weight_version: ""             # 기준선엔 미사용
parameters: {}                 # 위 런북 전체 설정 복사
input_hashes: {}               # photo_id -> sha256 (원자료 무결성)
selected_views: []             # 기준선은 전체 시점 사용 시 []
resources: { wall_seconds: null, peak_ram_mb: null, peak_vram_mb: null, disk_mb: null }  # null=미측정
outputs: []
log_path: ""
retry_count: 0
failure_reason: null
```

## 4. 미실행 항목과 사유 (명시)

| 항목 | 상태 | 사유 |
|---|---|---|
| 엔진 설치·실행 | 미실행 | 설치 허가·디스크 확인 전 (04). AGENTS: 설치 전 영향 설명·허가 |
| 실제 기준선 출력 | 미생성 | 시험자료 미확보 + 엔진 미설치 |
| 속도·정확도 | 미측정 | 측정 전. 수치 기록 금지 |
| 좌표 변환 실사용 | 미실행 | 좌표계·높이 기준 미정 [O] |
| 학습형 경로(R01) | 미실행 | 별도 작업(T09+). 기준선 대조군 먼저 |

## 5. 중단 조건과 다음 한 작업

현재 **BLOCKED**(설치·자료·좌표 미정). 안전하게 진행 가능한 다음 한 작업 후보:
1) **T05: 입력·좌표 합성 테스트** — 설치 없이 스키마·GCP/검증점 분리·단위 계약을 합성 자료로 검증.
2) 엔진 설치 허가 + 공간 확인 → 기준선 실제 실행(위 런북).

> 실제 자료가 포함된 실행은 반드시 사용자 반출·사용 권한을 먼저 확인한다.

## 6. 사용자 제공 자료 인계 체크리스트

사용자가 시험자료를 제공할 때, 아래가 충족되어야 기준선을 시작할 수 있다(계약: `data/schemas/`).

| 항목 | 필요한 것 | 미비 시 |
|---|---|---|
| 원사진 | 원본 보존 + `photo_id`, 해상도, `sha256`(무결성) | 원본 훼손 위험 → 보류 |
| 카메라 | 내부행렬·왜곡 모델(EXIF 또는 보정값) | 축척·왜곡 미상 → 보류 |
| GCP | 좌표 + 좌표계·단위·높이 기준 + 사진별 픽셀 관측 | 좌표 계약 불가 → 보류 |
| 독립 검증점 | GCP와 **분리**된 CHECK 좌표(+관측) | 독립 검증 불가 → GCP와 혼용 금지 |
| 좌표·단위 | 수평 CRS, 수직 기준, 축 순서, 단위 명시 | 0m 가정·임의 CRS 부여 금지 |
| 권한 | 유적 자료 반출·사용 승인 | 미승인 시 외부 처리 금지 |

- 자료가 오면 `data/schemas/` 스키마로 형식을 검사하고, `archphoto.preflight.preflight_control`로
  GCP/검증점 분리·좌표·단위를 확인한 뒤 §2 런북으로 기준선을 재개한다. 원자료는 덮어쓰지 않고
  `project.manifest`에 해시를 남긴다.
- 이때 확정해야 할 미확정 항목: 좌표계·높이 기준, 대상별 허용오차(05 §9).
