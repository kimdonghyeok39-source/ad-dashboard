# -*- coding: utf-8 -*-
"""
플랫폼별 광고 성과 CSV + GA4 전환 CSV를 하나의 JSON으로 통합하는 스크립트.

사용법:
  python scripts/merge.py

[매체 데이터]  data/raw/<meta|google|naver|kakao>/ 폴더의 CSV
[GA4 데이터]  data/raw/ga4/ 폴더의 CSV (일자 × 세션 캠페인 × 콘텐츠 단위 내보내기)
[매핑 테이블] data/mapping.csv — 매체 캠페인명 ↔ UTM 값 연결

→ docs/data.json 으로 저장 (대시보드가 이 파일을 읽음)

매핑 테이블 형식 (data/mapping.csv):
  매체,매체캠페인명,UTM캠페인,매체그룹명,UTM콘텐츠
  - 매체/매체캠페인명/UTM캠페인 3개는 필수
  - 매체그룹명/UTM콘텐츠까지 채우면 그룹 단위로 정밀 매칭
  - 매체가 비어있는 행은 무시됨 (미매핑으로 기록)
"""

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
MAPPING_FILE = ROOT / "data" / "mapping.csv"
OUT_FILE = ROOT / "docs" / "data.json"

# ──────────────────────────────────────────────
# 매체 CSV 컬럼 매핑 (후보는 부분 일치 허용, 앞이 우선)
# ──────────────────────────────────────────────
COLUMN_MAP = {
    "meta": {
        "date": ["일", "보고 시작", "날짜", "day"],
        "campaign": ["캠페인 이름", "campaign name"],
        "group": ["광고 세트 이름", "광고세트", "ad set name"],
        "ad": ["광고 이름", "광고명", "ad name"],
        "device": ["노출 기기", "디바이스", "impression device"],
        "impressions": ["노출", "impressions"],
        "clicks": ["클릭(전체)", "링크 클릭", "클릭", "clicks"],
        "cost": ["지출 금액", "amount spent"],
        "conversions": ["구매", "결과", "purchases"],
        "revenue": ["구매 전환값", "전환값", "purchase value"],
    },
    "google": {
        "date": ["일", "날짜", "day"],
        "campaign": ["캠페인", "campaign"],
        "group": ["광고그룹", "광고 그룹", "ad group"],
        "ad": ["광고 이름", "광고 라벨", "광고 제목", "ad name"],
        "keyword": ["검색 키워드", "키워드", "keyword"],
        "device": ["기기", "디바이스", "device"],
        "impressions": ["노출수", "노출", "impressions"],
        "clicks": ["클릭수", "클릭", "clicks"],
        "cost": ["비용", "cost"],
        "conversions": ["전환수", "전환", "conversions"],
        "revenue": ["전환 가치", "conv. value"],
    },
    "naver": {
        "date": ["기준일", "날짜", "일별"],
        "campaign": ["캠페인이름", "캠페인 이름", "캠페인"],
        "group": ["광고그룹이름", "광고그룹 이름", "광고그룹"],
        "ad": ["소재", "소재명", "광고소재"],
        "keyword": ["키워드", "검색어"],
        "device": ["디바이스", "PC/모바일"],
        "impressions": ["노출수", "노출"],
        "clicks": ["클릭수", "클릭"],
        "cost": ["총비용", "비용"],
        "conversions": ["전환수", "전환"],
        "revenue": ["전환매출액", "전환 매출"],
    },
    "kakao": {
        "date": ["일자", "날짜", "일"],
        "campaign": ["캠페인", "캠페인명"],
        "group": ["광고그룹", "광고 그룹", "그룹"],
        "ad": ["소재", "소재명", "광고 이름"],
        "device": ["디바이스"],
        "impressions": ["노출수", "노출"],
        "clicks": ["클릭수", "클릭"],
        "cost": ["비용", "지출"],
        "conversions": ["전환수", "전환"],
        "revenue": ["전환 매출", "매출"],
    },
}

PLATFORM_LABEL = {"meta": "메타", "google": "구글", "naver": "네이버", "kakao": "카카오"}

# GA4 내보내기 CSV의 차원 컬럼 후보
GA4_DIMS = {
    "date": ["날짜", "일", "date"],
    "device": ["기기 카테고리", "디바이스", "device category"],
    "utm_campaign": ["세션 캠페인", "캠페인", "session campaign"],
    "utm_content": ["세션 수동 광고 콘텐츠", "광고 콘텐츠", "session manual ad content"],
    "utm_term": ["세션 수동 검색어", "검색어", "session manual term"],
}
GA4_IGNORE_METRICS = {"총계", "총합계", "totals", "total"}

