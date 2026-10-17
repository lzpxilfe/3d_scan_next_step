# 엔진 조사 (기준선 후보) — T03

작성일: 2026-10-12. 방식: **읽기 전용 웹 조사**. 설치·다운로드·실행·외부 업로드 없음.
목적: 기준선 사진실측 엔진 후보의 **출처·라이선스·Apache-2.0 호환성·GCP 지원**을 조사해
[엔진 경계](../src/archphoto/engines/base.py) 설계와 [라이선스 결정](DECISIONS.md)의 근거를 모은다.

> **표기:** `확인` = 공식 저장소 LICENSE 원문/공식 문서에서 직접 확인(출처·일자 병기).
> `미확인` = 추가 확인 필요. 추정을 확인으로 표시하지 않는다. 성능·정확도는 이 문서에서
> 검증하지 않았다(실행 전).

## 1. 요약표

| 엔진 | 주 라이선스(확인) | Apache-2.0 호환(번들 기준) | GCP 지원(확인) | 출처 |
|---|---|---|---|---|
| COLMAP | BSD-3 (신 BSD, 단 의존성 주의) | 가능(자체 코드는) / 의존성에 따라 변동 가능 | 카메라 중심 정합(`model_aligner`) 위주. 이미지 GCP BA는 미확정 | github.com/colmap/colmap |
| OpenDroneMap (ODM) | **AGPL-3.0** | **불가(병합 시 AGPL 전파)** | 있음(`gcp_list.txt`, `--gcp`) | github.com/OpenDroneMap/ODM |
| AliceVision | MPL-2.0 (혼합, 다수 서드파티) | 조건부(파일 단위 copyleft + CUDA 등) | 미확인 | github.com/alicevision/AliceVision |
| Meshroom | MPL-2.0 (Qt/PySide6 LGPL-3.0 포함) | 조건부 | 미확인 | github.com/alicevision/Meshroom |

Apache-2.0은 BSD/MIT와 호환되지만 **AGPL과는 병합·배포 호환이 성립하지 않는다.**
MPL-2.0은 파일 단위 약한 copyleft라 조건부 결합이 가능하나 의무가 붙는다.

## 2. 후보별 상세

### 2.1 COLMAP — 기준선 SfM/MVS 후보
- 출처: https://github.com/colmap/colmap (`main`)
- **라이선스(확인, LICENSE 원문 2026-10-12):** "The COLMAP library is licensed under the
  new BSD license." → BSD-3-Clause 성격. 저작권 ETH Zurich·UNC Chapel Hill·COLMAP Contributors.
- **중요 주의(원문 그대로):** 이 텍스트는 COLMAP 자체 라이선스이며 **의존성은 별도 라이선스**.
  "Building COLMAP with these dependencies may affect the resulting COLMAP license."
  → CGAL(GPL/상용 이중) 등을 링크하면 결과물 라이선스가 달라질 수 있다. 의존성 라이선스는
  **별도 확인 필요 [O]**.
