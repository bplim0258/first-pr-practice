# First PR Practice

A tiny calculator library, used to receive pull requests for practice.

## Usage

```python
from calculator import add, subtract

add(2, 3)       # 5
subtract(5, 2)  # 3
```

## Running tests

```bash
python -m pytest
```

## 출퇴근 경로 비교 (`commute.py`)

버스(환승 없음)와 지하철(환승) 중 어느 쪽이 빠른지 판단하는 도구입니다.

### 1) 예상 시간으로 비교

구간을 `walk`(도보), `every`(배차간격 — 대기는 절반으로 계산), `wait`(대기), `ride`(탑승) 분 단위로 적습니다.

```bash
python commute.py estimate \
  --bus    "walk=5,every=12,ride=35,walk=3" \
  --subway "walk=8,every=5,ride=12,walk=4,every=6,ride=10,walk=5"
```

### 2) 실제 기록으로 비교 (추천)

매일 문 앞에서 문 앞까지 걸린 시간을 기록하고 비교합니다. 오전은 출근, 오후는 퇴근으로 자동 분류됩니다.

```bash
python commute.py log 버스 42
python commute.py log 지하철 39 --direction 퇴근
python commute.py compare --direction 출근
```

평균이 빠른 경로를 추천하고, 막히는 날(90퍼센타일) 기준으로 더 안정적인 경로가 다르면 함께 알려줍니다.

### 3) 실시간 도착정보로 지금 뭘 탈지 추천

공공데이터포털(data.go.kr)의 경기도 버스 API 키가 필요합니다.

```bash
export DATA_GO_KR_KEY="발급받은 일반 인증키(Decoding)"
python commute.py station 신흥역          # 정류소ID 찾기
python commute.py now --station <정류소ID> # 330·340번 도착시간 보고 버스/지하철 추천
```

정류장까지 걸어가는 시간(`--walk`, 기본 3분)보다 먼저 오는 버스는 제외하고, 기다리는 시간이 `--max-wait`(기본 10분)를 넘으면 지하철을 추천합니다.