DEVICE_ALIASES = [
    (("모바일", "mobile", "휴대전화", "휴대폰", "스마트폰"), "모바일"),
    (("pc", "컴퓨터", "데스크", "desktop"), "PC"),
    (("태블릿", "tablet"), "태블릿"),
]


def normalize_device(v: str) -> str:
    low = str(v).lower()
    if low in ("", "nan", "-", "--", "(not set)"):
        return ""
    for keys, label in DEVICE_ALIASES:
        if any(k in low for k in keys):
            return label
    return str(v)


def read_csv_safely(path: Path, mapping: dict) -> pd.DataFrame:
    """인코딩 자동 인식 + 헤더 행 자동 탐지 (구글 애즈 제목 줄 대응)."""
    text = None
    for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr", "utf-16"):
        try:
            text = path.read_bytes().decode(enc)
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
    if text is None:
        raise ValueError(f"인코딩을 인식할 수 없습니다: {path}")

    candidates = [c for cands in mapping.values() for c in cands]
    header_idx = 0
    for i, line in enumerate(text.splitlines()[:20]):
        hits = sum(1 for c in candidates if c in line)
        if hits >= 2:
            header_idx = i
            break

    # 구분자 자동 감지 (구글 애즈는 탭 구분 파일을 주는 경우가 있음)
    header_line = text.splitlines()[header_idx] if text.splitlines() else ""
    sep = "\t" if header_line.count("\t") > header_line.count(",") else ","

    import io
    return pd.read_csv(io.StringIO(text), skiprows=header_idx, sep=sep)


def find_column(columns, candidates):
    cols = {str(c).strip(): c for c in columns}
    for cand in candidates:
        if cand in cols:
            return cols[cand]
    for cand in candidates:
        for stripped, original in cols.items():
            if cand in stripped:
                return original
    return None


def to_number(series: pd.Series) -> pd.Series:
    cleaned = (
        series.astype(str)
        .str.replace(r"[^\d.\-]", "", regex=True)
        .replace({"": "0", "-": "0", "nan": "0"})
    )
    return pd.to_numeric(cleaned, errors="coerce").fillna(0)


def normalize_date(series: pd.Series) -> pd.Series:
    s = series.astype(str).str.strip().str.replace(r"[./]", "-", regex=True)
    s = s.str.rstrip("-")
    s = s.str.replace(r"^(\d{4})(\d{2})(\d{2})$", r"\1-\2-\3", regex=True)
    return pd.to_datetime(s, errors="coerce").dt.strftime("%Y-%m-%d")


# ──────────────────────────────────────────────
# 매체 데이터 처리
# ──────────────────────────────────────────────
def process_platform(platform: str) -> list:
    folder = RAW_DIR / platform
    if not folder.exists():
        return []

    mapping = COLUMN_MAP[platform]
    rows = []

    for csv_path in sorted(folder.glob("*.csv")):
        try:
            df = read_csv_safely(csv_path, mapping)
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
        for dim in ("group", "ad", "keyword", "device"):
            col = resolved.get(dim)
            out[dim] = df[col].astype(str).str.strip().replace("nan", "") if col else ""
        out["device"] = out["device"].map(normalize_device)
        for field in ("impressions", "clicks", "cost", "conversions", "revenue"):
            col = resolved.get(field)
            out[field] = to_number(df[col]) if col else 0

        out["platform"] = PLATFORM_LABEL[platform]
        out = out.dropna(subset=["date"])
        summary_words = {"합계", "총계", "전체", "total", "총합", "소계"}
        out = out[~out["campaign"].str.lower().isin(summary_words)]

        # 같은 파일 안에서 차원이 동일한 행(기여 설정·네트워크 분할 등으로
        # 쪼개진 행)은 합산 — 버리면 합계가 모자라게 됨
        dims = ["date", "campaign", "group", "ad", "keyword", "device", "platform"]
        metrics = ["impressions", "clicks", "cost", "conversions", "revenue"]
        out = out.groupby(dims, as_index=False)[metrics].sum()

        rows.append(out)
        print(f"  {csv_path.name}: {len(out)}행 처리")

    if not rows:
        return []

    merged = pd.concat(rows, ignore_index=True)
    merged = merged.drop_duplicates(
        subset=["date", "campaign", "group", "ad", "keyword", "device"], keep="last"
    )
    return merged.to_dict(orient="records")


