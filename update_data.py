# -*- coding: utf-8 -*-
# =====================================================================
#  update_data.py — 전력 대시보드 데이터 자동 갱신 오케스트레이터
# ---------------------------------------------------------------------
#  하는 일:
#   1) 현재 데이터 JS 백업 (data_backup/)
#   2) fetch_data.py   실행 → power_data.js · consumption_data.js (EPSIS 온라인, 완전자동)
#   3) kepco_wolbo.py  실행 → wolbo_data.js (dl/ 의 월보 엑셀에서 재생성)
#   4) 결과 파일 검증(마커·크기) → 손상 시 백업 자동 복원
#   5) update_log.txt 에 타임스탬프·결과 기록
#
#  수동 실행:  python update_data.py
#  자동 실행:  Windows 작업 스케줄러에 등록(매월 1회). 등록은 README_auto_update.md 참고.
#
#  ※ 월보(wolbo)는 새 호차 엑셀을 dl\kepco_YYYY_MM.xlsx 로 받아 넣고
#     kepco_wolbo.py 의 EDITIONS 에 추가해야 "새 달"이 반영됨(엑셀 자동수집 아님).
# =====================================================================
import os
import sys
import shutil
import subprocess
import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(BASE, "update_log.txt")
PY = sys.executable  # 현재 파이썬으로 하위 스크립트 실행 (스케줄러 환경에서도 동일)


def log(m):
    line = "%s  %s" % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), m)
    print(line)
    try:
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


def valid(fn, marker):
    p = os.path.join(BASE, fn)
    if not os.path.exists(p) or os.path.getsize(p) < 500:
        return False
    try:
        with open(p, "r", encoding="utf-8") as fh:
            return marker in fh.read()
    except Exception:
        return False


def run(script):
    try:
        r = subprocess.run([PY, os.path.join(BASE, script)], cwd=BASE,
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=600)
        if r.returncode != 0:
            log("[WARN] %s 종료코드 %d" % (script, r.returncode))
            err = (r.stderr or "").strip()
            if err:
                log("   " + err.splitlines()[-1])
        return r.returncode == 0
    except Exception as e:
        log("[WARN] %s 실행 예외: %s" % (script, e))
        return False


def restore(bak, fn):
    b = os.path.join(bak, fn + ".bak")
    if os.path.exists(b):
        shutil.copy2(b, os.path.join(BASE, fn))
        log("   → %s 백업 복원" % fn)


def main():
    log("================ 데이터 갱신 시작 (%s) ================" % PY)
    failed = False

    # 1) 백업
    bak = os.path.join(BASE, "data_backup")
    os.makedirs(bak, exist_ok=True)
    targets = ["power_data.js", "consumption_data.js", "wolbo_data.js"]
    for f in targets:
        p = os.path.join(BASE, f)
        if os.path.exists(p):
            shutil.copy2(p, os.path.join(bak, f + ".bak"))
    log("[백업] data_backup/ 에 현재 JS 보관")

    # 2) EPSIS (온라인, 완전 자동)
    log("[1/2] fetch_data.py (EPSIS) 실행...")
    run("fetch_data.py")
    for fn, mk in (("power_data.js", "window.POWER_DATA"),
                   ("consumption_data.js", "window.CONSUMPTION_DATA")):
        if valid(fn, mk):
            log("[OK]   %s 검증 통과" % fn)
        else:
            log("[FAIL] %s 손상/누락" % fn)
            restore(bak, fn)
            failed = True

    # 3) 월보 (로컬 엑셀 → wolbo_data.js)
    log("[2/2] kepco_wolbo.py (월보 엑셀) 실행...")
    run("kepco_wolbo.py")
    if valid("wolbo_data.js", "window.WOLBO"):
        log("[OK]   wolbo_data.js 검증 통과")
    else:
        log("[FAIL] wolbo_data.js 손상/누락")
        restore(bak, "wolbo_data.js")
        failed = True

    log("================ 갱신 %s ================\n" %
        ("종료: 경고/실패 있음(위 로그 확인)" if failed else "완료: 정상"))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