- GitHub SPDX 자동 판정: `NOASSERTION`(커스텀 BSD 문구 탓). **원문이 우선한다.**
- **GCP 지원(확인, 공식 FAQ·이슈):** `model_aligner`로 **카메라 중심 3D 좌표**(GPS 또는
  직교좌표, 최소 3개 이미지, RANSAC 유사변환)에 정합. 공식 FAQ가 이 경로를 문서화.
  (https://colmap.github.io/legacy/4.0/faq.html)
  - 잇슈 #593는 "GCP bundle adjustment 구현됨(commit c3679e1)"으로 닫혔으나, 이후 "main에
    병합됐는지 못 찾겠다"는 반론이 있어 **이미지 기반 GCP BA의 본 포함 여부는 미확인 [O]**.
  - 잇슈 #767(2019)에선 관리자가 GCP 기능을 즉시 구현할 계획이 없다고 답변, 외부 도구
    (github.com/lcmrl/COLMAP_GroundControlPoints) 언급.
  - **시사점:** 고고학의 전통적 GCP(사진상 픽셀 ↔ 지상 좌표)를 직접 쓰려면 COLMAP 단독보다
    외부 도구/추가 작업이 필요할 수 있음. 카메라 위치 측량자료가 있으면 정합 가능.

### 2.2 OpenDroneMap (ODM) — 풀 파이프라인 + GCP 후보
- 출처: https://github.com/OpenDroneMap/ODM (`master`)
- **라이선스(확인, LICENSE 원문 2026-10-12):** GNU **AGPL v3.0**. GitHub SPDX `AGPL-3.0`로도 확인.
- **Apache-2.0 호환성:** AGPL-3.0은 네트워크 사용까지 전파되는 강한 copyleft. **Apache-2.0
  코드와 병합·단일작품 배포 시 호환 불가.** 함께 배포하려면 결합 전체가 AGPL이 되어야 한다.
  → Apache-2.0 프로젝트에서 ODM을 **번들하지 않고 외부 프로세스/별개 배포물로 호출**하는
  구조로만 가능하며, 이조차 결합 여부 판단이 필요하다 **[O]**.
- **GCP 지원(확인, 공식 문서 https://docs.opendronemap.org/gcp/):** `gcp_list.txt` 자동 감지
  또는 `--gcp`. 형식: `EPSG:`(또는 proj4) + `geo_x geo_y geo_z im_x im_y image_name [gcp_name]`.
  권장 최소 5점×3이미지. WebODM에 GCP 배치 UI(POSM GCPi) 제공. `--use-exif`, `--force-gps` 옵션.
  → **이미지 픽셀 ↔ 지상 좌표 GCP를 원활히 지원**해 고고학 워크플로에 부합.

### 2.3 AliceVision — MPL-2.0 혼합 코드베이스
- 출처: https://github.com/alicevision/AliceVision (`develop`)
- **라이선스(확인, COPYING.md 원문 2026-10-12):** "AliceVision is licensed under the MPL2 license."
  단, 다수 서드파티 컴포넌트가 각기 다른 라이선스(MPL2·BSD·MIT·Boost·EPL·CDDL 등).
- **주의(원문 확인):** 깊이맵 계산에 **CUDA(독점 EULA)** 필요, cxsparse(LGPL), Popsift(SIFT 특허
  고지) 등. → 상업/배포 시 CUDA EULA·특허 검토 필요 **[O]**.
- GitHub SPDX: `NOASSERTION`(혼합). 원문이 우선.
- **Apache-2.0 호환성:** MPL-2.0은 파일 단위 약한 copyleft → Apache-2.0과 조건부 결합 가능하나
  MPL 파일에 대한 소스 제공 의무, 그리고 혼입된 각 서드파티 라이선스 준수가 필요. 단순 호환이 아님.

### 2.4 Meshroom — AliceVision 기반 GUI
- 출처: https://github.com/alicevision/Meshroom (`develop`)
- **라이선스(확인, COPYING.md 원문 2026-10-12):** MPL-2.0. 서드파티: AliceVision(MPL2),
  Python(PSF), **Qt/PySide6(LGPL-3.0)**, QtAliceVision(MPL2).
- **Apache-2.0 호환성:** MPL-2.0 + LGPL-3.0(Qt) 혼합. LGPL은 동적 링크·재링크 권리 등 의무 부과.
  GUI 툴킷 선택 시 중요한 참고자료.

## 3. Apache-2.0 배포 관점 정리 [D]

- **번들에 넣기 가장 안전한 후보:** COLMAP(자체 BSD) — 단, **빌드 의존성 라이선스를 먼저 확인**.
- **번들에 넣기 어려운 후보:** ODM(AGPL) — Apache-2.0과 병합 배포 시 AGPL 전파. 별도 호출로
  우회하더라도 결합 판단 필요.
- **조건부 후보:** AliceVision/Meshroom(MPL-2.0 + CUDA·LGPL) — 파일 단위 의무·독점 의존성 검토.
- **시사점:** "Apache-2.0 배포 + 기준선 엔진"을 동시에 이루려면 **엔진을 외부 의존(별도 설치/호출)**
  으로 두고 본체는 Apache-2.0으로 유지하는 구조가 가장 현실적이다. 이는 설계 결정이며 최종 확정 전이다.

## 4. 미확인 항목 [O] (다음 확인이 필요한 것)

| 항목 | 왜 미확인인지 | 확인 방법 |
|---|---|---|
| COLMAP 빌드 의존성 라이선스(CGAL·Ceres·Boost 등) | 원문에 "의존성에 따라 결과 라이선스 변동" 명시 | 실제로 쓸 빌드 구성의 각 라이선스 확인 |
| COLMAP 이미지 GCP BA가 main에 포함됐는지 | 잇슈 #593 반론 존재 | 해당 commit의 현재 main 포함 여부·문서 확인 |
| AliceVision/Meshroom CUDA·LGPL·특허(Popsift) 의무 | 혼합 라이선스·독점 의존성 | 배포 형태별 의무 검토 |
| 각 엔진 확정 버전 | 이 문서는 라이선스 유형만 확인 | 사용할 버전을 고정해 라이선스 재확인 |
| GCP 성능·정확도 | 이번엔 실행 안 함 | 작은 자료 기준선(T06)에서 실측 |
| 학습형 가중치 라이선스 | 아직 후보 미선정 | 후보 선정 후 개별 확인 |

## 5. 관련 결정

- [D-2026-10-12-04](DECISIONS.md): Apache-2.0 방향 — 본 조사 결과 **ODM(AGPL)은 번들 호환 불가,
  COLMAP은 의존성 확인 후 가능**. 배포 구조(외부 엔진 호출)를 검토 근거로 반영.
- 엔진 경계 설계: [engines/base.py](../src/archphoto/engines/base.py)의 `EngineInfo.license_verified`
  는 본 확인 전까지 `False` 유지.
