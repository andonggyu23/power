# -*- coding: utf-8 -*-
# =====================================================================
#  fetch_data.py  —  대한민국 전력통계 자동수집 스크립트 (EPSIS 실데이터)
# ---------------------------------------------------------------------
#  사용법:
#    1) Python 3.x + requests 설치  (pip install requests)
#    2) 더블클릭 또는 콘솔에서:   python fetch_data.py
#    3) 같은 폴더에 power_data.js / consumption_data.js 를 재생성한다.
#       (index.html 은 건드리지 않음)
#
#  하는 일:
#    - EPSIS(전력통계정보시스템) 4개 엔드포인트를 호출/파싱해
#      대시보드용 전역객체(window.POWER_DATA, window.CONSUMPTION_DATA)를 생성.
#    - 전부 실측. 추정 없음. 데이터 없는 연도는 키를 넣지 않음.
#    - 실행 시 검증결과와 "마지막 업데이트" 시각을 콘솔에 출력.
#
#  표준 라이브러리 + requests 만 사용.
# =====================================================================
import re
import sys
import json
import datetime
import requests

# 콘솔 한글 출력
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "X-Requested-With": "XMLHttpRequest",
}
TIMEOUT = 90

# 17개 시도 표준 키 (대시보드 고정 순서)
SIDO = ["서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종",
        "경기", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주"]

# 연도 범위 설정
CAP_MIN_YEAR = 2016          # 설비용량: 2016~최신(12월 기준, 현재 가용 최신연도까지)
GEN_TOTAL_MIN_YEAR = 2016    # 시도별 발전량 총량: 2016~최신(EPSIS 발행 최신연도까지)
GEN_FUEL_MIN_YEAR = 2018     # 전국 발전원별: 2018~최신
CONS_MIN_YEAR = 2018         # 시도별 소비량: 2018~ (가용 전부, 최소 2018~2024)

URL_CAP   = "https://epsis.kpx.or.kr/epsisnew/selectEkpoBft.ajax"
URL_GTOT  = "https://epsis.kpx.or.kr/epsisnew/selectEkgeGepGbaChart.do?menuId=060104"
URL_GFUEL = "https://epsis.kpx.or.kr/epsisnew/selectEkgeGepGesGrid.do?menuId=060102"
URL_CONS  = "https://epsis.kpx.or.kr/epsisnew/selectEksaAscAsaChart.do?menuId=060405"


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------
# 1) 설비용량 (MW)  POST selectEkpoBft.ajax
#    응답: JS 블록. 블록마다 c1~c98 var 할당 -> nmArea -> year("YYYY/12") -> gridData.push
#    컬럼:  c1=원자력 c2=유연탄 c3=무연탄 c4=유류 c5=LNG c6=양수 c7=기타 c8=합계
#           c91~c98=신재생 세분류 (c95=수력)
#    버킷:  nuclear=c1 / coal=c2+c3 / gas=c5 / renewable=신재생계(c91..c98 합)
#           etc=c4+c6+c7 / hydro=c95(참고용)  →  5버킷 합 ≈ c8(합계)
# ---------------------------------------------------------------------
def fetch_capacity():
    sel_year = str(datetime.datetime.now().year)   # 현재 연도로 요청 → 가용 최신연도까지 응답
    r = requests.post(URL_CAP, data={"selYear": sel_year, "selRegion": "0"},
                      headers=HEADERS, timeout=TIMEOUT)
    t = r.content.decode("utf-8", "replace")

    segs = t.split("gridData.push")
    records = []  # (year_int, region, cdict)
    for seg in segs:
        cv = {}
        for n, v in re.findall(r'c(\d+) = textFormmat\("([0-9.\-]+)",count\)', seg):
            cv[int(n)] = _f(v)
        areas = re.findall(r'nmArea="([^"]*)"', seg)
        yrs = re.findall(r'year = "([0-9]{4})/12"', seg)
        if cv and areas and yrs:
            records.append((int(yrs[-1]), areas[-1], cv))

    by_year = {}   # {year:int -> {sido -> bucket dict}}
    raw_c8 = {}    # {year -> {sido -> c8}}  (검증용)
    for yr, region, cv in records:
        if region == "소계":          # 전국 소계행 제외
            continue
        if region not in SIDO:
            continue
        if yr < CAP_MIN_YEAR:
            continue
        renewable = sum(cv.get(k, 0.0) for k in (91, 92, 93, 94, 95, 96, 97, 98))
        bucket = {
            "nuclear":   round(cv.get(1, 0.0), 1),
            "coal":      round(cv.get(2, 0.0) + cv.get(3, 0.0), 1),
            "gas":       round(cv.get(5, 0.0), 1),
            "renewable": round(renewable, 1),
            "etc":       round(cv.get(4, 0.0) + cv.get(6, 0.0) + cv.get(7, 0.0), 1),
            "hydro":     round(cv.get(95, 0.0), 1),
            "total":     round(cv.get(8, 0.0), 1),
        }
        by_year.setdefault(yr, {})[region] = bucket
        raw_c8.setdefault(yr, {})[region] = cv.get(8, 0.0)

    # 17개 시도 모두 있는 연도만 채택
    complete = {y: d for y, d in by_year.items() if len(d) == 17}
    return complete, raw_c8


# ---------------------------------------------------------------------
# 2) 시도별 발전량 총량 (MWh→GWh)  GET selectEkgeGepGbaChart.do
#    chartData.push({"Date":"YYYY", "Value":..,"Value2":..,..,"Value16":..,"Value18":..})
#    value..value18 (value17 결번) → 17개 시도 순서:
#    서울/부산/대구/인천/광주/대전/울산/경기/강원/충북/충남/전북/전남/경북/경남/제주/세종
# ---------------------------------------------------------------------
def fetch_generation_total():
    r = requests.get(URL_GTOT, headers=HEADERS, timeout=TIMEOUT)
    t = r.content.decode("utf-8", "replace")

    order = ["서울", "부산", "대구", "인천", "광주", "대전", "울산", "경기",
             "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주", "세종"]
    # value 변수 순서: value, value2..value16, value18 (value17 결번)
    vnames = ["value"] + ["value%d" % i for i in range(2, 17)] + ["value18"]

    # 각 블록은 value 변수들을 할당한 뒤 chartData.push({"Date":"YYYY", ...}) 한다.
    # push 호출 직전 토큰(setup)에 해당 연도의 값이 들어있다.
    toks = re.split(r'chartData\.push\(\{"Date":"(\d{4})"', t)
    # toks: [setup0, year0, body0+setup1, year1, ...]
    by_year = {}
    seen = set()
    for k in range(1, len(toks), 2):
        yr = int(toks[k])
        setup = toks[k - 1]
        if yr in seen:
            continue
        seen.add(yr)
        if yr < GEN_TOTAL_MIN_YEAR:
            continue
        assigns = dict(re.findall(r'(value\d*) = "([0-9.\-]+)"', setup))
        region_map = {}
        for region, vn in zip(order, vnames):
            region_map[region] = round(_f(assigns.get(vn, "0")) / 1000.0, 1)  # MWh->GWh
        by_year[yr] = {s: region_map[s] for s in SIDO}
    return by_year


# ---------------------------------------------------------------------
# 3) 전국 발전원별 발전량 (GWh)  GET selectEkgeGepGesGrid.do
#    블록: if(srchDate==YYYY){ genName=...; c1..c20; c17=총계; push }
#    버킷(genName의 c17 사용, 합계 정확 일치):
#      nuclear=원자력 / coal=유연탄+무연탄 / gas=LNG /
#      renewable=신재생 계(수력 포함) / etc=유류+양수+기타 / hydro=수력
#      total=총계
# ---------------------------------------------------------------------
def fetch_generation_fuel():
    r = requests.get(URL_GFUEL, headers=HEADERS, timeout=TIMEOUT)
    t = r.content.decode("utf-8", "replace")

    pat = re.compile(
        r'==\"(\d{4})\"\)\{\s*idx = "\d+";\s*genName = "([^"]*)";(.*?)c17 = "([0-9.\-]+)";',
        re.S)
    # year -> {genName -> c17 total}
    data = {}
    for m in pat.finditer(t):
        yr, name, _body, c17 = m.groups()
        yr = int(yr)
        data.setdefault(yr, {})[name.strip()] = _f(c17)

    by_year = {}
    for yr, d in data.items():
        if yr < GEN_FUEL_MIN_YEAR:
            continue
        nuclear   = d.get("원자력", 0.0)
        coal      = d.get("유연탄", 0.0) + d.get("무연탄", 0.0)
        gas       = d.get("LNG", 0.0)
        renewable = d.get("신재생 계", 0.0)
        etc       = d.get("유류", 0.0) + d.get("양수", 0.0) + d.get("기타", 0.0)
        hydro     = d.get("수력", 0.0)
        total     = d.get("총계", d.get("총      계", 0.0))
        by_year[yr] = {
            "nuclear":   round(nuclear, 1),
            "coal":      round(coal, 1),
            "gas":       round(gas, 1),
            "renewable": round(renewable, 1),
            "etc":       round(etc, 1),
            "hydro":     round(hydro, 1),
            "total":     round(total, 1),
        }
    return by_year


# ---------------------------------------------------------------------
# 4) 시도별 소비량 (판매전력량, MWh→GWh)  GET selectEksaAscAsaChart.do
#    블록: c-vars... gridData.push({"gubun":"<지역>", ...})
#    각 지역 블록은 최신연도(2024)부터 내림차순. 총합계 컬럼은
#    블록 내 가장 마지막(최고번호) c-var (2020+ : c34 / 2019이하 : c27).
# ---------------------------------------------------------------------
def fetch_consumption():
    r = requests.get(URL_CONS, headers=HEADERS, timeout=TIMEOUT)
    t = r.content.decode("utf-8", "replace")

    toks = re.split(r'gridData\.push\(\{"gubun":"([^"]*)"', t)
    # toks: [setup0, gubun0, setup1, gubun1, ...]
    per_region = {}  # region -> [total_GWh in document order (desc year)]
    for k in range(1, len(toks), 2):
        gubun = toks[k]
        setup = toks[k - 1]
        asg = re.findall(r'c(\d+) = (?:textFormmat\(")?([0-9.\-]+)', setup)
        if not asg:
            per_region.setdefault(gubun, []).append(None)
            continue
        total = _f(asg[-1][1])  # 마지막 c-var = 합계 컬럼
        per_region.setdefault(gubun, []).append(total / 1000.0)  # MWh -> GWh

    # 블록 0번째 = 2024, 이후 내림차순
    by_year = {}  # year -> {sido -> GWh}
    for region, lst in per_region.items():
        if region not in SIDO:
            continue
        for i, v in enumerate(lst):
            yr = 2024 - i
            if v is None:
                continue
            if yr < CONS_MIN_YEAR:
                continue
            by_year.setdefault(yr, {})[region] = round(v, 1)

    # 17개 시도 모두 있는 연도만 채택 (세종은 출범 후만 존재)
    complete = {y: d for y, d in by_year.items() if len(d) == 17}
    return complete


# ---------------------------------------------------------------------
#  기존 consumption_data.js 의 월별값 재사용 (CONSUMPTION_MONTHLY, 2025)
# ---------------------------------------------------------------------
def load_existing_monthly():
    import os
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "consumption_data.js")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            txt = fh.read()
    except Exception:
        return None
    # window.CONSUMPTION_MONTHLY = {...}; 또는 consumption_monthly: {...}
    # 중첩 객체이므로 non-greedy 정규식 대신 중괄호 균형 매칭으로 전체 블록 추출
    key = re.search(r'(?:CONSUMPTION_MONTHLY\s*=|consumption_monthly\s*:)\s*\{', txt)
    if not key:
        return None
    start = key.end() - 1          # 여는 '{' 위치
    depth = 0
    block = None
    for j in range(start, len(txt)):
        if txt[j] == '{':
            depth += 1
        elif txt[j] == '}':
            depth -= 1
            if depth == 0:
                block = txt[start:j + 1]
                break
    if block is None:
        return None
    # 시도별 {"01":n,...} 추출
    out = {}
    for rm in re.finditer(r'"([가-힣]+)"\s*:\s*\{([^}]*)\}', block):
        region = rm.group(1)
        if region not in SIDO:
            continue
        months = {}
        for mm in re.finditer(r'"(\d{2})"\s*:\s*([0-9.\-]+)', rm.group(2)):
            months[mm.group(1)] = _f(mm.group(2))
        if months:
            out[region] = months
    return out or None


