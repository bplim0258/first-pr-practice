"""출퇴근 경로 비교: 버스(환승 없음) vs 지하철(환승) 중 어느 쪽이 빠른지 판단한다.

두 가지 방법을 제공한다.

1. estimate: 구간별 예상 시간(도보, 배차간격, 탑승)을 넣어 총 소요시간을 추정
2. log / compare: 매일 실제로 걸린 시간을 기록하고, 쌓인 기록으로 평균·편차를 비교
"""

import argparse
import csv
import json
import os
import statistics
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

DEFAULT_LOG = Path("commute_log.csv")
LOG_FIELDS = ["date", "direction", "route", "minutes"]

# 경기도 버스정보 API (공공데이터포털). 키는 환경변수 DATA_GO_KR_KEY 로 넣는다.
GBIS_BASE = "https://apis.data.go.kr/6410000"
API_KEY_ENV = "DATA_GO_KR_KEY"


def parse_legs(spec):
    """'walk=5,every=10,ride=30' 같은 구간 문자열을 (종류, 분) 리스트로 바꾼다.

    - walk: 도보 시간
    - wait: 예상 대기 시간
    - every: 배차간격 (예상 대기 시간은 배차간격의 절반으로 계산)
    - ride: 탑승 시간
    """
    legs = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        kind, sep, value = part.partition("=")
        kind = kind.strip()
        if not sep or kind not in ("walk", "wait", "every", "ride"):
            raise ValueError(f"잘못된 구간: {part!r} (walk/wait/every/ride=분 형식)")
        minutes = float(value)
        if minutes < 0:
            raise ValueError(f"시간은 음수일 수 없음: {part!r}")
        legs.append((kind, minutes))
    if not legs:
        raise ValueError("구간이 비어 있음")
    return legs


def estimate_minutes(legs):
    """구간 리스트의 예상 총 소요시간(분)."""
    total = 0.0
    for kind, minutes in legs:
        total += minutes / 2 if kind == "every" else minutes
    return total


def transfer_count(legs):
    """탑승(ride) 구간 수 - 1 = 환승 횟수."""
    rides = sum(1 for kind, _ in legs if kind == "ride")
    return max(rides - 1, 0)


def summarize(samples):
    """소요시간 표본의 통계: 건수, 평균, 중앙값, 90퍼센타일(늦은 날 기준)."""
    ordered = sorted(samples)
    n = len(ordered)
    p90_index = min(n - 1, max(0, round(0.9 * (n - 1))))
    return {
        "n": n,
        "mean": statistics.fmean(ordered),
        "median": statistics.median(ordered),
        "p90": ordered[p90_index],
    }


def default_direction(now=None):
    now = now or datetime.now()
    return "출근" if now.hour < 12 else "퇴근"


def append_log(path, route, minutes, direction, date):
    path = Path(path)
    new_file = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=LOG_FIELDS)
        if new_file:
            writer.writeheader()
        writer.writerow(
            {"date": date, "direction": direction, "route": route, "minutes": minutes}
        )


def read_log(path, direction=None):
    """기록을 {경로: [분, ...]} 으로 읽는다. direction 이 주어지면 그 방향만."""
    by_route = {}
    path = Path(path)
    if not path.exists():
        return by_route
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if direction and row["direction"] != direction:
                continue
            by_route.setdefault(row["route"], []).append(float(row["minutes"]))
    return by_route


def _subject(word):
    """한글 받침에 맞춰 '이/가' 조사를 붙인다."""
    last = word[-1]
    if "가" <= last <= "힣" and (ord(last) - ord("가")) % 28:
        return word + "이"
    return word + "가"


