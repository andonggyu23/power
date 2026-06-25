# -*- coding: utf-8 -*-
# 한국전력통계 제90~94호(2020~2024) → 시도×발전원 발전량 실측 + 신재생 세분(수력/태양광/풍력/바이오)
# 출력: kepco_gen_data.js  (window.KEPCO_GEN)
import sys; sys.stdout.reconfigure(encoding="utf-8")
import re, os, openpyxl

BASE = os.path.dirname(os.path.abspath(__file__))
SIDO = ["서울","부산","대구","인천","광주","대전","울산","세종",
        "경기","강원","충북","충남","전북","전남","경북","경남","제주"]
EDITIONS = {2020:"90", 2021:"91", 2022:"92", 2023:"93", 2024:"94"}

def short(name):
    if not name: return None
    n = re.sub(r"[A-Za-z()0-9]", "", str(name)).strip().replace(" ", "")
    for s in SIDO:
        if n.startswith(s): return s
    return None

def sheet_by(wb, prefix):
    for n in wb.sheetnames:
        if n.startswith(prefix): return wb[n]
    return None

def parse_edition(year, code):
    wb = openpyxl.load_workbook(os.path.join(BASE, "dl", "kepco%s.xlsx" % code), read_only=True, data_only=True)
    # 8-2: 발전량(MWh) 컬럼 idx → 10원자력 11무연탄 12유연탄 13LNG 14신재생 15유류 16양수 17기타 18계
    ws2 = sheet_by(wb, "8-2")
    rows2 = {}
    for r in ws2.iter_rows(values_only=True):
        s = short(r[0])
        if not s or len(r) < 19 or r[10] is None: continue
        g = lambda i: (r[i] or 0) / 1000.0
        rows2[s] = dict(nuclear=g(10), coal=g(11)+g(12), gas=g(13),
                        renewable=g(14), etc=g(15)+g(16)+g(17), total=g(18))
    # 8-3: 발전량 컬럼 idx → 7수력 8태양광 9풍력 10바이오 11기타 12계
    ws3 = sheet_by(wb, "8-3")
    rows3 = {}
    for r in ws3.iter_rows(values_only=True):
        s = short(r[0])
        if not s or len(r) < 13 or r[7] is None: continue
        g = lambda i: (r[i] or 0) / 1000.0
        rows3[s] = dict(hydro=g(7), solar=g(8), wind=g(9), bio=g(10), etc_re=g(11), re_total=g(12))
    out = {}
    for s in SIDO:
        a = rows2.get(s); b = rows3.get(s, {})
        if not a: continue
        rec = {k: round(a[k], 1) for k in ("nuclear","coal","gas","renewable","etc","total")}
        for k in ("solar","wind","hydro","bio","etc_re"):
            rec[k] = round(b.get(k, 0.0), 1)
        out[s] = rec
    return out, rows2, rows3

def num(v):
    return str(int(v)) if v == int(v) else ("%.1f" % v).rstrip("0").rstrip(".")

def main():
    data = {}
    print("=== 검증: 8-3 신재생계 vs 8-2 신재생, 시도합 vs 계 ===")
    for year, code in EDITIONS.items():
        out, r2, r3 = parse_edition(year, code)
        # check renewable subdivision sums to 8-2 신재생
        bad = 0
        for s in out:
            sub = out[s]["solar"]+out[s]["wind"]+out[s]["hydro"]+out[s]["bio"]+out[s]["etc_re"]
            if abs(sub - out[s]["renewable"]) > 2: bad += 1
        nat_total = sum(out[s]["total"] for s in out)
        nat_re = sum(out[s]["renewable"] for s in out)
        nat_solar = sum(out[s]["solar"] for s in out)
        print("  %d (제%s호): 시도수 %d, 신재생세분 불일치 %d개, 전국 총발전 %s GWh, 신재생 %s, 태양광 %s"
              % (year, code, len(out), bad, format(round(nat_total),","), format(round(nat_re),","), format(round(nat_solar),",")))
        data[year] = out

    # write JS
    lines = ["// AUTO-GENERATED from 한국전력통계 제90~94호 (KEPCO) — 시도×발전원 발전량 실측 + 신재생 세분",
             "window.KEPCO_GEN = {",
             '  source: "한국전력통계 제90~94호(한전) 8-2/8-3 행정구역별 발전설비 및 발전량",',
             '  url: "https://home.kepco.co.kr/kepco/KO/ntcob/list.do?boardCd=BRD_000099&menuCd=FN05030103",',
             '  unit: "GWh", note: "시도×발전원 발전량 실측. 신재생=수력+태양광+풍력+바이오+기타(신재생).",',
             "  years: [%s]," % ",".join(str(y) for y in sorted(data))]
    body = []
    for y in sorted(data, reverse=True):
        regs = []
        for s in SIDO:
            if s not in data[y]: continue
            d = data[y][s]
            kv = ",".join('"%s":%s' % (k, num(d[k])) for k in
                          ("nuclear","coal","gas","renewable","etc","total","solar","wind","hydro","bio","etc_re"))
            regs.append('"%s":{%s}' % (s, kv))
        body.append('    "%d": {%s}' % (y, ", ".join(regs)))
    lines.append("  by_year: {\n" + ",\n".join(body) + "\n  }")
    lines.append("};")
    js = "\n".join(lines) + "\n"
    with open(os.path.join(BASE, "kepco_gen_data.js"), "w", encoding="utf-8") as fh:
        fh.write(js)
    print("\nkepco_gen_data.js 생성: %d bytes, 연도 %s" % (len(js.encode()), sorted(data)))

if __name__ == "__main__":
    main()
