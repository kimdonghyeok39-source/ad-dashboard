# -*- coding: utf-8 -*-
"""
플랫폼별 광고 성과 CSV를 하나의 JSON으로 통합하는 스크립트.

사용법:
  python scripts/merge.py

data/raw/<플랫폼>/ 폴더의 모든 CSV를 읽어
docs/data.json 으로 저장합니다 (대시보드가 이 파일을 읽음).

플랫폼에서 내려받은 CSV의 컬럼명이 아래 COLUMN_MAP과 다르면
해당 플랫폼의 후보 목록에 실제 컬럼명을 추가해 주세요.
"""

import json
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
OUT_FILE = ROOT / "docs" / "data.json"

# 각 표준 필드에 대해, 플랫폼 CSV에서 나타날 수 있는 컬럼명 후보들.
# 후보는 부분 일치(포함)로도 매칭됩니다. 앞에 있는 후보가 우선합니다.
COLUMN_MAP = {
    "meta": {
        "date": ["일", "보고 시작", "날짜", "day"],
        "campaign": ["캠페인 이름", "campaign name"],
        "impressions": ["노출", "impressions"],
        "clicks": ["클릭(전체)", "링크 클릭", "클릭", "clicks"],
        "cost": ["지출 금액", "amount spent"],
        "conversions": ["구매", "결과", "purchases"],
        "revenue": ["구매 전환값", "전환값", "purchase value"],
    },
    "google": {
        "date": ["일", "날짜", "day"],
        "campaign": ["캠페인", "campaign"],
        "impressions": ["노출수", "노출", "impressions"],
        "clicks": ["클릭수", "클릭", "clicks"],
        "cost": ["비용", "cost"],
        "conversions": ["전환수", "전환", "conversions"],
        "revenue": ["전환 가치", "conv. value"],
    },
    "naver": {
        "date": ["기준일", "날짜", "일별"],
        "campaign": ["캠페인이름", "캠페인 이름", "캠페인"],
        "impressions": ["노출수", "노출"],
        "clicks": ["클릭수", "클릭"],
        "cost": ["총비용", "비용"],
        "conversions": ["전환수", "전환"],
        "revenue": ["전환매출액", "전환 매출"],
    },
    "kakao": {
        "date": ["일자", "날짜", "일"],
        "campaign": ["캠페인", "캠페인명"],
        "impressions": ["노출수", "노출"],
        "clicks": ["클릭수", "클릭"],
        "cost": ["비용", "지출"],
        "conversions": ["전환수", "전환"],
        "revenue": ["전환 매출", "매출"],
    },
}

PLATFORM_LABEL = {
    "meta": "메타",
    "google": "구글",
    "naver": "네이버",
    "kakao": "카카오",
}


def read_csv_safely(path: Path) -> pd.DataFrame:
    """네이버/카카오 CSV는 cp949 인코딩인 경우가 많아 순차적으로 시도."""
    for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
        try:
            return pd.read_csv(path, encoding=enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
    raise ValueError(f"인코딩을 인식할 수 없습니다: {path}")


def find_column(columns, candidates):
    """후보 목록에서 일치하는 컬럼명 탐색 (정확 일치 → 부분 일치)."""
    cols = {c.strip(): c for c in columns}
    for cand in candidates:
        if cand in cols:
            return cols[cand]
    for cand in candidates:
        for stripped, original in cols.items():
            if cand in stripped:
                return original
    return None


def to_number(series: pd.Series) -> pd.Series:
    """'1,234원' 같은 문자열을 숫자로 변환."""
    cleaned = (
        series.astype(str)
        .str.replace(r"[^\d.\-]", "", regex=True)
        .replace({"": "0", "-": "0", "nan": "0"})
    )
    return pd.to_numeric(cleaned, errors="coerce").fillna(0)


def normalize_date(series: pd.Series) -> pd.Series:
    """2026-06-01, 2026.06.01, 20260601 등 다양한 형식을 YYYY-MM-DD로 통일."""
    s = series.astype(str).str.strip().str.replace(r"[./]", "-", regex=True)
    s = s.str.rstrip("-")  # 네이버 '2026.05.25.' 형식의 끝 구분자 제거
    s = s.str.replace(r"^(\d{4})(\d{2})(\d{2})$", r"\1-\2-\3", regex=True)
    return pd.to_datetime(s, errors="coerce").dt.strftime("%Y-%m-%d")


def process_platform(platform: str) -> list[dict]:
    folder = RAW_DIR / platform
    if not folder.exists():
        return []

    mapping = COLUMN_MAP[platform]
    rows = []

    for csv_path in sorted(folder.glob("*.csv")):
        try:
            df = read_csv_safely(csv_path)
        except Exception as e:
            print(f"  [경고] {csv_path.name} 읽기 실패: {e}", file=sys.stderr)
            continue

        resolved = {field: find_column(df.columns, cands) for field, cands in mapping.items()}

        missing = [f for f in ("date", "campaign", "cost") if not resolved[f]]
        if missing:
            print(
                f"  [경고] {csv_path.name}: 필수 컬럼을 찾지 못해 건너뜀 "
                f"(누락: {missing} / 파일 컬럼: {list(df.columns)})",
                file=sys.stderr,
            )
            continue

        out = pd.DataFrame()
        out["date"] = normalize_date(df[resolved["date"]])
        out["campaign"] = df[resolved["campaign"]].astype(str).str.strip()
        for field in ("impressions", "clicks", "cost", "conversions", "revenue"):
            col = resolved[field]
            out[field] = to_number(df[col]) if col else 0

        out["platform"] = PLATFORM_LABEL[platform]
        out = out.dropna(subset=["date"])
        # '합계' 같은 요약 행 제거 (캠페인명 전체가 요약 단어일 때만)
        summary_words = {"합계", "총계", "전체", "total", "총합", "소계"}
        out = out[~out["campaign"].str.lower().isin(summary_words)]
        rows.append(out)
        print(f"  {csv_path.name}: {len(out)}행 처리")

    if not rows:
        return []

    merged = pd.concat(rows, ignore_index=True)
    # 같은 날짜+캠페인이 여러 파일에 중복되면 마지막 파일 기준으로 유지
    merged = merged.drop_duplicates(subset=["date", "campaign"], keep="last")
    return merged.to_dict(orient="records")


def main():
    all_rows = []
    for platform in COLUMN_MAP:
        print(f"[{PLATFORM_LABEL[platform]}] 처리 중...")
        all_rows.extend(process_platform(platform))

    all_rows.sort(key=lambda r: (r["date"], r["platform"], r["campaign"]))

    payload = {
        "updated_at": pd.Timestamp.now(tz="Asia/Seoul").strftime("%Y-%m-%d %H:%M"),
        "rows": all_rows,
    }

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print(f"\n완료: {len(all_rows)}행 → {OUT_FILE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