# ---------------------------------------------------------------------
#  JS 직렬화 헬퍼
# ---------------------------------------------------------------------
def _num(v):
    # 정수면 정수로, 아니면 소수1자리
    if v == int(v):
        return str(int(v))
    return ("%.1f" % v).rstrip("0").rstrip(".")


def js_bucket(b):
    return ("{" +
            ",".join('"%s":%s' % (k, _num(b[k]))
                     for k in ("nuclear", "coal", "gas", "renewable", "etc", "hydro", "total")) +
            "}")


def js_region_map(d):
    return ("{" + ", ".join('"%s":%s' % (s, _num(d[s])) for s in SIDO if s in d) + "}")


# ---------------------------------------------------------------------
#  메인
# ---------------------------------------------------------------------
def main():
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    print("=" * 60)
    print(" 대한민국 전력통계 자동수집 (EPSIS)")
    print("=" * 60)

    print("[1/4] 설비용량 수집 중...")
    cap, raw_c8 = fetch_capacity()
    print("[2/4] 시도별 발전량(총량) 수집 중...")
    gtot = fetch_generation_total()
    print("[3/4] 전국 발전원별 발전량 수집 중...")
    gfuel = fetch_generation_fuel()
    print("[4/4] 시도별 소비량 수집 중...")
    cons = fetch_consumption()
    monthly = load_existing_monthly()

    cap_years = sorted(cap.keys())
    gtot_years = sorted(gtot.keys())
    gfuel_years = sorted(gfuel.keys())
    cons_years = sorted(cons.keys())

    # -------------------- 검증 --------------------
    print()
    print("-" * 60)
    print(" 검증 결과")
    print("-" * 60)
    ok = True

    # (a) 설비: 5버킷 합 ≈ c8 합계
    print(" [설비용량] 연도별 (5버킷합 vs c8합계, MW):")
    for y in cap_years:
        bsum = sum(cap[y][s]["nuclear"] + cap[y][s]["coal"] + cap[y][s]["gas"] +
                   cap[y][s]["renewable"] + cap[y][s]["etc"] for s in SIDO)
        c8sum = sum(cap[y][s]["total"] for s in SIDO)
        diff = abs(bsum - c8sum)
        flag = "OK" if diff < 50 else "WARN"
        if diff >= 50:
            ok = False
        print("   %d: 버킷합=%9.1f  합계=%9.1f  차이=%6.1f  [%s]" %
              (y, bsum, c8sum, diff, flag))

    # (b) 2024 전국발전원별 합 = 594,266
    if 2024 in gfuel:
        g = gfuel[2024]
        s5 = g["nuclear"] + g["coal"] + g["gas"] + g["renewable"] + g["etc"]
        print(" [전국발전원별 2024] nuclear=%.0f coal=%.0f gas=%.0f renewable=%.0f etc=%.0f"
              % (g["nuclear"], g["coal"], g["gas"], g["renewable"], g["etc"]))
        print("   5버킷합=%.1f  total=%.1f  (기대 594266)" % (s5, g["total"]))
        if abs(g["total"] - 594266.3) > 5 or abs(s5 - g["total"]) > 5:
            ok = False
            print("   [WARN] 594,266 GWh 불일치")
        else:
            print("   [OK]")

    # (c) 2024 시도별 발전량 합 ≈ 595,601
    if 2024 in gtot:
        ssum = sum(gtot[2024].values())
        print(" [시도별 발전량 2024] 합계=%.1f GWh (기대 ~595,601)" % ssum)
        print("   [%s]" % ("OK" if abs(ssum - 595601) < 2000 else "WARN"))

    # (d) 소비 2024 전국합 ≈ 549,821
    if 2024 in cons:
        csum = sum(cons[2024].values())
        print(" [소비량 2024] 전국합=%.1f GWh (기대 ~549,821)" % csum)
        print("   [%s]" % ("OK" if abs(csum - 549821) < 2000 else "WARN"))

    # -------------------- power_data.js --------------------
    p_lines = []
    p_lines.append("// AUTO-GENERATED by fetch_data.py — do not edit by hand")
    p_lines.append("window.POWER_DATA = {")
    p_lines.append('  last_updated: "%s",' % now)
    p_lines.append('  capacity_unit: "MW", generation_unit: "GWh",')
    p_lines.append("  capacity_years: [%s]," % ",".join(str(y) for y in cap_years))
    p_lines.append("  generation_years: [%s]," % ",".join(str(y) for y in gtot_years))
    # capacity_by_year (최신연도 먼저)
    cap_body = []
    for y in sorted(cap_years, reverse=True):
        regs = ", ".join('"%s": %s' % (s, js_bucket(cap[y][s])) for s in SIDO)
        cap_body.append('    "%d": { %s }' % (y, regs))
    p_lines.append("  capacity_by_year: {\n" + ",\n".join(cap_body) + "\n  },")
    # generation_total_by_year
    gt_body = []
    for y in sorted(gtot_years, reverse=True):
        gt_body.append('    "%d": %s' % (y, js_region_map(gtot[y])))
    p_lines.append("  generation_total_by_year: {\n" + ",\n".join(gt_body) + "\n  },")
    # generation_national_by_fuel_by_year
    gf_body = []
    for y in sorted(gfuel_years, reverse=True):
        gf_body.append('    "%d": %s' % (y, js_bucket(gfuel[y])))
    p_lines.append("  generation_national_by_fuel_by_year: {\n" + ",\n".join(gf_body) + "\n  },")
    p_lines.append("  sources: [")
    p_lines.append('    {"name":"EPSIS 「연료원별 발전설비」 (selectEkpoBft.ajax)", "url":"https://epsis.kpx.or.kr/epsisnew/selectEkpoBftChart.do?menuId=020100", "note":"시도×발전원 설비용량(MW), 각 연도 12월 기준 실측"},')
    p_lines.append('    {"name":"EPSIS 「지역별 발전량」", "url":"https://epsis.kpx.or.kr/epsisnew/selectEkgeGepGbaChart.do?menuId=060104", "note":"시도별 총발전량(MWh→GWh)"},')
    p_lines.append('    {"name":"EPSIS 「에너지원별 발전량」", "url":"https://epsis.kpx.or.kr/epsisnew/selectEkgeGepGesGrid.do?menuId=060102", "note":"전국 발전원별 발전량(GWh)"}')
    p_lines.append("  ]")
    p_lines.append("};")
    power_js = "\n".join(p_lines) + "\n"

    # -------------------- consumption_data.js --------------------
    c_lines = []
    c_lines.append("// AUTO-GENERATED by fetch_data.py — do not edit by hand")
    c_lines.append("window.CONSUMPTION_DATA = {")
    c_lines.append('  last_updated: "%s", unit: "GWh",' % now)
    c_lines.append("  consumption_years: [%s]," % ",".join(str(y) for y in cons_years))
    cb_body = []
    for y in sorted(cons_years, reverse=True):
        cb_body.append('    "%d": %s' % (y, js_region_map(cons[y])))
    c_lines.append("  consumption_by_year: {\n" + ",\n".join(cb_body) + "\n  },")
    if monthly:
        c_lines.append("  monthly_year: 2025,")
        mb = []
        for s in SIDO:
            if s in monthly:
                mm = ",".join('"%s":%s' % (k, _num(monthly[s][k]))
                              for k in sorted(monthly[s].keys()))
                mb.append('    "%s": {%s}' % (s, mm))
        c_lines.append("  consumption_monthly: {\n" + ",\n".join(mb) + "\n  },")
    c_lines.append("  sources: [")
    c_lines.append('    {"name":"EPSIS 「시도별 용도별 판매전력량」", "url":"https://epsis.kpx.or.kr/epsisnew/selectEksaAscAsaChart.do?menuId=060405", "note":"시도별 연간 소비량(판매전력량) MWh→GWh 실측"},')
    if monthly:
        c_lines.append('    {"name":"KEPCO 「시군구별 전력사용량」 월별 (2025)", "url":"https://www.kepco.co.kr/", "note":"시도 월별 소비량(기존 실측값 재사용)"}')
    else:
        c_lines.append('    {"name":"KEPCO 「시군구별 전력사용량」 월별", "url":"https://www.kepco.co.kr/", "note":"월별 소비 미수집"}')
    c_lines.append("  ]")
    c_lines.append("};")
    cons_js = "\n".join(c_lines) + "\n"

    # -------------------- 파일 출력 --------------------
    import os
    base = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(base, "power_data.js"), "w", encoding="utf-8") as fh:
        fh.write(power_js)
    with open(os.path.join(base, "consumption_data.js"), "w", encoding="utf-8") as fh:
        fh.write(cons_js)

    print()
    print("-" * 60)
    print(" 생성 완료")
    print("-" * 60)
    print("  설비용량 연도:        %s" % cap_years)
    print("  발전량(시도총량) 연도: %s" % gtot_years)
    print("  발전량(발전원별) 연도: %s" % gfuel_years)
    print("  소비량 연도:          %s" % cons_years)
    print("  월별소비(2025):       %s" % ("재사용함" if monthly else "없음(생략)"))
    print("  power_data.js       : %d bytes" % len(power_js.encode("utf-8")))
    print("  consumption_data.js : %d bytes" % len(cons_js.encode("utf-8")))
    print()
    print("  마지막 업데이트: %s" % now)
    print("  전체 검증: %s" % ("통과(OK)" if ok else "경고 있음(WARN 확인)"))


if __name__ == "__main__":
    main()
