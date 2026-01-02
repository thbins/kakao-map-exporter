import os
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv

load_dotenv()

KAKAO_REST_API_KEY = os.getenv("KAKAO_REST_API_KEY", "").strip()
if not KAKAO_REST_API_KEY:
    raise RuntimeError("KAKAO_REST_API_KEY가 없습니다. .env/환경변수 확인")

HEADERS = {"Authorization": f"KakaoAK {KAKAO_REST_API_KEY}"}

KEYWORD_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
ADDRESS_URL = "https://dapi.kakao.com/v2/local/search/address.json"


def keyword_search(
    query: str,
    page: int = 1,
    size: int = 15,
    sort: str = "accuracy",
    x: Optional[float] = None,
    y: Optional[float] = None,
    radius: Optional[int] = None,
    rect: Optional[str] = None,
) -> Dict[str, Any]:
    params: Dict[str, Any] = {"query": query, "page": page, "size": size, "sort": sort}
    if rect:
        params["rect"] = rect
    else:
        if x is not None and y is not None:
            params["x"] = str(x)
            params["y"] = str(y)
        if radius is not None:
            params["radius"] = int(radius)

    r = requests.get(KEYWORD_URL, headers=HEADERS, params=params, timeout=20)
    r.raise_for_status()
    return r.json()


def address_search(query: str, page: int = 1, size: int = 10) -> Dict[str, Any]:
    params = {"query": query, "page": page, "size": size}
    r = requests.get(ADDRESS_URL, headers=HEADERS, params=params, timeout=20)
    r.raise_for_status()
    return r.json()


def geocode_location(location_query: str) -> Tuple[float, float]:
    """
    지역명/주소 -> (x=경도, y=위도)
    1) 주소 검색
    2) 실패하면 키워드 검색(장소명) fallback
    """
    q = (location_query or "").strip()
    if not q:
        raise ValueError("지역명을 입력하세요.")

    data = address_search(q)
    docs = data.get("documents", [])
    if docs:
        addr = docs[0].get("address") or {}
        x = addr.get("x")
        y = addr.get("y")
        if x and y:
            return float(x), float(y)

    data2 = keyword_search(query=q, page=1, size=1)
    docs2 = data2.get("documents", [])
    if docs2:
        x = docs2[0].get("x")
        y = docs2[0].get("y")
        if x and y:
            return float(x), float(y)

    raise ValueError(f"'{q}' 좌표를 찾지 못했습니다. 더 구체적으로 입력해 주세요.")


def bbox_from_center_radius(x: float, y: float, radius_m: int) -> Tuple[float, float, float, float]:
    """중심좌표 + 반경(m) -> bbox 근사"""
    import math

    dlat = radius_m / 111_320.0
    lat_rad = math.radians(y)
    denom = 111_320.0 * max(0.1, math.cos(lat_rad))
    dlon = radius_m / denom

    return (x - dlon, y - dlat, x + dlon, y + dlat)


def _iter_tiles(bbox: Tuple[float, float, float, float], tile_deg: float):
    """bbox를 tile_deg 단위로 잘라 (rect, tile_index, total_tiles) 형태로 순회하기 위한 제너레이터"""
    min_x, min_y, max_x, max_y = bbox
    if min_x >= max_x or min_y >= max_y:
        raise ValueError("bbox가 올바르지 않습니다. (min_x < max_x, min_y < max_y)")

    # 전체 타일 개수 계산(진행률용)
    nx = int(((max_x - min_x) / tile_deg) + (1 if (max_x - min_x) % tile_deg > 0 else 0))
    ny = int(((max_y - min_y) / tile_deg) + (1 if (max_y - min_y) % tile_deg > 0 else 0))
    total = max(1, nx * ny)

    idx = 0
    y = min_y
    while y < max_y:
        y2 = min(y + tile_deg, max_y)
        x = min_x
        while x < max_x:
            x2 = min(x + tile_deg, max_x)
            rect = f"{x},{y},{x2},{y2}"
            idx += 1
            yield rect, idx, total
            x = x2
        y = y2


def fetch_places_tiled(
    query: str,
    bbox: Tuple[float, float, float, float],  # (min_x, min_y, max_x, max_y)
    tile_deg: float = 0.01,
    sleep_sec: float = 0.25,
    max_pages_per_tile: int = 45,
    stop_event: Optional[Any] = None,
    on_progress: Optional[Callable[[int, int, int], None]] = None,
) -> List[Dict[str, Any]]:
    """
    bbox를 타일로 쪼개 rect 검색 반복 -> 타일 내부 페이징 -> id로 중복 제거
    + stop_event로 중지 지원
    + on_progress(tile_idx, total_tiles, total_collected) 콜백 지원
    """
    by_id: Dict[str, Dict[str, Any]] = {}

    for rect, tile_idx, total_tiles in _iter_tiles(bbox, tile_deg):
        if stop_event is not None and stop_event.is_set():
            break

        page = 1
        while True:
            if stop_event is not None and stop_event.is_set():
                break

            data = keyword_search(query=query, page=page, size=15, rect=rect)
            docs = data.get("documents", [])

            for d in docs:
                pid = d.get("id")
                if not pid:
                    continue
                by_id[pid] = {
                    "id": pid,
                    "이름": d.get("place_name", ""),
                    "도로명주소": d.get("road_address_name", ""),
                    "지번주소": d.get("address_name", ""),
                    "전화번호": d.get("phone", ""),
                    "place_url": d.get("place_url", ""),
                    "x": d.get("x", ""),
                    "y": d.get("y", ""),
                }

            # 진행 콜백(타일 n/m, 누적 수집 수)
            if on_progress is not None:
                on_progress(tile_idx, total_tiles, len(by_id))

            meta = data.get("meta", {})
            if meta.get("is_end", True) or page >= max_pages_per_tile:
                break

            page += 1
            time.sleep(sleep_sec)

        if stop_event is not None and stop_event.is_set():
            break

        time.sleep(sleep_sec)

    return list(by_id.values())