def recommend(stats):
    """경로별 통계로 추천 문장을 만든다. 평균이 빠른 쪽을 추천하고,
    늦은 날(p90)에는 다른 경로가 유리하면 함께 알려준다."""
    if len(stats) < 2:
        return "비교하려면 두 경로 이상의 기록이 필요합니다."
    by_mean = sorted(stats, key=lambda r: stats[r]["mean"])
    best, second = by_mean[0], by_mean[1]
    diff = stats[second]["mean"] - stats[best]["mean"]
    if diff < 1:
        msg = f"평균 차이가 1분 미만으로 비슷합니다 ({best} ≈ {second})."
    else:
        msg = f"평균적으로 {_subject(best)} {diff:.1f}분 빠릅니다."
    safest = min(stats, key=lambda r: stats[r]["p90"])
    if safest != best:
        msg += (
            f" 다만 늦는 날(90퍼센타일)에는 {_subject(safest)} 더 안정적입니다"
            f" ({stats[safest]['p90']:.0f}분 vs {stats[best]['p90']:.0f}분)."
            " 지각하면 안 되는 날엔 이쪽을 고려하세요."
        )
    if min(s["n"] for s in stats.values()) < 5:
        msg += " (기록이 경로당 5회 미만이라 아직 참고용입니다.)"
    return msg


def _gbis_get(path, params):
    key = os.environ.get(API_KEY_ENV)
    if not key:
        raise ValueError(f"환경변수 {API_KEY_ENV} 에 공공데이터포털 API 키를 넣어주세요.")
    query = urllib.parse.urlencode({"serviceKey": key, "format": "json", **params})
    with urllib.request.urlopen(f"{GBIS_BASE}/{path}?{query}", timeout=10) as resp:
        return json.load(resp)


def _as_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def parse_stations(data):
    """정류소 검색 응답 → [(정류소ID, 이름, 정류소번호), ...]"""
    body = data.get("response", {}).get("msgBody") or {}
    return [
        (str(s.get("stationId")), s.get("stationName"), str(s.get("mobileNo", "")).strip())
        for s in _as_list(body.get("busStationList"))
    ]


def parse_arrivals(data):
    """도착정보 응답 → {노선이름: [첫번째 버스 분, 두번째 버스 분]} (정보 없는 버스는 제외)"""
    body = data.get("response", {}).get("msgBody") or {}
    arrivals = {}
    for bus in _as_list(body.get("busArrivalList")):
        name = str(bus.get("routeName") or bus.get("routeId"))
        times = []
        for key in ("predictTime1", "predictTime2"):
            value = bus.get(key)
            if value not in (None, ""):
                times.append(int(value))
        arrivals[name] = times
    return arrivals


def decide(arrivals, routes, walk, max_wait):
    """정류장까지 걸어가서 탈 수 있는 버스 중 가장 빨리 오는 것을 고르고,
    기다리는 시간이 max_wait 분 이하면 버스, 아니면 지하철을 추천한다."""
    catchable = [
        (minutes, route)
        for route in routes
        for minutes in arrivals.get(route, [])
        if minutes >= walk
    ]
    if not catchable:
        return "지하철", None, None
    minutes, route = min(catchable)
    wait = minutes - walk
    return ("버스" if wait <= max_wait else "지하철"), route, minutes


def cmd_station(args):
    stations = parse_stations(
        _gbis_get("busstationservice/v2/getBusStationListv2", {"keyword": args.keyword})
    )
    if not stations:
        print("정류소를 찾지 못했습니다.")
    for station_id, name, mobile_no in stations:
        print(f"{station_id}  {name}  (정류소번호 {mobile_no})")


def cmd_now(args):
    arrivals = parse_arrivals(
        _gbis_get("busarrivalservice/v2/getBusArrivalListv2", {"stationId": args.station})
    )
    for route in args.routes:
        times = arrivals.get(route)
        shown = ", ".join(f"{m}분" for m in times) if times else "도착정보 없음"
        print(f"{route}번: {shown}")
    choice, route, minutes = decide(arrivals, args.routes, args.walk, args.max_wait)
    if route is None:
        print("→ 지금 탈 수 있는 버스가 없습니다. 지하철을 타세요.")
    elif choice == "버스":
        print(f"→ {route}번 버스를 타세요. {minutes}분 후 도착 (지금 나가면 {minutes - args.walk}분 대기).")
    else:
        print(f"→ 가장 빠른 버스({route}번)도 {minutes}분 후라 지하철이 낫습니다.")