# ──────────────────────────────────────────────
# 매핑 테이블 + GA4 데이터 처리
# ──────────────────────────────────────────────
def load_mapping(campaign_platform):
    """data/mapping.csv → (캠페인 매핑, 그룹 매핑)

    매체 칸이 비어 있으면, 매체 데이터에 있는 캠페인명으로 매체를 자동 추론합니다.
    campaign_platform: {매체캠페인명: set(매체들)} — 매체 데이터에서 생성
    """
    if not MAPPING_FILE.exists():
        return {}, {}, {}
    try:
        mdf = read_csv_safely(MAPPING_FILE, {"_": ["UTM캠페인", "매체캠페인명"]})
    except Exception as e:
        print(f"[경고] mapping.csv 읽기 실패: {e}", file=sys.stderr)
        return {}, {}, {}

    for col in ("매체", "매체캠페인명", "UTM캠페인", "매체그룹명", "UTM콘텐츠"):
        if col not in mdf.columns:
            mdf[col] = ""
    mdf = mdf.fillna("").astype(str)
    for col in mdf.columns:
        mdf[col] = mdf[col].str.strip()

    camp_map, grp_map, grp_by_content = {}, {}, {}
    valid_platforms = set(PLATFORM_LABEL.values())
    for _, r in mdf.iterrows():
        if not r["매체캠페인명"] or not r["UTM캠페인"]:
            continue

        platform = r["매체"]
        if platform and platform not in valid_platforms:
            print(f"  [경고] mapping.csv: 알 수 없는 매체 '{platform}' (메타/구글/네이버/카카오 중 하나여야 함)", file=sys.stderr)
            continue
        if not platform:
            # 매체 자동 추론: 매체 데이터에서 같은 캠페인명 검색
            found = campaign_platform.get(r["매체캠페인명"], set())
            if len(found) == 1:
                platform = next(iter(found))
            elif len(found) > 1:
                print(f"  [경고] mapping.csv: 캠페인 '{r['매체캠페인명']}'이(가) 여러 매체({', '.join(sorted(found))})에 있어 매체 칸을 채워야 합니다", file=sys.stderr)
                continue
            else:
                print(f"  [경고] mapping.csv: 캠페인 '{r['매체캠페인명']}'을(를) 매체 데이터에서 찾지 못했습니다 (이름이 정확히 같은지 확인)", file=sys.stderr)
                continue

        camp_map[r["UTM캠페인"]] = (platform, r["매체캠페인명"])
        if r["UTM콘텐츠"]:
            grp_map[(r["UTM캠페인"], r["UTM콘텐츠"])] = (platform, r["매체캠페인명"], r["매체그룹명"])
            # 보조 인덱스: UTM캠페인 값이 정확하지 않아도
            # (매체, 매체캠페인명, UTM콘텐츠) 조합으로 그룹 매칭
            grp_by_content[(platform, r["매체캠페인명"], r["UTM콘텐츠"])] = r["매체그룹명"]
    return camp_map, grp_map, grp_by_content


