import pytest

from commute import (
    append_log,
    estimate_minutes,
    parse_legs,
    read_log,
    recommend,
    summarize,
    transfer_count,
)


def test_estimate_uses_half_headway_as_wait():
    legs = parse_legs("walk=5,every=10,ride=30,walk=3")
    assert estimate_minutes(legs) == 5 + 5 + 30 + 3


def test_transfer_count():
    assert transfer_count(parse_legs("walk=5,ride=30")) == 0
    assert transfer_count(parse_legs("walk=5,ride=10,walk=3,wait=2,ride=12")) == 1


def test_parse_legs_rejects_bad_input():
    with pytest.raises(ValueError):
        parse_legs("fly=10")
    with pytest.raises(ValueError):
        parse_legs("walk=-1")
    with pytest.raises(ValueError):
        parse_legs("")


def test_summarize():
    s = summarize([40, 42, 44, 46, 60])
    assert s["n"] == 5
    assert s["mean"] == 46.4
    assert s["median"] == 44
    assert s["p90"] == 60


def test_log_roundtrip_filters_direction(tmp_path):
    log = tmp_path / "log.csv"
    append_log(log, "버스", 45, "출근", "2026-10-01")
    append_log(log, "지하철", 40, "출근", "2026-10-01")
    append_log(log, "버스", 55, "퇴근", "2026-10-01")
    assert read_log(log) == {"버스": [45.0, 55.0], "지하철": [40.0]}
    assert read_log(log, "출근") == {"버스": [45.0], "지하철": [40.0]}


def test_recommend_flags_less_reliable_faster_route():
    stats = {
        "버스": summarize([33, 34, 35, 36, 65]),  # 평균은 빠르지만 막히는 날이 있음
        "지하철": summarize([42, 42, 43, 43, 44]),
    }
    msg = recommend(stats)
    assert "평균적으로 버스가" in msg
    assert "지하철이 더 안정적" in msg


def test_recommend_needs_two_routes():
    assert "두 경로" in recommend({"버스": summarize([40])})


def test_parse_arrivals_and_decide():
    from commute import decide, parse_arrivals

    data = {"response": {"msgBody": {"busArrivalList": [
        {"routeName": "330", "predictTime1": 2, "predictTime2": 12},
        {"routeName": "340", "predictTime1": 7, "predictTime2": ""},
        {"routeName": "8", "predictTime1": 1},
    ]}}}
    arrivals = parse_arrivals(data)
    assert arrivals["330"] == [2, 12]
    assert arrivals["340"] == [7]
    # 330번 2분 후는 걸어가는 3분 안에 못 탐 → 340번 7분 후 (대기 4분)
    assert decide(arrivals, ["330", "340"], walk=3, max_wait=10) == ("버스", "340", 7)
    assert decide(arrivals, ["330", "340"], walk=3, max_wait=3) == ("지하철", "340", 7)
    assert decide({}, ["330", "340"], walk=3, max_wait=10) == ("지하철", None, None)


def test_parse_stations_single_item():
    from commute import parse_stations

    data = {"response": {"msgBody": {"busStationList": {
        "stationId": 206000123, "stationName": "신흥역.종합시장", "mobileNo": " 06123"}}}}
    assert parse_stations(data) == [("206000123", "신흥역.종합시장", "06123")]
