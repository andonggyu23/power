# -*- coding: utf-8 -*-
# 한전 전력통계월보 → 시도별 설비/발전/소비 통합 (6버킷: 원자력·석탄·LNG·유류·수력·신재생)
#  - 발전: 시트 10-1(누계, 연간/YTD)  - 설비: 시트 5(월말 스냅샷)
#  - 신재생 세분: 시트 9-1(태양광/풍력/소수력/바이오/연료전지/해양)
#  - 소비: 시트 20(행정구역 판매, 연도×시도)
#  출력: dashboard_standalone.html 의 WOLBO 데이터 블록을 직접 교체(단일 파일 유지)
#  갱신법: 새 월보 엑셀을 dl/kepco_YYYY_MM.xlsx 로 넣고  →  python kepco_wolbo.py
import sys; sys.stdout.reconfigure(encoding="utf-8")
import re, os, openpyxl
BASE=os.path.dirname(os.path.abspath(__file__))
SIDO=["서울","부산","대구","인천","광주","대전","울산","세종","경기","강원","충북","충남","전북","전남","경북","경남","제주"]

def build_editions():
    """dl/ 폴더의 kepco_YYYY_MM.xlsx 를 스캔해 연도별 '최신 월호'를 자동 선택.
       새 월보 엑셀(예: kepco_2026_08.xlsx)을 dl/ 에 넣기만 하면 자동 반영됨(코드 수정 불필요)."""
    d=os.path.join(BASE,"dl"); best={}
    if os.path.isdir(d):
        for fn in os.listdir(d):
            m=re.match(r"kepco_(\d{4})_(\d{2})\.xlsx$", fn)
            if not m: continue
            y,mo=int(m.group(1)),int(m.group(2))
            if y not in best or mo>best[y][0]: best[y]=(mo,"%04d_%02d"%(y,mo))
    return {y:best[y][1] for y in best}

EDITIONS=build_editions()

def num(x):
    if x is None: return 0.0
    if isinstance(x,(int,float)): return float(x)
    s=str(x).replace(",","").strip()
    if s in ("","-","‑","–"): return 0.0
    try: return float(s)
    except: return 0.0

def short(name):
    if not name: return None
    n=re.sub(r"[A-Za-z()0-9.~∼]","",str(name)).strip().replace(" ","")
    for s in SIDO:
        if n==s or n.startswith(s): return s
    return None

def sheet(wb,prefix):
    for n in wb.sheetnames:
        if n.strip().startswith(prefix): return wb[n]
    return None

# 발전형식 12컬럼(시도명 다음): 1수력 2무연탄 3유연탄 4유류 5LNG 6기력계 7복합 8내연 9원자력 10대체 11기타 12계
def remap6(r, base):
    g=lambda i:num(r[base+i])
    return dict(nuclear=g(9), coal=g(2)+g(3), lng=g(5)+g(7),
                oil=g(4)+g(8)+g(11), hydro=g(1), renewable=g(10), total=g(12))

def parse_form(ws, sido_col=0):
    out={}
    for r in ws.iter_rows(values_only=True):
        if len(r)<=sido_col+12: continue
        s=short(r[sido_col])
        if not s or s in out: continue
        rec=remap6(r, sido_col)
        if rec["total"]>0 or rec["nuclear"]+rec["coal"]+rec["lng"]>0:
            out[s]={k:round(v,1) for k,v in rec.items()}
    return out

def parse_re(ws):
    # 9-1: 시도 col1, 발전(GWh): 10소수력 11태양광 12풍력 13바이오 14해양 15연료전지 16IGCC
    out={}
    for r in ws.iter_rows(values_only=True):
        if len(r)<17: continue
        s=short(r[1])
        if not s or s in out: continue
        g=lambda i:round(num(r[i]),1)
        rec=dict(smallhydro=g(10),solar=g(11),wind=g(12),bio=g(13),ocean=g(14),fuelcell=g(15),igcc=g(16))
        if sum(rec.values())>0: out[s]=rec
    return out

def parse_cons(ws, year):
    rows=list(ws.iter_rows(values_only=True))
    # 헤더행: 시도명 가로배열 / 데이터행: 연도 + 시도값들
    hdr=None
    for r in rows:
        if r and str(r[0]).strip()=="구  분" and short(r[1]):
            hdr=[short(c) for c in r]; break
    if not hdr: return {}, None
    best=None;besty=-1
    for r in rows:
        try: y=int(str(r[0]).strip()[:4])
        except: continue
        if 2000<=y<=2100 and y<=year and y>besty: besty=y;best=r
    if not best: return {}, None
    out={}
    for i,s in enumerate(hdr):
        if s in SIDO: out[s]=round(num(best[i])/1000.0,1)  # MWh->GWh
    return out, besty

def jnum(v): return str(int(v)) if v==int(v) else ("%.1f"%v).rstrip("0").rstrip(".")
def jrec(d,keys): return "{"+",".join('"%s":%s'%(k,jnum(d.get(k,0))) for k in keys)+"}"

