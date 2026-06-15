import argparse
import json
import os
import re
import ssl
import urllib.parse
import urllib.request
import time
from datetime import datetime

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


SOURCE_URL = os.getenv(
    "SOURCE_URL",
    "https://kt.59itou.com/2/user/12/shop/details/result_xcpmjW.html"
    "?id=54156441&reg_channel_type=kdcode_c&station_uuid=329640eji8qu1m1653302035",
)
STATION_USER_ID = os.getenv("STATION_USER_ID", "54156441")
STATION_UUID = os.getenv("STATION_UUID", "329640eji8qu1m1653302035")

JCZQ_LIST_API = (
    "https://apic.jindianle.com/api/match/selectlist"
    "?platform=koudai_mobile&_prt=https&ver=20180101000000"
    "&hide_more=1&single_support=2"
    f"&station_user_id={STATION_USER_ID}&station_uuid={STATION_UUID}"
)
ZQ14_SCHEDULE_API = (
    "https://apic.jindianle.com/api/zucai/getschedule"
    "?platform=koudai_mobile&_prt=https&ver=20180101000000"
    "&lottery_type=ToTo"
    f"&station_uuid={STATION_UUID}&station_user_id={STATION_USER_ID}"
)

SSL_CONTEXT = ssl._create_unverified_context()

MODULES = {
    "jczq": {
        "module_code": "jczq",
        "module_name": "竞彩足球",
        "list_strategy": "api_jczq",
        "detail_lottery_id": "90",
        "detail_lottery_style": "jczq",
        "page_path": "/jingcai/",
        "page_bsrc2": "jczq",
    },
    "bjdc": {
        "module_code": "bjdc",
        "module_name": "北京单场",
        "list_strategy": "page_dc_like",
        "detail_lottery_id": "45",
        "detail_lottery_style": "dc",
        "page_path": "/danchang/",
        "page_bsrc2": "dc",
        "primary_play_name": "胜平负",
        "filter_sport_name": "足球",
    },
    "zq14": {
        "module_code": "zq14",
        "module_name": "足球14场",
        "list_strategy": "api_zq14",
        "allow_empty_list": True,
        "detail_lottery_id": "10",
        "detail_lottery_style": "zc",
        "page_path": "/zucai/",
        "page_bsrc2": "",
    },
    "sfgg": {
        "module_code": "sfgg",
        "module_name": "胜负过关",
        "list_strategy": "page_dc_like",
        "detail_lottery_id": "45",
        "detail_lottery_style": "dc",
        "page_path": "/danchang/guoguan/",
        "page_bsrc2": "wl",
        "primary_play_name": "胜负",
        "filter_sport_name": "足球",
    },
}

PAGE_STATE_EVAL = """
() => {
  const seen = new Set();
  const vms = Array.from(document.querySelectorAll('*'))
    .map((el) => el.__vue__)
    .filter((vm) => {
      if (!vm || seen.has(vm)) {
        return false;
      }
      seen.add(vm);
      return true;
    });
  const target =
    vms.find((vm) => vm && vm._data && vm._data.info && vm._data.info.matchs) ||
    vms.find((vm) => vm && vm._data && vm._data.info && Array.isArray(vm._data.info.list)) ||
    vms.find((vm) => vm && vm._data && vm._data.info && typeof vm._data.info === 'object');
  if (!target) {
    return null;
  }
  return JSON.parse(
    JSON.stringify({
      component_name:
        (target.$options && (target.$options.name || target.$options._componentTag)) || '',
      data: target._data || {},
    })
  );
}
"""


def fetch_json(url, method="GET", data=None, headers=None):
    req_headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://kt.59itou.com/",
    }
    if headers:
        req_headers.update(headers)
    payload = None
    if data is not None:
        if isinstance(data, dict):
            payload = urllib.parse.urlencode(data).encode("utf-8")
            req_headers.setdefault(
                "Content-Type", "application/x-www-form-urlencoded; charset=UTF-8"
            )
        elif isinstance(data, str):
            payload = data.encode("utf-8")
        else:
            payload = data
    last_error = None
    for attempt in range(3):
        req = urllib.request.Request(url, data=payload, headers=req_headers, method=method)
        try:
            with urllib.request.urlopen(req, context=SSL_CONTEXT, timeout=60) as resp:
                body = resp.read().decode("utf-8", "ignore")
            return json.loads(body)
        except Exception as exc:
            last_error = exc
            if attempt == 2:
                raise
            time.sleep(1.5 * (attempt + 1))
    raise last_error