def process_ga4(campaign_platform, ad_index, ad_group):
    folder = RAW_DIR / "ga4"
    if not folder.exists():
        return [], {}

    camp_map, grp_map, grp_by_content = load_mapping(campaign_platform)
    frames = []

    for csv_path in sorted(folder.glob("*.csv")):
        try:
            df = read_csv_safely(csv_path, GA4_DIMS)
        except Exception as e:
            print(f"  [경고] {csv_path.name} 읽기 실패: {e}", file=sys.stderr)
            continue

        resolved = {field: find_column(df.columns, cands) for field, cands in GA4_DIMS.items()}
        if not resolved["date"] or not resolved["utm_campaign"]:
            print(f"  [경고] {csv_path.name}: 날짜/세션 캠페인 컬럼을 찾지 못해 건너뜀", file=sys.stderr)
            continue

        dim_cols = [c for c in resolved.values() if c]
        event_cols = [
            c for c in df.columns
            if c not in dim_cols and str(c).strip().lower() not in GA4_IGNORE_METRICS
        ]

        out = pd.DataFrame()
        out["date"] = normalize_date(df[resolved["date"]])
        out["utm_campaign"] = df[resolved["utm_campaign"]].astype(str).str.strip()
        out["utm_content"] = (
            df[resolved["utm_content"]].astype(str).str.strip().replace("nan", "")
            if resolved["utm_content"] else ""
        )
        out["utm_term"] = (
            df[resolved["utm_term"]].astype(str).str.strip().replace("nan", "")
            if resolved["utm_term"] else ""
        )
        out["device"] = (
            df[resolved["device"]].map(normalize_device) if resolved["device"] else ""
        )
        for ev in event_cols:
            out[ev] = to_number(df[ev])

        out = out.dropna(subset=["date"])
        frames.append((out, event_cols))
        print(f"  {csv_path.name}: {len(out)}행, 이벤트 {len(event_cols)}종 처리")

    if not frames:
        return [], {}

    all_events = sorted({ev for _, evs in frames for ev in evs})
    ga4 = pd.concat([f for f, _ in frames], ignore_index=True)
    for ev in all_events:
        if ev not in ga4.columns:
            ga4[ev] = 0
        ga4[ev] = ga4[ev].fillna(0)

    ga4 = ga4.groupby(["date", "utm_campaign", "utm_content", "utm_term", "device"], as_index=False)[all_events].sum()

    records, unmapped = [], {}
    for _, r in ga4.iterrows():
        key2 = (r["utm_campaign"], r["utm_content"])
        direct = campaign_platform.get(r["utm_campaign"], set())
        if key2 in grp_map:
            platform, campaign, group = grp_map[key2]
        elif r["utm_campaign"] in camp_map:
            platform, campaign = camp_map[r["utm_campaign"]]
            group = ""
        elif len(direct) == 1:
            # UTM캠페인 값이 매체 캠페인명과 완전히 같으면 매핑 없이 자동 연결
            platform = next(iter(direct))
            campaign = r["utm_campaign"]
            group = ""
        else:
            total = int(sum(r[ev] for ev in all_events))
            if total > 0 and r["utm_campaign"] not in ("(not set)", "(direct)", "(organic)"):
                unmapped[r["utm_campaign"]] = unmapped.get(r["utm_campaign"], 0) + total
            continue

        if not group and r["utm_content"]:
            group = grp_by_content.get((platform, campaign, r["utm_content"]), "")

        events = {ev: int(r[ev]) for ev in all_events if r[ev] > 0}
        if not events:
            continue

        # 소재 자동 매칭: utm_term이 해당 캠페인의 소재명과 정확히 같으면 연결
        ad = ""
        term = r.get("utm_term", "")
        if term and term in ad_index.get((platform, campaign), set()):
            ad = term
            if not group:
                group = ad_group.get((platform, campaign, ad), "")

        records.append({
            "date": r["date"], "platform": platform, "campaign": campaign,
            "group": group, "ad": ad, "device": r["device"], "events": events,
        })

    return records, unmapped


def main():
    all_rows = []
    for platform in COLUMN_MAP:
        print(f"[{PLATFORM_LABEL[platform]}] 처리 중...")
        all_rows.extend(process_platform(platform))
    all_rows.sort(key=lambda r: (r["date"], r["platform"], r["campaign"]))

    campaign_platform = {}
    ad_index = {}     # (매체, 캠페인) → 소재명 집합
    ad_group = {}     # (매체, 캠페인, 소재) → 그룹명
    for r in all_rows:
        campaign_platform.setdefault(r["campaign"], set()).add(r["platform"])
        if r.get("ad"):
            key = (r["platform"], r["campaign"])
            ad_index.setdefault(key, set()).add(r["ad"])
            if r.get("group"):
                ad_group[(r["platform"], r["campaign"], r["ad"])] = r["group"]

    print("[GA4] 처리 중...")
    ga4_records, unmapped = process_ga4(campaign_platform, ad_index, ad_group)
    if unmapped:
        print("\n  ⚠️ 매핑되지 않은 UTM 캠페인 (전환수 순) — data/mapping.csv에 추가해 주세요:")
        for utm, total in sorted(unmapped.items(), key=lambda x: -x[1])[:20]:
            print(f"    - {utm}  (전환 {total})")

    payload = {
        "updated_at": pd.Timestamp.now(tz="Asia/Seoul").strftime("%Y-%m-%d %H:%M"),
        "rows": all_rows,
        "ga4": ga4_records,
    }

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print(f"\n완료: 매체 {len(all_rows)}행 + GA4 {len(ga4_records)}행 → {OUT_FILE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