CAPK=["nuclear","coal","lng","oil","hydro","renewable","total"]
GENK=CAPK
REK=["solar","wind","smallhydro","bio","fuelcell","ocean","igcc"]

def main():
    if not EDITIONS:
        print("[ERROR] dl/ 에 kepco_YYYY_MM.xlsx 월보 엑셀이 없습니다 — 갱신 중단(기존 wolbo_data.js 유지)")
        sys.exit(1)
    print("자동 인식된 월보:", ", ".join("%d→%s"%(y,EDITIONS[y]) for y in sorted(EDITIONS)))
    CAP={};GEN={};CONS={};RE_G={};consyr={}
    for year,code in EDITIONS.items():
        wb=openpyxl.load_workbook(os.path.join(BASE,"dl","kepco_%s.xlsx"%code),read_only=True,data_only=True)
        CAP[year]=parse_form(sheet(wb,"5. 발전설비현황(행정구역"))
        GEN[year]=parse_form(sheet(wb,"10-1"))
        RE_G[year]=parse_re(sheet(wb,"9-1"))
        cons,cy=parse_cons(sheet(wb,"20."),year); CONS[year]=cons; consyr[year]=cy
        # merge 신재생 세분 into generation rec
        for s in GEN[year]:
            for k in REK: GEN[year][s][k]=RE_G[year].get(s,{}).get(k,0)
        print("%d: 설비 %d시도, 발전 %d시도, 소비 %d시도(기준연 %s), 전국발전 %s GWh, 태양광 %s"%(
            year,len(CAP[year]),len(GEN[year]),len(cons),consyr[year],
            format(round(sum(GEN[year][s]["total"] for s in GEN[year])),","),
            format(round(sum(GEN[year][s].get("solar",0) for s in GEN[year])),",")))

    _ly=max(EDITIONS); _lm=int(EDITIONS[_ly].split('_')[1])
    L=["// AUTO-GENERATED from 한전 전력통계월보 (dl/kepco_YYYY_MM.xlsx 자동 인식) — 시도별 설비·발전·소비 6버킷",
       "window.WOLBO = {",
       '  source:"한전 전력통계월보(행정구역별 발전설비/발전량/판매량)", url:"https://www.kepco.co.kr/home/customer/library/electricity-statistics/monthly-stats/boardList.do",',
       '  buckets:["nuclear","coal","lng","oil","hydro","renewable"],',
       '  re_detail:["solar","wind","smallhydro","bio","fuelcell","ocean","igcc"],',
       '  note:"발전=각 연도 12월 월보 누계(연간), %d=최신 월보(%d월) YTD. 설비=해당 월말 스냅샷.",'%(_ly,_lm),
       "  years:[%s], current_year:%d, current_months:%d, current_label:\"%d년 %d월 월보(누계 1~%d월)\","%(
           ",".join(map(str,sorted(EDITIONS))), max(EDITIONS),
           int(EDITIONS[max(EDITIONS)].split('_')[1]), max(EDITIONS),
           int(EDITIONS[max(EDITIONS)].split('_')[1]), int(EDITIONS[max(EDITIONS)].split('_')[1]))]
    def block(name,D,keys,reattach=False):
        b=[]
        for y in sorted(D,reverse=True):
            regs=[]
            for s in SIDO:
                if s not in D[y]: continue
                rec=D[y][s]; kk=keys+(REK if reattach else [])
                regs.append('"%s":%s'%(s,jrec(rec,kk)))
            b.append('    "%d":{%s}'%(y,", ".join(regs)))
        return "  %s:{\n%s\n  },"%(name,",\n".join(b))
    L.append(block("capacity",CAP,CAPK))
    L.append(block("generation",GEN,GENK,reattach=True))
    cb=[]
    for y in sorted(CONS,reverse=True):
        cb.append('    "%d":{%s}'%(y,", ".join('"%s":%s'%(s,jnum(CONS[y][s])) for s in SIDO if s in CONS[y])))
    L.append("  consumption:{\n"+",\n".join(cb)+"\n  }")
    L.append("};")
    # dashboard_standalone.html 의 WOLBO 블록을 직접 교체(단일 파일 유지 — 별도 빌드 불필요)
    js="\n".join(L)
    out=os.path.join(BASE,"dashboard_standalone.html")
    if not os.path.exists(out):
        print("[FAIL] dashboard_standalone.html 이 없습니다 — 중단"); sys.exit(1)
    with open(out,"r",encoding="utf-8") as fh: html=fh.read()
    marker="/* inlined: wolbo_data.js */"
    pat=re.compile(re.escape(marker)+r".*?</script>", re.S)
    if not pat.search(html):
        print("[FAIL] dashboard_standalone.html 에서 WOLBO 블록 마커를 못 찾음 — 중단"); sys.exit(1)
    html=pat.sub(lambda m: marker+"\n"+js+"\n</script>", html, count=1)
    with open(out,"w",encoding="utf-8") as fh: fh.write(html)
    print("\ndashboard_standalone.html WOLBO 데이터 갱신 완료 (",os.path.getsize(out),"bytes )")

if __name__=="__main__": main()