def stringify(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def norm_text(text):
    return re.sub(r"[ \t\r\f\v]+", " ", (text or "")).strip()


def split_lines(text):
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


INVALID_DETAIL_MARKERS = (
    "参数错误",
    "参数错误1",
    "网络错误，请稍后再试",
    "undefined",
)


def has_invalid_detail_marker(text):
    normalized = stringify(text)
    if not normalized:
        return False
    return any(marker in normalized for marker in INVALID_DETAIL_MARKERS)


def has_meaningful_detail_text(text):
    normalized = stringify(text)
    if not normalized or has_invalid_detail_marker(normalized):
        return False
    return len(split_lines(normalized)) >= 4


def has_meaningful_api_payload(raw_text):
    if not stringify(raw_text) or has_invalid_detail_marker(raw_text):
        return False
    payload = parse_json_text(raw_text)
    if not payload:
        return False
    if isinstance(payload, dict):
        if payload.get("code") not in (None, 0, "0", 200, "200"):
            return False
        data = payload.get("data")
        if data is None:
            return bool(payload)
        if isinstance(data, dict):
            return any(value not in (None, "", [], {}) for value in data.values())
        if isinstance(data, list):
            return len(data) > 0
        return bool(data)
    if isinstance(payload, list):
        return len(payload) > 0
    return bool(payload)


def has_meaningful_api_payload_list(raw_values):
    for item in raw_values or []:
        if has_meaningful_api_payload(item):
            return True
    return False


def detail_capture_is_usable(detail, refresh_mode):
    wants_fast = refresh_mode in {"full", "fast"}
    wants_slow = refresh_mode in {"full", "slow"}
    if wants_slow:
        if any(
            has_meaningful_detail_text(detail.get(field))
            for field in ("history_dom_text", "strength_detail_dom_text", "lineup_dom_text")
        ):
            return True
        if any(
            has_meaningful_api_payload(detail.get(field))
            for field in ("history_api_raw", "base_api_raw", "lineup_api_raw")
        ):
            return True
    if wants_fast:
        if any(has_meaningful_detail_text(detail.get(field)) for field in ("europe_dom_text", "asia_dom_text")):
            return True
        if has_meaningful_api_payload_list(detail.get("europe_list_api_raw")):
            return True
        if has_meaningful_api_payload_list(detail.get("europe_stats_api_raw")):
            return True
        if has_meaningful_api_payload_list(detail.get("asia_list_api_raw")):
            return True
        if has_meaningful_api_payload_list(detail.get("asia_stats_api_raw")):
            return True
    return False


def slice_between(lines, start_key, end_key=None, start_offset=1):
    try:
        start = lines.index(start_key) + start_offset
    except ValueError:
        return []
    if end_key:
        try:
            end = lines.index(end_key, start)
        except ValueError:
            end = len(lines)
    else:
        end = len(lines)
    return lines[start:end]


def slice_between_any(lines, start_key, end_keys=None, start_offset=1):
    try:
        start = lines.index(start_key) + start_offset
    except ValueError:
        return []
    end = len(lines)
    for candidate in end_keys or []:
        try:
            idx = lines.index(candidate, start)
        except ValueError:
            continue
        end = min(end, idx)
    return lines[start:end]


def trim_trailing_keywords(lines, stop_keywords):
    if not lines:
        return []
    end = len(lines)
    for idx, line in enumerate(lines):
        if line in stop_keywords:
            end = idx
            break
    return lines[:end]


def extract_strength_compare_sections(strength_lines):
    scene_control = trim_trailing_keywords(
        slice_between_any(strength_lines, "场面控制", ["攻防特征", "角球和犯规", "半全场", "投诉/反馈"], 0),
        ["投诉/反馈"],
    )
    attack_defense = trim_trailing_keywords(
        slice_between_any(strength_lines, "攻防特征", ["角球和犯规", "半全场", "投诉/反馈"], 0),
        ["投诉/反馈"],
    )
    corner_foul = trim_trailing_keywords(
        slice_between_any(strength_lines, "角球和犯规", ["半全场", "投诉/反馈"], 0),
        ["投诉/反馈"],
    )
    half_full = trim_trailing_keywords(
        slice_between_any(strength_lines, "半全场", ["投诉/反馈"], 0),
        ["投诉/反馈"],
    )
    return {
        "scene_control": scene_control,
        "attack_defense": attack_defense,
        "corner_foul": corner_foul,
        "half_full": half_full,
    }


def find_line(lines, keyword):
    for line in lines:
        if keyword in line:
            return line
    return ""


def trim_before_keywords(lines, stop_keywords):
    for i, line in enumerate(lines):
        if line in stop_keywords:
            return lines[:i]
    return lines


def trim_after_keywords(lines, stop_keywords):
    for i, line in enumerate(lines):
        if line in stop_keywords:
            return lines[:i]
    return lines


def find_sequence_start(lines, sequence):
    if not lines or not sequence:
        return -1
    size = len(sequence)
    for i in range(len(lines) - size + 1):
        if lines[i : i + size] == sequence:
            return i
    return -1


def extract_swipe_analysis(lines, tab_sequence, table_title, start_markers=None):
    start = 0
    if start_markers:
        for marker in start_markers:
            if marker in lines:
                start = lines.index(marker)
                break
    elif "查看全部" in lines:
        start = lines.index("查看全部") + 1
    end = find_sequence_start(lines, tab_sequence)
    if end == -1 and table_title in lines:
        end = lines.index(table_title)
    if end == -1:
        end = len(lines)
    block = lines[start:end]
    return trim_after_keywords(block, ["投诉/反馈", "参数错误1", "参数错误"])


def parse_odds_table(lines, title, end_keywords=None, skip_lines=None):
    if title not in lines:
        return {"title": title, "rows": []}
    start = lines.index(title) + 1
    block = lines[start:]
    block = trim_after_keywords(block, end_keywords or ["投诉/反馈", "参数错误1"])
    block = [line for line in block if line not in (skip_lines or [])]

    rows = []
    row = []
    for line in block:
        if line == ">":
            if row:
                rows.append({"company": row[0], "cells": row[1:]})
                row = []
            continue
        row.append(line)
    if row:
        rows.append({"company": row[0], "cells": row[1:]})
    return {"title": title, "rows": rows}


def parse_json_text(raw_text):
    if not raw_text:
        return {}
    try:
        return json.loads(raw_text)
    except Exception:
        return {}


def build_module_page_url(module_cfg):
    params = {
        "back": SOURCE_URL,
        "scene": "station_lottery",
        "station_id": STATION_USER_ID,
    }
    if module_cfg.get("page_bsrc2"):
        params["bsrc1"] = "select_list"
        params["bsrc2"] = module_cfg["page_bsrc2"]
    return f"https://kt.59itou.com{module_cfg['page_path']}?{urllib.parse.urlencode(params)}"


def build_detail_url(module_cfg, match_id2):
    params = {
        "current_tab": "history",
        "matchid": match_id2,
        "lotteryId": module_cfg["detail_lottery_id"],
        "lottery_style": module_cfg["detail_lottery_style"],
        "station_user_id": STATION_USER_ID,
    }
    return "https://kt.59itou.com/770/match3/?" + urllib.parse.urlencode(params)


def empty_record(module_cfg):
    return {
        "source_url": SOURCE_URL,
        "captured_at": "",
        "issue_no": "",
        "module_code": module_cfg["module_code"],
        "lottery_category": module_cfg["module_name"],
        "sport_name": "",
        "match_id": "",
        "match_id2": "",
        "match_no": "",
        "match_date": "",
        "match_weekday": "",
        "match_time": "",
        "bet_time": "",
        "league_name": "",
        "home_team": "",
        "away_team": "",
        "home_rank_text": "",
        "away_rank_text": "",
        "recommend_count": "",
        "spf_handicap": "",
        "spf_win_odds": "",
        "spf_draw_odds": "",
        "spf_lose_odds": "",
        "rqspf_handicap": "",
        "rqspf_win_odds": "",
        "rqspf_draw_odds": "",
        "rqspf_lose_odds": "",
        "single_support": "",
        "more_play_text": "",
        "primary_play_name": "",
        "primary_boundary": "",
        "primary_options": "",
        "all_plays_raw": "",
        "history_home_summary": "",
        "history_away_summary": "",
        "history_home_recent_list": "",
        "history_away_recent_list": "",
        "history_h2h_list": "",
        "history_home_schedule_list": "",
        "history_away_schedule_list": "",
        "overall_strength_home_score": "",
        "overall_strength_away_score": "",
        "overall_strength_desc": "",
        "strength_overview_title": "",
        "strength_compare_scope": "",
        "strength_compare_scene_control": "",
        "strength_compare_attack_defense": "",
        "strength_compare_corner_foul": "",
        "strength_compare_half_full": "",
        "lineup_overview": "",
        "lineup_tech_compare": "",
        "lineup_last_match_compare": "",
        "lineup_starting_home": "",
        "lineup_starting_away": "",
        "lineup_bench_home": "",
        "lineup_bench_away": "",
        "lineup_injury_home": "",
        "lineup_injury_away": "",
        "europe_index_table": "",
        "europe_analysis_cards": "",
        "asia_handicap_table": "",
        "asia_analysis_cards": "",
        "history_dom_text": "",
        "strength_detail_dom_text": "",
        "lineup_dom_text": "",
        "europe_dom_text": "",
        "asia_dom_text": "",
        "history_api_raw": "",
        "base_api_raw": "",
        "lineup_api_raw": "",
        "europe_list_api_raw": "",
        "europe_stats_api_raw": "",
        "asia_list_api_raw": "",
        "asia_stats_api_raw": "",
        "request_log": "",
        "list_page_url": build_module_page_url(module_cfg),
        "detail_url": "",
        "detail_lottery_id": module_cfg["detail_lottery_id"],
        "detail_lottery_style": module_cfg["detail_lottery_style"],
        "list_item_raw": "",
        "error": "",
    }


LEGACY_MATCH_FIELDS = [
    "source_url",
    "captured_at",
    "issue_no",
    "lottery_category",
    "match_id",
    "match_id2",
    "match_no",
    "match_date",
    "match_weekday",
    "match_time",
    "bet_time",
    "league_name",
    "home_team",
    "away_team",
    "home_rank_text",
    "away_rank_text",
    "recommend_count",
    "spf_handicap",
    "spf_win_odds",
    "spf_draw_odds",
    "spf_lose_odds",
    "rqspf_handicap",
    "rqspf_win_odds",
    "rqspf_draw_odds",
    "rqspf_lose_odds",
    "single_support",
    "more_play_text",
    "history_home_summary",
    "history_away_summary",
    "history_home_recent_list",
    "history_away_recent_list",
    "history_h2h_list",
    "history_home_schedule_list",
    "history_away_schedule_list",
    "overall_strength_home_score",
    "overall_strength_away_score",
    "overall_strength_desc",
    "strength_overview_title",
    "strength_compare_scope",
    "strength_compare_scene_control",
    "strength_compare_attack_defense",
    "strength_compare_corner_foul",
    "strength_compare_half_full",
    "lineup_overview",
    "lineup_tech_compare",
    "lineup_last_match_compare",
    "lineup_starting_home",
    "lineup_starting_away",
    "lineup_bench_home",
    "lineup_bench_away",
    "lineup_injury_home",
    "lineup_injury_away",
    "europe_index_table",
    "europe_analysis_cards",
    "asia_handicap_table",
    "asia_analysis_cards",
    "history_dom_text",
    "strength_detail_dom_text",
    "lineup_dom_text",
    "europe_dom_text",
    "asia_dom_text",
    "history_api_raw",
    "base_api_raw",
    "lineup_api_raw",
    "europe_list_api_raw",
    "europe_stats_api_raw",
    "asia_list_api_raw",
    "asia_stats_api_raw",
    "request_log",
    "error",
]

FAST_DETAIL_FIELDS = {
    "europe_index_table",
    "europe_analysis_cards",
    "asia_handicap_table",
    "asia_analysis_cards",
    "europe_dom_text",
    "asia_dom_text",
    "europe_list_api_raw",
    "europe_stats_api_raw",
    "asia_list_api_raw",
    "asia_stats_api_raw",
    "request_log",
    "error",
}

SLOW_DETAIL_FIELDS = {
    "history_home_summary",
    "history_away_summary",
    "history_home_recent_list",
    "history_away_recent_list",
    "history_h2h_list",
    "history_home_schedule_list",
    "history_away_schedule_list",
    "overall_strength_home_score",
    "overall_strength_away_score",
    "overall_strength_desc",
    "strength_overview_title",
    "strength_compare_scope",
    "strength_compare_scene_control",
    "strength_compare_attack_defense",
    "strength_compare_corner_foul",
    "strength_compare_half_full",
    "lineup_overview",
    "lineup_tech_compare",
    "lineup_last_match_compare",
    "lineup_starting_home",
    "lineup_starting_away",
    "lineup_bench_home",
    "lineup_bench_away",
    "lineup_injury_home",
    "lineup_injury_away",
    "history_dom_text",
    "strength_detail_dom_text",
    "lineup_dom_text",
    "history_api_raw",
    "base_api_raw",
    "lineup_api_raw",
    "request_log",
    "error",
}

FAST_REFRESH_FIELDS = {
    "source_url",
    "captured_at",
    "issue_no",
    "lottery_category",
    "match_id",
    "match_id2",
    "match_no",
    "match_date",
    "match_weekday",
    "match_time",
    "bet_time",
    "league_name",
    "home_team",
    "away_team",
    "home_rank_text",
    "away_rank_text",
    "recommend_count",
    "spf_handicap",
    "spf_win_odds",
    "spf_draw_odds",
    "spf_lose_odds",
    "rqspf_handicap",
    "rqspf_win_odds",
    "rqspf_draw_odds",
    "rqspf_lose_odds",
    "single_support",
    "more_play_text",
    *FAST_DETAIL_FIELDS,
}

SLOW_REFRESH_FIELDS = {
    "source_url",
    "captured_at",
    "issue_no",
    "lottery_category",
    "match_id",
    "match_id2",
    "match_no",
    "match_date",
    "match_weekday",
    "match_time",
    "bet_time",
    "league_name",
    "home_team",
    "away_team",
    "home_rank_text",
    "away_rank_text",
    "recommend_count",
    "spf_handicap",
    "spf_win_odds",
    "spf_draw_odds",
    "spf_lose_odds",
    "rqspf_handicap",
    "rqspf_win_odds",
    "rqspf_draw_odds",
    "rqspf_lose_odds",
    "single_support",
    "more_play_text",
    *SLOW_DETAIL_FIELDS,
}


def make_weekday(date_text):
    try:
        dt = datetime.strptime(date_text, "%Y-%m-%d")
    except Exception:
        return ""
    return "周" + "一二三四五六日"[dt.weekday()]


def wait_for_body_keywords(page, keywords, timeout_ms=6000):
    if not keywords:
        return False
    script = """
    ([needles]) => {
      const text = document.body ? document.body.innerText : '';
      return needles.every((needle) => text.includes(needle));
    }
    """
    try:
        page.wait_for_function(script, [keywords], timeout=timeout_ms)
        return True
    except Exception:
        return False


def click_text_via_js(page, text):
    script = """
    ([target]) => {
      const nodes = Array.from(document.querySelectorAll('*'));
      const exact = nodes.find((el) => (el.innerText || '').trim() === target);
      const fuzzy = nodes.find((el) => (el.innerText || '').includes(target));
      const hit = exact || fuzzy;
      if (!hit) {
        return false;
      }
      hit.click();
      return true;
    }
    """
    try:
        return bool(page.evaluate(script, [text]))
    except Exception:
        return False


def flatten_player_groups(groups):
    players = []
    for group in groups or []:
        for player in group or []:
            if player:
                players.append(player)
    return players


def build_player_lines(players):
    lines = []
    for player in players or []:
        num = stringify(player.get("pNum"))
        name = stringify(player.get("pName"))
        price = stringify(player.get("price"))
        pos = stringify(player.get("pos"))
        if num:
            lines.append(num)
        if name:
            lines.append(name)
        if price:
            lines.append(price)
        elif pos:
            lines.append(pos)
    return lines


def build_starter_lines(team_name, team_price, avg_age, avg_height, players, coach, formation):
    lines = [
        "本场",
        "阵型图",
        "表格",
        "事件",
        "赛季战绩",
        "身价评分",
        "身高年龄",
    ]
    if team_name:
        lines.append(team_name)
    if team_price:
        lines.extend([team_price, "欧", "首发身价"])
    if avg_age:
        lines.extend([avg_age, "岁", "平均年龄"])
    if avg_height:
        lines.extend([avg_height, "cm", "平均身高"])
    lines.extend(build_player_lines(players))
    if coach:
        lines.append(f"教练：{coach}")
    if formation:
        lines.append(f"阵型：{formation}")
    return lines


def build_substitute_lines(team_name, team_price, players):
    lines = []
    if team_name:
        lines.append(team_name)
    if team_price:
        lines.append(f"替补身价：{team_price}欧")
    lines.extend(build_player_lines(players))
    return lines


def build_injury_lines(team_name, players):
    lines = []
    if team_name:
        lines.append(team_name)
    lines.extend(["球员", "状态", "影响"])
    if not players:
        lines.append("暂无数据")
        return lines
    for player in players:
        name = stringify(player.get("pName") or player.get("name"))
        status = stringify(player.get("statusName") or player.get("status"))
        impact = stringify(player.get("effect") or player.get("influence") or player.get("desc"))
        if name:
            lines.append(name)
        if status:
            lines.append(status)
        if impact:
            lines.append(impact)
    return lines


def overwrite_lineup_fields_from_api(record, lineup_api):
    data = (lineup_api or {}).get("data") or {}
    if not data:
        return
    home_name = stringify(data.get("hName")) or record["home_team"]
    away_name = stringify(data.get("aName")) or record["away_team"]
    home_starters = flatten_player_groups(data.get("homeStarter"))
    away_starters = flatten_player_groups(data.get("awayStarter"))
    home_subs = data.get("homeSubstitute") or []
    away_subs = data.get("awaySubstitute") or []
    home_injury = data.get("homeInjury") or []
    away_injury = data.get("awayInjury") or []

    home_starting = build_starter_lines(
        home_name,
        stringify(data.get("homeStarterPrice")),
        stringify(data.get("homeStarterAvgAge") or data.get("homeAvgAge")),
        stringify(data.get("homeStarterAvgHeight") or data.get("homeAvgHeight")),
        home_starters,
        stringify(data.get("homeCoach")),
        stringify(data.get("homeFormation")),
    )
    away_starting = build_starter_lines(
        away_name,
        stringify(data.get("awayStarterPrice")),
        stringify(data.get("awayStarterAvgAge") or data.get("awayAvgAge")),
        stringify(data.get("awayStarterAvgHeight") or data.get("awayAvgHeight")),
        away_starters,
        stringify(data.get("awayCoach")),
        stringify(data.get("awayFormation")),
    )
    home_bench = build_substitute_lines(
        home_name,
        stringify(data.get("homeSubstitutePrice")),
        home_subs,
    )
    away_bench = build_substitute_lines(
        away_name,
        stringify(data.get("awaySubstitutePrice")),
        away_subs,
    )
    home_injury_lines = build_injury_lines(home_name, home_injury)
    away_injury_lines = build_injury_lines(away_name, away_injury)

    record["lineup_starting_home"] = stringify(home_starting)
    record["lineup_starting_away"] = stringify(away_starting)
    record["lineup_bench_home"] = stringify(home_bench)
    record["lineup_bench_away"] = stringify(away_bench)
    record["lineup_injury_home"] = stringify(home_injury_lines)
    record["lineup_injury_away"] = stringify(away_injury_lines)


def flatten_jczq_match_list(module_cfg, payload):
    records = []
    data = payload.get("data") or {}
    for date_key, match_map in data.items():
        for serial_no, item in (match_map or {}).items():
            record = empty_record(module_cfg)
            record["captured_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            record["sport_name"] = "足球"
            record["match_id"] = stringify(item.get("match_id"))
            record["match_id2"] = stringify(item.get("match_id2"))
            record["match_no"] = stringify(item.get("serial_no") or serial_no)
            record["match_date"] = stringify(item.get("bet_date") or date_key)
            record["match_weekday"] = make_weekday(record["match_date"])
            record["match_time"] = stringify(item.get("match_time"))
            record["bet_time"] = stringify(item.get("bet_time"))
            record["league_name"] = norm_text(stringify(item.get("league_name")))
            record["home_team"] = stringify(item.get("host_name_s"))
            record["away_team"] = stringify(item.get("guest_name_s"))
            rank = item.get("rank") or {}
            home_rank = rank.get("1") or {}
            away_rank = rank.get("2") or {}
            record["home_rank_text"] = norm_text(
                f"[{home_rank.get('rank', '')}] {home_rank.get('rank_league', '')}".strip()
            )
            record["away_rank_text"] = norm_text(
                f"[{away_rank.get('rank', '')}] {away_rank.get('rank_league', '')}".strip()
            )
            record["recommend_count"] = stringify(item.get("sort"))
            play_map = item.get("list") or {}
            normal = play_map.get("SportteryNWDL") or {}
            handicap = play_map.get("SportteryWDL") or {}
            record["spf_handicap"] = stringify(normal.get("boundary"))
            record["spf_win_odds"] = stringify((normal.get("odds") or {}).get("3"))
            record["spf_draw_odds"] = stringify((normal.get("odds") or {}).get("1"))
            record["spf_lose_odds"] = stringify((normal.get("odds") or {}).get("0"))
            record["rqspf_handicap"] = stringify(handicap.get("boundary"))
            record["rqspf_win_odds"] = stringify((handicap.get("odds") or {}).get("3"))
            record["rqspf_draw_odds"] = stringify((handicap.get("odds") or {}).get("1"))
            record["rqspf_lose_odds"] = stringify((handicap.get("odds") or {}).get("0"))
            record["single_support"] = (
                "1"
                if stringify(normal.get("is_single")) == "1"
                or stringify(handicap.get("is_single")) == "1"
                else "0"
            )
            record["more_play_text"] = "更多玩法"
            record["primary_play_name"] = "胜平负"
            record["primary_boundary"] = record["spf_handicap"]
            record["primary_options"] = stringify(
                [
                    {"text": "胜", "code": "3", "odds": record["spf_win_odds"]},
                    {"text": "平", "code": "1", "odds": record["spf_draw_odds"]},
                    {"text": "负", "code": "0", "odds": record["spf_lose_odds"]},
                ]
            )
            record["all_plays_raw"] = stringify(play_map)
            record["list_item_raw"] = stringify(item)
            record["detail_url"] = build_detail_url(module_cfg, record["match_id2"])
            records.append(record)
    return records


def build_zq14_selectlist_api(issue_no):
    issue_no = stringify(issue_no)
    return (
        "https://apic.jindianle.com/api/zucai/selectlist"
        "?platform=koudai_mobile&_prt=https&ver=20180101000000"
        f"&lottery_type=ToTo&lottery_no={urllib.parse.quote(issue_no)}"
        f"&station_uuid={STATION_UUID}&station_user_id={STATION_USER_ID}"
    )


def latest_zq14_issue_no(schedule_payload):
    data = schedule_payload.get("data") or {}
    schedule_list = data.get("list") or []
    if not schedule_list:
        return ""
    def sort_key(item):
        lottery_no = stringify((item or {}).get("lottery_no"))
        return int(re.sub(r"\D", "", lottery_no) or "0")
    latest = max(schedule_list, key=sort_key)
    return stringify(latest.get("lottery_no"))


def normalize_zq14_item(module_cfg, item, issue_no=""):
    record = empty_record(module_cfg)
    record["captured_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    record["issue_no"] = stringify(issue_no or item.get("lottery_no"))
    record["sport_name"] = "足球"
    record["match_id"] = stringify(item.get("match_id"))
    record["match_id2"] = stringify(item.get("match_id2"))
    record["match_no"] = stringify(item.get("serial_no"))
    record["match_date"] = stringify(item.get("bet_date"))
    record["match_weekday"] = make_weekday(record["match_date"])
    match_time_text = stringify(item.get("match_time") or item.get("bet_time"))
    record["match_time"] = match_time_text.split(" ", 1)[1][:5] if " " in match_time_text else match_time_text[:5]
    record["bet_time"] = stringify(item.get("bet_time") or item.get("match_time"))
    record["league_name"] = norm_text(stringify(item.get("league_name")))
    record["home_team"] = stringify(item.get("host_name_l") or item.get("host_name_s"))
    record["away_team"] = stringify(item.get("guest_name_l") or item.get("guest_name_s"))
    rank = item.get("rank") or {}
    home_rank = rank.get("1") or {}
    away_rank = rank.get("2") or {}
    record["home_rank_text"] = norm_text(
        f"[{stringify(home_rank.get('rank'))}] {stringify(home_rank.get('rank_league'))}".strip()
    )
    record["away_rank_text"] = norm_text(
        f"[{stringify(away_rank.get('rank'))}] {stringify(away_rank.get('rank_league'))}".strip()
    )
    odds = item.get("odds") or {}
    record["spf_handicap"] = ""
    record["spf_win_odds"] = stringify(odds.get("3"))
    record["spf_draw_odds"] = stringify(odds.get("1"))
    record["spf_lose_odds"] = stringify(odds.get("0"))
    record["rqspf_handicap"] = ""
    record["rqspf_win_odds"] = ""
    record["rqspf_draw_odds"] = ""
    record["rqspf_lose_odds"] = ""
    record["single_support"] = "0"
    record["more_play_text"] = "分析"
    record["primary_play_name"] = "胜平负"
    record["primary_boundary"] = ""
    record["primary_options"] = stringify(
        [
            {"text": "胜", "code": "3", "odds": record["spf_win_odds"]},
            {"text": "平", "code": "1", "odds": record["spf_draw_odds"]},
            {"text": "负", "code": "0", "odds": record["spf_lose_odds"]},
        ]
    )
    record["all_plays_raw"] = stringify({"odds": odds})
    record["list_item_raw"] = stringify(item)
    if record["match_id2"]:
        record["detail_url"] = build_detail_url(module_cfg, record["match_id2"])
    return record


def normalize_dc_item(module_cfg, item, serial_no=None):
    record = empty_record(module_cfg)
    record["captured_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    record["sport_name"] = stringify(item.get("sportName"))
    record["match_id"] = stringify(item.get("betId") or item.get("lotteryNo"))
    record["match_id2"] = stringify(item.get("id"))
    record["match_no"] = stringify(item.get("serialNo") or serial_no)
    record["match_date"] = stringify(item.get("betDate"))
    record["match_weekday"] = make_weekday(record["match_date"])
    record["match_time"] = stringify(item.get("betTime"))
    record["bet_time"] = stringify(item.get("betTimeFull"))
    record["league_name"] = stringify(((item.get("league") or {}).get("name")))
    host = item.get("host") or {}
    guest = item.get("guest") or {}
    record["home_team"] = stringify(host.get("name"))
    record["away_team"] = stringify(guest.get("name"))
    record["home_rank_text"] = norm_text(
        f"[{stringify(host.get('rank'))}] {stringify(host.get('league'))}".strip()
    )
    record["away_rank_text"] = norm_text(
        f"[{stringify(guest.get('rank'))}] {stringify(guest.get('league'))}".strip()
    )
    record["recommend_count"] = stringify(item.get("grcmdNum"))
    record["spf_handicap"] = stringify(item.get("boundary"))
    record["single_support"] = ""
    record["more_play_text"] = "分析"
    opts = item.get("opts") or []
    code_map = {stringify(opt.get("code")): opt for opt in opts}
    record["spf_win_odds"] = stringify((code_map.get("3") or {}).get("odds"))
    record["spf_draw_odds"] = stringify((code_map.get("1") or {}).get("odds"))
    record["spf_lose_odds"] = stringify((code_map.get("0") or {}).get("odds"))
    record["primary_play_name"] = module_cfg.get("primary_play_name", "胜平负")
    record["primary_boundary"] = stringify(item.get("boundary"))
    record["primary_options"] = stringify(opts)
    record["all_plays_raw"] = stringify(item)
    record["list_item_raw"] = stringify(item)
    record["detail_url"] = build_detail_url(module_cfg, record["match_id2"])
    return record


def fetch_page_state(page, module_cfg):
    page.goto(build_module_page_url(module_cfg), wait_until="networkidle", timeout=60000)
    page.wait_for_timeout(1500)
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except PlaywrightTimeoutError:
        pass
    return page.evaluate(PAGE_STATE_EVAL) or {}


def collect_dc_like_records(context, module_cfg):
    page = context.new_page()
    try:
        state = fetch_page_state(page, module_cfg)
    finally:
        page.close()
    vm_data = (state or {}).get("data") or {}
    info = vm_data.get("info") or {}
    matches = info.get("matchs") or {}
    records = []
    for serial_no, item in sorted(
        matches.items(),
        key=lambda pair: (
            int((pair[1] or {}).get("sort") or 999999),
            int(re.sub(r"\D", "", str(pair[0])) or "999999"),
        ),
    ):
        if module_cfg.get("filter_sport_name") and stringify(item.get("sportName")) != module_cfg["filter_sport_name"]:
            continue
        records.append(normalize_dc_item(module_cfg, item, serial_no=serial_no))
    return records


def collect_zq14_records(module_cfg):
    schedule_payload = fetch_json(ZQ14_SCHEDULE_API)
    issue_no = latest_zq14_issue_no(schedule_payload)
    if not issue_no:
        return []
    payload = fetch_json(build_zq14_selectlist_api(issue_no))
    data = payload.get("data") or {}
    match_list = data.get("match_list") or {}
    records = []
    for serial_no, item in sorted(
        match_list.items(),
        key=lambda pair: int(re.sub(r"\D", "", stringify((pair[1] or {}).get("serial_no") or pair[0])) or "999999"),
    ):
        if not isinstance(item, dict):
            continue
        if not stringify(item.get("host_name_l") or item.get("host_name_s")):
            continue
        if not stringify(item.get("guest_name_l") or item.get("guest_name_s")):
            continue
        item = dict(item)
        if not item.get("serial_no"):
            item["serial_no"] = serial_no
        records.append(normalize_zq14_item(module_cfg, item, issue_no=issue_no))
    return records


def load_snapshot_module_records(module_cfg):
    output_dir = "output"
    if not os.path.isdir(output_dir):
        return []
    json_files = [
        os.path.join(output_dir, name)
        for name in os.listdir(output_dir)
        if name.lower().endswith(".json")
    ]
    json_files.sort(key=lambda path: os.path.getmtime(path), reverse=True)
    empty_snapshot_found = False
    for file_path in json_files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception:
            continue
        found_snapshot, matches = extract_snapshot_matches(file_path, payload, module_cfg)
        if not found_snapshot:
            continue
        records = []
        for match in matches:
            record = build_record_from_snapshot_match(module_cfg, match)
            if record:
                records.append(record)
        if records:
            return records
        empty_snapshot_found = True
        if module_cfg.get("allow_empty_list"):
            return []
    if empty_snapshot_found and module_cfg.get("allow_empty_list"):
        return []
    return None


def extract_snapshot_matches(file_path, payload, module_cfg):
    module_code = module_cfg["module_code"]
    if isinstance(payload, dict):
        modules = payload.get("modules") or {}
        if isinstance(modules, dict):
            module_payload = modules.get(module_code) or {}
            if isinstance(module_payload, dict):
                matches = module_payload.get("matches") or []
                if isinstance(matches, list):
                    return True, matches
        if stringify(payload.get("module_code")) == module_code:
            matches = payload.get("matches") or []
            if isinstance(matches, list):
                return True, matches
        if is_module_specific_snapshot_file(file_path, module_cfg):
            matches = payload.get("matches") or []
            if isinstance(matches, list):
                return True, matches
        return False, []
    if isinstance(payload, list) and is_module_specific_snapshot_file(file_path, module_cfg):
        return True, payload
    return False, []


def is_module_specific_snapshot_file(file_path, module_cfg):
    file_name = os.path.basename(file_path).lower()
    module_code = module_cfg["module_code"].lower()
    return (
        module_code in file_name
        or "all_modules" in file_name
        or file_name in {"a4.json", "football_all_modules_once_full.json", "api_snapshot_current.json"}
        or file_name.startswith("api_snapshot_")
    )


def merge_snapshot_section(record, section):
    if not isinstance(section, dict):
        return
    for key, value in section.items():
        if key in record and not record.get(key):
            record[key] = stringify(value)


def build_record_from_snapshot_match(module_cfg, match):
    if not isinstance(match, dict):
        return None
    record = empty_record(module_cfg)

    for key, value in match.items():
        if key in record:
            record[key] = stringify(value)

    for section_name in (
        "base",
        "plays",
        "history",
        "strength_detail",
        "lineup",
        "odds_europe",
        "odds_asia",
        "debug",
    ):
        merge_snapshot_section(record, match.get(section_name))

    if not record["lottery_category"]:
        record["lottery_category"] = module_cfg["module_name"]
    if record["match_id2"]:
        record["detail_url"] = build_detail_url(module_cfg, record["match_id2"])
    if not record["captured_at"]:
        record["captured_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if not record["home_team"] and not record["away_team"] and not record["match_id2"]:
        return None
    return record


def dismiss_overlays(page):
    for _ in range(3):
        try:
            locator = page.get_by_text("知道了", exact=True)
            if locator.count() > 0 and locator.first.is_visible():
                locator.first.click(timeout=1500)
                page.wait_for_timeout(500)
        except Exception:
            break


def safe_click(page, text, exact=True):
    try:
        locator = page.get_by_text(text, exact=exact)
        if locator.count() > 0:
            locator.first.scroll_into_view_if_needed(timeout=1500)
            locator.first.click(timeout=3000)
            page.wait_for_timeout(1200)
            return True
    except Exception:
        return False
    return False


def safe_click_tab(page, text):
    try:
        locator = page.get_by_role("tab", name=text)
        if locator.count() > 0:
            locator.first.scroll_into_view_if_needed(timeout=1500)
            locator.first.click(timeout=3000)
            page.wait_for_timeout(1200)
            return True
    except Exception:
        return False
    return safe_click(page, text, exact=True)


def extract_body_text(page):
    try:
        return page.evaluate("() => document.body ? document.body.innerText : ''")
    except Exception:
        return ""


def parse_strength_scores(text):
    lines = split_lines(text)
    try:
        idx = lines.index("综合实力")
    except ValueError:
        return "", "", ""
    window = lines[idx : idx + 12]
    numbers = [line for line in window if re.fullmatch(r"\d+(?:\.\d+)?", line)]
    home_score = numbers[0] if len(numbers) > 0 else ""
    away_score = numbers[1] if len(numbers) > 1 else ""
    desc = ""
    for line in window:
        if "综合实力根据" in line:
            desc = line
            break
    return home_score, away_score, desc


def find_request_payload(request_log, url_keyword):
    for item in request_log:
        if url_keyword in item.get("url", "") and item.get("post_data"):
            return item.get("post_data", "")
    return ""


def capture_detail(page, module_cfg, match_id2, refresh_mode="full"):
    detail_url = build_detail_url(module_cfg, match_id2)
    lineup_url = detail_url.replace("current_tab=history", "current_tab=lineup")
    wants_fast = refresh_mode in {"full", "fast"}
    wants_slow = refresh_mode in {"full", "slow"}
    captured = {
        "history_api_raw": "",
        "base_api_raw": "",
        "lineup_api_raw": "",
        "europe_list_api_raw": [],
        "europe_stats_api_raw": [],
        "asia_list_api_raw": [],
        "asia_stats_api_raw": [],
        "request_log": [],
        "history_dom_text": "",
        "strength_detail_dom_text": "",
        "lineup_dom_text": "",
        "europe_dom_text": "",
        "asia_dom_text": "",
    }

    def on_request(request):
        url = request.url
        if any(
            key in url
            for key in (
                "historyV1",
                "match/base/2",
                "lineupDataV1",
                "qkdata/odds/list/6",
                "qkdata/odds/detail/stats/europe",
                "qkdata/odds/list/5",
                "qkdata/odds/detail/stats/asia",
            )
        ):
            captured["request_log"].append(
                {
                    "method": request.method,
                    "url": url,
                    "post_data": request.post_data or "",
                }
            )

    def on_response(response):
        url = response.url
        try:
            text = response.text()
        except Exception:
            return
        if "historyV1" in url:
            captured["history_api_raw"] = text
        elif "match/base/2" in url:
            captured["base_api_raw"] = text
        elif "lineupDataV1" in url:
            captured["lineup_api_raw"] = text
        elif "qkdata/odds/list/6" in url:
            captured["europe_list_api_raw"].append(text)
        elif "qkdata/odds/detail/stats/europe" in url:
            captured["europe_stats_api_raw"].append(text)
        elif "qkdata/odds/list/5" in url:
            captured["asia_list_api_raw"].append(text)
        elif "qkdata/odds/detail/stats/asia" in url:
            captured["asia_stats_api_raw"].append(text)

    page.on("request", on_request)
    page.on("response", on_response)
    page.goto(detail_url, wait_until="networkidle", timeout=60000)
    page.wait_for_timeout(1500)
    dismiss_overlays(page)
    if wants_slow:
        captured["history_dom_text"] = extract_body_text(page)
        clicked = safe_click(page, "查看详细数据", exact=True)
        if not clicked:
            clicked = click_text_via_js(page, "查看详细数据")
        if clicked:
            wait_for_body_keywords(page, ["实力数据", "场面控制"], timeout_ms=7000)
            page.wait_for_timeout(800)
        dismiss_overlays(page)
        captured["strength_detail_dom_text"] = extract_body_text(page)
    if refresh_mode == "full":
        page.goto(detail_url, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(1200)
        dismiss_overlays(page)
    if wants_fast:
        if safe_click_tab(page, "欧指"):
            dismiss_overlays(page)
            wait_for_body_keywords(page, ["典型指数"], timeout_ms=5000)
            page.wait_for_timeout(1200)
            captured["europe_dom_text"] = extract_body_text(page)
        if safe_click_tab(page, "亚指"):
            dismiss_overlays(page)
            wait_for_body_keywords(page, ["典型亚盘"], timeout_ms=5000)
            page.wait_for_timeout(1200)
            captured["asia_dom_text"] = extract_body_text(page)
    if wants_slow:
        page.goto(lineup_url, wait_until="networkidle", timeout=60000)
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except PlaywrightTimeoutError:
            pass
        wait_for_body_keywords(page, ["首发阵容", "替补阵容"], timeout_ms=7000)
        page.wait_for_timeout(1500)
        dismiss_overlays(page)
        captured["lineup_dom_text"] = extract_body_text(page)
    return captured


def merge_detail_into_record(record, detail, refresh_mode="full"):
    wants_fast = refresh_mode in {"full", "fast"}
    wants_slow = refresh_mode in {"full", "slow"}
    history_api = parse_json_text(detail.get("history_api_raw"))
    base_api = parse_json_text(detail.get("base_api_raw"))
    lineup_api = parse_json_text(detail.get("lineup_api_raw"))
    europe_list_api = [parse_json_text(item) for item in detail.get("europe_list_api_raw") or []]
    europe_stats_api = [parse_json_text(item) for item in detail.get("europe_stats_api_raw") or []]
    asia_list_api = [parse_json_text(item) for item in detail.get("asia_list_api_raw") or []]
    asia_stats_api = [parse_json_text(item) for item in detail.get("asia_stats_api_raw") or []]
    if wants_slow:
        record["history_api_raw"] = stringify(history_api)
        record["base_api_raw"] = stringify(base_api)
        record["lineup_api_raw"] = stringify(lineup_api)
        record["history_dom_text"] = stringify(detail.get("history_dom_text"))
        record["strength_detail_dom_text"] = stringify(detail.get("strength_detail_dom_text"))
        record["lineup_dom_text"] = stringify(detail.get("lineup_dom_text"))
    if wants_fast:
        record["europe_list_api_raw"] = stringify(europe_list_api)
        record["europe_stats_api_raw"] = stringify(europe_stats_api)
        record["asia_list_api_raw"] = stringify(asia_list_api)
        record["asia_stats_api_raw"] = stringify(asia_stats_api)
        record["europe_dom_text"] = stringify(detail.get("europe_dom_text"))
        record["asia_dom_text"] = stringify(detail.get("asia_dom_text"))

    history_lines = split_lines(detail.get("history_dom_text"))
    strength_lines = split_lines(detail.get("strength_detail_dom_text"))
    lineup_lines = split_lines(detail.get("lineup_dom_text"))
    europe_lines = split_lines(detail.get("europe_dom_text"))
    asia_lines = split_lines(detail.get("asia_dom_text"))
    lineup_compare_title = ""
    if "阵容数据对比-上一场" in lineup_lines:
        lineup_compare_title = "阵容数据对比-上一场"
    elif "阵容数据对比" in lineup_lines:
        lineup_compare_title = "阵容数据对比"
    strength_sections = extract_strength_compare_sections(strength_lines)

    if wants_slow:
        record["history_home_summary"] = find_line(history_lines, "主队近10场")
        record["history_away_summary"] = find_line(history_lines, "客队近10场")
        home_score, away_score, desc = parse_strength_scores(detail.get("history_dom_text"))
        if not home_score or not away_score:
            home_score, away_score, desc = parse_strength_scores(detail.get("strength_detail_dom_text"))
        record["overall_strength_home_score"] = home_score
        record["overall_strength_away_score"] = away_score
        record["overall_strength_desc"] = desc
        record["strength_overview_title"] = "实力数据" if "实力数据" in strength_lines else ""
        record["strength_compare_scope"] = stringify(
            [line for line in strength_lines if line in ("近10", "近20", "近30", "同赛事", "同主客")]
        )
        record["strength_compare_scene_control"] = stringify(strength_sections["scene_control"])
        record["strength_compare_attack_defense"] = stringify(strength_sections["attack_defense"])
        record["strength_compare_corner_foul"] = stringify(strength_sections["corner_foul"])
        record["strength_compare_half_full"] = stringify(strength_sections["half_full"])

        record["lineup_overview"] = stringify(slice_between(lineup_lines, "阵容概览", "技术对比"))
        record["lineup_tech_compare"] = stringify(
            slice_between(lineup_lines, "技术对比", lineup_compare_title or "首发阵容")
        )
        record["lineup_last_match_compare"] = stringify(
            slice_between(lineup_lines, lineup_compare_title, "首发阵容") if lineup_compare_title else []
        )
        starting_block = slice_between(lineup_lines, "首发阵容", "替补阵容")
        coach_indices = [i for i, line in enumerate(starting_block) if line.startswith("教练：")]
        if len(coach_indices) >= 2:
            record["lineup_starting_home"] = stringify(starting_block[: coach_indices[0] + 2])
            record["lineup_starting_away"] = stringify(starting_block[coach_indices[0] + 2 : coach_indices[1] + 2])
        else:
            record["lineup_starting_home"] = stringify(starting_block)
            record["lineup_starting_away"] = ""

        bench_block = slice_between(lineup_lines, "替补阵容", "预计伤停以及影响")
        if bench_block:
            away_start = -1
            for i, line in enumerate(bench_block):
                if line == record["away_team"]:
                    away_start = i
                    break
            if away_start != -1:
                record["lineup_bench_home"] = stringify(bench_block[:away_start])
                record["lineup_bench_away"] = stringify(
                    trim_before_keywords(
                        bench_block[away_start:],
                        ["进球", "点击查看>", "预计伤停以及影响", "投诉/反馈"],
                    )
                )
            else:
                record["lineup_bench_home"] = stringify(bench_block)
                record["lineup_bench_away"] = ""

        injury_block = slice_between(lineup_lines, "预计伤停以及影响", None)
        if injury_block:
            injury_block = trim_before_keywords(injury_block, ["投诉/反馈", "参数错误1"])
            if record["away_team"] in injury_block:
                away_idx = injury_block.index(record["away_team"])
                record["lineup_injury_home"] = stringify(injury_block[:away_idx])
                record["lineup_injury_away"] = stringify(injury_block[away_idx:])
            else:
                record["lineup_injury_home"] = stringify(injury_block)
                record["lineup_injury_away"] = ""

    europe_tabs = ["指数", "让球", "凯利", "总进球数", "比分", "半全场"]
    asia_tabs = ["盘口", "凯利", "大小球"]
    if wants_fast:
        record["europe_analysis_cards"] = stringify(
            extract_swipe_analysis(
                europe_lines,
                europe_tabs,
                "典型指数",
                start_markers=["概率转换", "查看全部"],
            )
        )
        record["europe_index_table"] = stringify(
            parse_odds_table(
                europe_lines,
                "典型指数",
                ["投诉/反馈", "参数错误1"],
                ["初始", "最新"],
            )
        )
        record["asia_analysis_cards"] = stringify(
            extract_swipe_analysis(
                asia_lines,
                asia_tabs,
                "典型亚盘",
                start_markers=["亚盘赢盘率"],
            )
        )
        record["asia_handicap_table"] = stringify(
            parse_odds_table(
                asia_lines,
                "典型亚盘",
                ["投诉/反馈", "参数错误", "参数错误1"],
                ["初始盘口", "最新盘口"],
            )
        )

    if wants_slow and history_api:
        history_data = history_api.get("data") or {}
        record["history_home_recent_list"] = stringify(
            ((history_data.get("homeHistoryMatches") or {}).get("matches")) or []
        )
        record["history_away_recent_list"] = stringify(
            ((history_data.get("awayHistoryMatches") or {}).get("matches")) or []
        )
        record["history_h2h_list"] = stringify(
            ((history_data.get("historyMatches") or {}).get("matches")) or []
        )
        record["history_home_schedule_list"] = stringify(
            (history_data.get("homeRecentlyMatches")) or []
        )
        record["history_away_schedule_list"] = stringify(
            (history_data.get("awayRecentlyMatches")) or []
        )
    if wants_slow and base_api:
        base_data = base_api.get("data") or {}
        record["home_team"] = stringify(base_data.get("homeTeamName")) or record["home_team"]
        record["away_team"] = stringify(base_data.get("awayTeamName")) or record["away_team"]
        record["league_name"] = stringify(base_data.get("tournamentName")) or record["league_name"]
        match_time_text = stringify(base_data.get("matchTime"))
        if match_time_text and " " in match_time_text:
            record["match_time"] = match_time_text.split(" ", 1)[1][:5] or record["match_time"]
        home_region = stringify(base_data.get("homeTeamPosRegion"))
        away_region = stringify(base_data.get("awayTeamPosRegion"))
        home_pos = stringify(base_data.get("homeTeamPosition"))
        away_pos = stringify(base_data.get("awayTeamPosition"))
        if home_region or home_pos:
            record["home_rank_text"] = norm_text(f"[{home_pos}] {home_region}".strip())
        if away_region or away_pos:
            record["away_rank_text"] = norm_text(f"[{away_pos}] {away_region}".strip())
        if not record["overall_strength_desc"]:
            record["overall_strength_desc"] = stringify(base_api)
    if wants_slow and lineup_api:
        overwrite_lineup_fields_from_api(record, lineup_api)
        if not record["lineup_overview"]:
            record["lineup_overview"] = stringify(lineup_api)

    record["request_log"] = stringify(
        {
            "history_post_data": find_request_payload(detail.get("request_log", []), "historyV1"),
            "base_post_data": find_request_payload(detail.get("request_log", []), "match/base/2"),
            "lineup_post_data": find_request_payload(detail.get("request_log", []), "lineupDataV1"),
            "europe_list_post_data": find_request_payload(detail.get("request_log", []), "qkdata/odds/list/6"),
            "europe_stats_post_data": find_request_payload(
                detail.get("request_log", []), "qkdata/odds/detail/stats/europe"
            ),
            "asia_list_post_data": find_request_payload(detail.get("request_log", []), "qkdata/odds/list/5"),
            "asia_stats_post_data": find_request_payload(
                detail.get("request_log", []), "qkdata/odds/detail/stats/asia"
            ),
        }
    )


def to_match_output(record):
    return {key: stringify(record.get(key, "")) for key in LEGACY_MATCH_FIELDS}


def collect_module_records(context, module_cfg):
    strategy = module_cfg["list_strategy"]
    try:
        if strategy == "api_jczq":
            records = flatten_jczq_match_list(module_cfg, fetch_json(JCZQ_LIST_API))
        elif strategy == "page_dc_like":
            records = collect_dc_like_records(context, module_cfg)
        elif strategy == "api_zq14":
            records = collect_zq14_records(module_cfg)
        else:
            raise ValueError(f"Unknown list strategy: {strategy}")
        if records or module_cfg.get("allow_empty_list"):
            return records
        snapshot_records = load_snapshot_module_records(module_cfg)
        if snapshot_records is not None:
            return snapshot_records
        return records
    except Exception:
        snapshot_records = load_snapshot_module_records(module_cfg)
        if snapshot_records is not None:
            return snapshot_records
        raise


def crawl_payload(
    selected_modules=None,
    limit_per_module=None,
    progress_callback=None,
    headless=True,
    refresh_mode="full",
):
    module_codes = selected_modules or ["jczq", "bjdc", "zq14", "sfgg"]
    now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    payload = {
        "source_url": SOURCE_URL,
        "captured_at": now_text,
        "station_user_id": STATION_USER_ID,
        "station_uuid": STATION_UUID,
        "refresh_mode": refresh_mode,
        "modules": {},
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            viewport={"width": 1280, "height": 2400},
            user_agent="Mozilla/5.0",
        )
        for module_code in module_codes:
            module_cfg = MODULES[module_code]
            records = collect_module_records(context, module_cfg)
            if limit_per_module:
                records = records[:limit_per_module]

            module_matches = []
            total = len(records)
            for index, record in enumerate(records, start=1):
                if record["match_id2"]:
                    detail = None
                    last_error = None
                    for attempt in range(1, 4):
                        page = context.new_page()
                        try:
                            detail = capture_detail(
                                page,
                                module_cfg,
                                record["match_id2"],
                                refresh_mode=refresh_mode,
                            )
                            if detail_capture_is_usable(detail, refresh_mode):
                                if attempt > 1:
                                    record["error"] = ""
                                break
                            last_error = RuntimeError(
                                f"detail capture returned empty content on attempt {attempt}"
                            )
                            if attempt == 3:
                                record["error"] = stringify(str(last_error))
                        except Exception as exc:
                            last_error = exc
                            if attempt == 3:
                                record["error"] = stringify(f"{type(exc).__name__}: {exc}")
                        finally:
                            page.close()
                        time.sleep(1.2 * attempt)
                    if detail:
                        merge_detail_into_record(record, detail, refresh_mode=refresh_mode)
                    message = (
                        f"[{module_code}/{refresh_mode} {index}/{total}] "
                        f"{'ok' if not record['error'] else 'warn'} "
                        f"{record['match_no']} {record['home_team']} VS {record['away_team']}"
                    )
                    if record["error"]:
                        message = f"{message} | {record['error']}"
                    if progress_callback:
                        progress_callback(message)
                    else:
                        print(message)
                module_matches.append(to_match_output(record))

            payload["modules"][module_code] = {
                "module_code": module_cfg["module_code"],
                "module_name": module_cfg["module_name"],
                "match_count": stringify(len(module_matches)),
                "matches": module_matches,
            }
        browser.close()
    return payload


def save_payload(payload, output_path=None):
    if not output_path:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join("output", f"football_all_modules_once_{ts}.json")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return output_path


def run(selected_modules=None, limit_per_module=None, output_path=None, refresh_mode="full"):
    payload = crawl_payload(
        selected_modules=selected_modules,
        limit_per_module=limit_per_module,
        refresh_mode=refresh_mode,
    )
    output_path = save_payload(payload, output_path=output_path)
    print(output_path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--module",
        action="append",
        choices=list(MODULES.keys()),
        help="只抓指定模块，可重复传入多次",
    )
    parser.add_argument("--limit-per-module", type=int, default=0)
    parser.add_argument("--output", default="")
    parser.add_argument("--refresh-mode", choices=["full", "fast", "slow"], default="full")
    args = parser.parse_args()
    run(
        selected_modules=args.module or None,
        limit_per_module=args.limit_per_module or None,
        output_path=args.output or None,
        refresh_mode=args.refresh_mode,
    )


if __name__ == "__main__":
    main()
