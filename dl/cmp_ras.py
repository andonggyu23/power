# -*- coding: utf-8 -*-
import sys; sys.stdout.reconfigure(encoding='utf-8')
import json, re, openpyxl, os
base=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
t=open(os.path.join(base,'power_data.js'),encoding='utf-8').read()

def block(key):
    i=t.find(key+':'); i=t.find('{',i); depth=0
    for j in range(i,len(t)):
        if t[j]=='{': depth+=1
        elif t[j]=='}':
            depth-=1
            if depth==0: return json.loads(t[i:j+1])
PD_cap=block('capacity_by_year')
PD_gt=block('generation_total_by_year')
PD_gn=block('generation_national_by_fuel_by_year')
Y='2024'
SIDO=["서울","부산","대구","인천","광주","대전","울산","세종","경기","강원","충북","충남","전북","전남","경북","경남","제주"]
FO=["nuclear","coal","gas","renewable","etc"]
cap=PD_cap[Y]; gt=PD_gt[Y]; gn=PD_gn[Y]

# RAS (대시보드 genEst 재현)
capF={f:sum((cap[s].get(f,0) or 0) for s in SIDO) for f in FO}
M={s:{f:(cap[s].get(f,0) or 0)*(gn.get(f,0)/capF[f] if capF[f]>0 else 0) for f in FO} for s in SIDO}
Grow=sum(gt[s] for s in SIDO); Gcol=sum(gn.get(f,0) for f in FO)
colT={f:gn.get(f,0)*Grow/(Gcol or 1) for f in FO}
for _ in range(80):
    for s in SIDO:
        rs=sum(M[s].values()) or 1; k=gt[s]/rs
        for f in FO: M[s][f]*=k
    for f in FO:
        cs=sum(M[s][f] for s in SIDO) or 1; k=colT[f]/cs
        for s in SIDO: M[s][f]*=k

# KEPCO 8-2 (한전 실측, MWh->GWh)
wb=openpyxl.load_workbook(os.path.join(base,'dl','kepco94.xlsx'),read_only=True,data_only=True)
ws=wb['8-2. 행정구역별 발전설비 및 발전량']
rows=list(ws.iter_rows(values_only=True))
def short(name):
    if not name: return None
    n=re.sub(r'[A-Za-z()0-9]','',str(name)).strip().replace(' ','')
    for s in SIDO:
        if n.startswith(s): return s
    return None
HJ={}
for r in rows:
    s=short(r[0])
    if not s or len(r)<19 or r[10] is None: continue
    g=lambda i:(r[i] or 0)/1000.0
    HJ[s]={'nuclear':g(10),'coal':g(11)+g(12),'gas':g(13),'renewable':g(14),'etc':g(15)+g(16)+g(17),'total':g(18)}

print('한전 파싱 시도수:',len(HJ),'/ 누락:',[s for s in SIDO if s not in HJ])

print('\n=== 시도 총발전량(GWh): 한전 vs EPSIS(060104=RAS 행마진) ===')
te=ta=0
for s in SIDO:
    if s not in HJ: continue
    a=HJ[s]['total']; b=gt[s]; te+=abs(a-b); ta+=a
    print('  %-3s 한전 %9.0f  EPSIS %9.0f  Δ %+8.0f (%+5.1f%%)'%(s,a,b,a-b,(a-b)/(a or 1)*100))
print('  >> 시도총량 평균절대오차 %.0f GWh, 전국합대비 %.1f%%'%(te/len(HJ),te/ta*100))

print('\n=== 발전원 전국합: RAS vs 한전(GWh) ===')
for f in FO:
    ras=sum(M[s][f] for s in SIDO); hj=sum(HJ[s][f] for s in HJ)
    print('  %-10s RAS %9.0f  한전 %9.0f  Δ %+8.0f'%(f,ras,hj,ras-hj))

print('\n=== 셀단위 오차 RAS vs 한전 (발전원별 집계) ===')
for f in FO:
    errs=[abs(M[s][f]-HJ[s][f]) for s in HJ]
    tot=sum(HJ[s][f] for s in HJ) or 1
    print('  %-10s MAE %7.0f GWh   합계대비 %5.1f%%   최대셀 %7.0f'%(f,sum(errs)/len(HJ),sum(errs)/tot*100,max(errs)))

print('\n=== 최악 오차 셀 top10 (|RAS-한전| GWh) ===')
cells=[(s,f,M[s][f],HJ[s][f]) for s in HJ for f in FO]
cells.sort(key=lambda x:-abs(x[2]-x[3]))
for s,f,r,h in cells[:10]:
    pct=(r-h)/(h or 1)*100
    print('  %-3s %-10s RAS %8.0f  한전 %8.0f  Δ %+8.0f (%+6.0f%%)'%(s,f,r,h,r-h,pct))

# 전체 정합 지표
allerr=sum(abs(M[s][f]-HJ[s][f]) for s in HJ for f in FO)
alltot=sum(HJ[s][f] for s in HJ for f in FO)
print('\n=== 전체 셀 정합 ===')
print('  총 발전량(한전,5버킷합) {:,.0f} GWh'.format(alltot))
print('  RAS 총 절대오차 {:,.0f} GWh = 전체의 {:.1f}%'.format(allerr,allerr/alltot*100))
print('\n=== 시도별 RAS 배분 절대오차율(해당 시도 총량 대비) ===')
rr=[]
for s in HJ:
    e=sum(abs(M[s][f]-HJ[s][f]) for f in FO); tot=HJ[s]['total'] or 1
    rr.append((e/tot*100,s,e,tot))
for p,s,e,tot in sorted(rr,reverse=True):
    print('  %-3s %5.1f%%  (오차 %6.0f / 총 %7.0f GWh)'%(s,p,e,tot))