def cmd_estimate(args):
    routes = {"버스": parse_legs(args.bus), "지하철": parse_legs(args.subway)}
    totals = {}
    for name, legs in routes.items():
        totals[name] = estimate_minutes(legs)
        print(f"{name}: 약 {totals[name]:.1f}분 (환승 {transfer_count(legs)}회)")
    fast, slow = sorted(totals, key=totals.get)
    diff = totals[slow] - totals[fast]
    if diff < 1:
        print("→ 예상 시간이 거의 같습니다. 실제 기록(log)으로 비교해 보세요.")
    else:
        print(f"→ 예상으로는 {_subject(fast)} {diff:.1f}분 빠릅니다.")


def cmd_log(args):
    direction = args.direction or default_direction()
    date = args.date or datetime.now().strftime("%Y-%m-%d")
    append_log(args.file, args.route, args.minutes, direction, date)
    print(f"기록함: {date} {direction} {args.route} {args.minutes:g}분")


def cmd_compare(args):
    by_route = read_log(args.file, args.direction)
    if not by_route:
        print("기록이 없습니다. 먼저 'log' 명령으로 소요시간을 기록하세요.")
        return
    stats = {route: summarize(samples) for route, samples in by_route.items()}
    label = args.direction or "전체"
    print(f"[{label}]")
    for route, s in sorted(stats.items(), key=lambda kv: kv[1]["mean"]):
        print(
            f"{route}: {s['n']}회, 평균 {s['mean']:.1f}분, "
            f"중앙값 {s['median']:.1f}분, 늦은 날(p90) {s['p90']:.0f}분"
        )
    print("→ " + recommend(stats))


def build_parser():
    parser = argparse.ArgumentParser(description="버스 vs 지하철 출퇴근 시간 비교")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("estimate", help="구간별 예상 시간으로 비교")
    p.add_argument("--bus", required=True, help="예: walk=5,every=12,ride=35,walk=3")
    p.add_argument(
        "--subway",
        required=True,
        help="예: walk=8,every=5,ride=12,walk=4,every=6,ride=10,walk=5",
    )
    p.set_defaults(func=cmd_estimate)

    p = sub.add_parser("station", help="정류소 이름으로 정류소ID 찾기")
    p.add_argument("keyword", help="예: 신흥역")
    p.set_defaults(func=cmd_station)

    p = sub.add_parser("now", help="실시간 도착정보로 지금 버스/지하철 중 뭘 탈지 추천")
    p.add_argument("--station", required=True, help="정류소ID ('station' 명령으로 확인)")
    p.add_argument("--routes", nargs="+", default=["330", "340"], help="직통 버스 노선")
    p.add_argument("--walk", type=int, default=3, help="정류장까지 걸어가는 시간(분)")
    p.add_argument("--max-wait", type=int, default=10, help="이보다 오래 기다려야 하면 지하철")
    p.set_defaults(func=cmd_now)

    p = sub.add_parser("log", help="실제 소요시간 기록")
    p.add_argument("route", help="경로 이름 (예: 버스, 지하철)")
    p.add_argument("minutes", type=float, help="문 앞에서 문 앞까지 걸린 시간(분)")
    p.add_argument("--direction", choices=["출근", "퇴근"], help="기본: 오전=출근, 오후=퇴근")
    p.add_argument("--date", help="YYYY-MM-DD (기본: 오늘)")
    p.add_argument("--file", default=DEFAULT_LOG, help="기록 파일 경로")
    p.set_defaults(func=cmd_log)

    p = sub.add_parser("compare", help="기록된 소요시간으로 비교")
    p.add_argument("--direction", choices=["출근", "퇴근"], help="해당 방향만 비교")
    p.add_argument("--file", default=DEFAULT_LOG, help="기록 파일 경로")
    p.set_defaults(func=cmd_compare)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except (ValueError, OSError) as e:
        print(f"오류: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
