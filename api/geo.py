# -*- coding: utf-8 -*-
"""地理服务: 城市名 → 经纬度/IANA时区(拍板项4, 数据源选型报备Owner)。

数据源(首选): GeoNames cities5000(全球人口≥5000的城市, 许可 CC-BY 4.0, 报备Owner)。
- 首次初始化时下载 https://download.geonames.org/export/dump/cities5000.zip 到 data/,
  解析后装入 SQLite geo_cities 表; 之后完全离线, 运行期查询零外网调用。
- 授权边界: 本模块只允许访问上述这一个 geonames.org 文件, 不访问任何其他外部服务。

数据源(兜底): 若下载失败, 使用内置约68个主要城市表(中国省会+直辖市+港澳台+全球
大都市), 坐标为常识值(精度约0.01度), 时区为 IANA 标准名。实际使用的数据源与条数
写入 geo_meta 表, 并随每次搜索响应的 meta 字段返回, 便于前端与Owner核查。

搜索规则: 精确匹配(name/asciiname/别名)优先, 前缀匹配次之, 同级按人口降序,
最多返回10条 {city, country, lat, lng, timezone}, timezone 直接给 IANA 名,
方便前端填排盘契约的 timezone 字段。
"""
import io
import sqlite3
import threading
import urllib.request
import zipfile
from pathlib import Path

from . import storage

GEONAMES_URL = "https://download.geonames.org/export/dump/cities5000.zip"
_ZIP_NAME = "cities5000.zip"
_TXT_NAME = "cities5000.txt"
_DOWNLOAD_TIMEOUT = 60          # 秒
_SOURCE_GEONAMES = "GeoNames cities5000 (CC-BY 4.0)"
_SOURCE_BUILTIN = "内置主要城市表(下载GeoNames失败时兜底, 坐标常识值±0.01度)"

# CN→EN city name mapping for international city search
_CITY_CN_MAP = {
    "纽约": "New York",
    "纽约市": "New York City",
    "伦敦": "London",
    "东京": "Tokyo",
    "巴黎": "Paris",
    "柏林": "Berlin",
    "悉尼": "Sydney",
    "莫斯科": "Moscow",
    "首尔": "Seoul",
    "曼谷": "Bangkok",
    "新加坡": "Singapore",
    "吉隆坡": "Kuala Lumpur",
    "迪拜": "Dubai",
    "罗马": "Rome",
    "米兰": "Milan",
    "马德里": "Madrid",
    "巴塞罗那": "Barcelona",
    "阿姆斯特丹": "Amsterdam",
    "布鲁塞尔": "Brussels",
    "日内瓦": "Geneva",
    "苏黎世": "Zurich",
    "维也纳": "Vienna",
    "布拉格": "Prague",
    "华沙": "Warsaw",
    "布达佩斯": "Budapest",
    "伊斯坦布尔": "Istanbul",
    "雅典": "Athens",
    "开罗": "Cairo",
    "拉各斯": "Lagos",
    "内罗毕": "Nairobi",
    "开普敦": "Cape Town",
    "约翰内斯堡": "Johannesburg",
    "孟买": "Mumbai",
    "德里": "Delhi",
    "新德里": "New Delhi",
    "班加罗尔": "Bangalore",
    "雅加达": "Jakarta",
    "马尼拉": "Manila",
    "河内": "Hanoi",
    "胡志明": "Ho Chi Minh",
    "多伦多": "Toronto",
    "温哥华": "Vancouver",
    "蒙特利尔": "Montreal",
    "洛杉矶": "Los Angeles",
    "旧金山": "San Francisco",
    "芝加哥": "Chicago",
    "波士顿": "Boston",
    "华盛顿": "Washington",
    "迈阿密": "Miami",
    "西雅图": "Seattle",
    "休斯顿": "Houston",
    "达拉斯": "Dallas",
    "圣保罗": "São Paulo",
    "里约": "Rio de Janeiro",
    "布宜诺斯": "Buenos Aires",
    "墨西哥城": "Mexico City",
    "利马": "Lima",
    "圣地亚哥": "Santiago",
    "波哥大": "Bogota",
}

_init_lock = threading.Lock()
_meta_cache = None              # {"source":…, "count":…}

# 内置兜底城市表: (name中文优先, asciiname, 别名逗号串, lat, lng, country, timezone, population)
# 坐标取常识值(约0.01度精度); 中国大陆统一 Asia/Shanghai(含乌鲁木齐, 官方时区)。
_BUILTIN_CITIES = [
    ("北京", "Beijing", "北京,Beijing,Peking", 39.90, 116.41, "CN", "Asia/Shanghai", 21540000),
    ("上海", "Shanghai", "上海,Shanghai", 31.23, 121.47, "CN", "Asia/Shanghai", 24870000),
    ("天津", "Tianjin", "天津,Tianjin", 39.13, 117.20, "CN", "Asia/Shanghai", 13870000),
    ("重庆", "Chongqing", "重庆,Chongqing", 29.56, 106.55, "CN", "Asia/Shanghai", 32050000),
    ("石家庄", "Shijiazhuang", "石家庄,Shijiazhuang", 38.04, 114.51, "CN", "Asia/Shanghai", 11030000),
    ("太原", "Taiyuan", "太原,Taiyuan", 37.87, 112.55, "CN", "Asia/Shanghai", 5300000),
    ("呼和浩特", "Hohhot", "呼和浩特,Hohhot", 40.84, 111.75, "CN", "Asia/Shanghai", 3450000),
    ("沈阳", "Shenyang", "沈阳,Shenyang", 41.80, 123.43, "CN", "Asia/Shanghai", 9070000),
    ("长春", "Changchun", "长春,Changchun", 43.88, 125.32, "CN", "Asia/Shanghai", 9060000),
    ("哈尔滨", "Harbin", "哈尔滨,Harbin", 45.80, 126.53, "CN", "Asia/Shanghai", 10630000),
    ("南京", "Nanjing", "南京,Nanjing", 32.06, 118.80, "CN", "Asia/Shanghai", 9310000),
    ("杭州", "Hangzhou", "杭州,Hangzhou", 30.27, 120.15, "CN", "Asia/Shanghai", 12200000),
    ("合肥", "Hefei", "合肥,Hefei", 31.82, 117.23, "CN", "Asia/Shanghai", 9370000),
    ("福州", "Fuzhou", "福州,Fuzhou", 26.07, 119.30, "CN", "Asia/Shanghai", 8290000),
    ("南昌", "Nanchang", "南昌,Nanchang", 28.68, 115.86, "CN", "Asia/Shanghai", 6250000),
    ("济南", "Jinan", "济南,Jinan", 36.65, 117.12, "CN", "Asia/Shanghai", 9200000),
    ("郑州", "Zhengzhou", "郑州,Zhengzhou", 34.75, 113.63, "CN", "Asia/Shanghai", 12600000),
    ("武汉", "Wuhan", "武汉,Wuhan", 30.59, 114.31, "CN", "Asia/Shanghai", 12320000),
    ("长沙", "Changsha", "长沙,Changsha", 28.23, 112.94, "CN", "Asia/Shanghai", 10050000),
    ("广州", "Guangzhou", "广州,Guangzhou,Canton", 23.13, 113.26, "CN", "Asia/Shanghai", 18680000),
    ("深圳", "Shenzhen", "深圳,Shenzhen", 22.54, 114.06, "CN", "Asia/Shanghai", 17560000),
    ("南宁", "Nanning", "南宁,Nanning", 22.82, 108.32, "CN", "Asia/Shanghai", 8740000),
    ("海口", "Haikou", "海口,Haikou", 20.04, 110.34, "CN", "Asia/Shanghai", 2870000),
    ("成都", "Chengdu", "成都,Chengdu", 30.57, 104.07, "CN", "Asia/Shanghai", 20940000),
    ("贵阳", "Guiyang", "贵阳,Guiyang", 26.65, 106.63, "CN", "Asia/Shanghai", 5990000),
    ("昆明", "Kunming", "昆明,Kunming", 24.88, 102.83, "CN", "Asia/Shanghai", 8460000),
    ("拉萨", "Lhasa", "拉萨,Lhasa", 29.65, 91.14, "CN", "Asia/Shanghai", 870000),
    ("西安", "Xi'an", "西安,Xi'an,Xian", 34.34, 108.94, "CN", "Asia/Shanghai", 12950000),
    ("兰州", "Lanzhou", "兰州,Lanzhou", 36.06, 103.83, "CN", "Asia/Shanghai", 4360000),
    ("西宁", "Xining", "西宁,Xining", 36.62, 101.78, "CN", "Asia/Shanghai", 2470000),
    ("银川", "Yinchuan", "银川,Yinchuan", 38.49, 106.23, "CN", "Asia/Shanghai", 2860000),
    ("乌鲁木齐", "Urumqi", "乌鲁木齐,Urumqi,Wulumuqi", 43.83, 87.62, "CN", "Asia/Shanghai", 4050000),
    ("香港", "Hong Kong", "香港,Hong Kong,Hongkong", 22.32, 114.17, "HK", "Asia/Hong_Kong", 7480000),
    ("澳门", "Macau", "澳门,Macau,Macao", 22.20, 113.55, "MO", "Asia/Macau", 680000),
    ("台北", "Taipei", "台北,Taipei", 25.03, 121.57, "TW", "Asia/Taipei", 2650000),
    ("Tokyo", "Tokyo", "东京,東京,Tokyo", 35.69, 139.69, "JP", "Asia/Tokyo", 13960000),
    ("Osaka", "Osaka", "大阪,Osaka", 34.69, 135.50, "JP", "Asia/Tokyo", 2750000),
    ("Seoul", "Seoul", "首尔,Seoul", 37.57, 126.98, "KR", "Asia/Seoul", 9720000),
    ("Singapore", "Singapore", "新加坡,Singapore", 1.35, 103.82, "SG", "Asia/Singapore", 5690000),
    ("Bangkok", "Bangkok", "曼谷,Bangkok", 13.76, 100.50, "TH", "Asia/Bangkok", 10540000),
    ("Kuala Lumpur", "Kuala Lumpur", "吉隆坡,Kuala Lumpur", 3.14, 101.69, "MY", "Asia/Kuala_Lumpur", 1800000),
    ("Jakarta", "Jakarta", "雅加达,Jakarta", -6.21, 106.85, "ID", "Asia/Jakarta", 10560000),
    ("New Delhi", "New Delhi", "新德里,New Delhi,Delhi", 28.61, 77.21, "IN", "Asia/Kolkata", 21750000),
    ("Mumbai", "Mumbai", "孟买,Mumbai,Bombay", 19.08, 72.88, "IN", "Asia/Kolkata", 20410000),
    ("Dubai", "Dubai", "迪拜,Dubai", 25.20, 55.27, "AE", "Asia/Dubai", 3330000),
    ("Istanbul", "Istanbul", "伊斯坦布尔,Istanbul", 41.01, 28.98, "TR", "Europe/Istanbul", 15460000),
    ("Moscow", "Moscow", "莫斯科,Moscow,Moskva", 55.76, 37.62, "RU", "Europe/Moscow", 12500000),
    ("London", "London", "伦敦,London", 51.51, -0.13, "GB", "Europe/London", 8980000),
    ("Paris", "Paris", "巴黎,Paris", 48.86, 2.35, "FR", "Europe/Paris", 2160000),
    ("Berlin", "Berlin", "柏林,Berlin", 52.52, 13.41, "DE", "Europe/Berlin", 3640000),
    ("Madrid", "Madrid", "马德里,Madrid", 40.42, -3.70, "ES", "Europe/Madrid", 3220000),
    ("Rome", "Rome", "罗马,Rome,Roma", 41.90, 12.50, "IT", "Europe/Rome", 2870000),
    ("Amsterdam", "Amsterdam", "阿姆斯特丹,Amsterdam", 52.37, 4.89, "NL", "Europe/Amsterdam", 872000),
    ("Cairo", "Cairo", "开罗,Cairo", 30.04, 31.24, "EG", "Africa/Cairo", 20900000),
    ("Sydney", "Sydney", "悉尼,Sydney", -33.87, 151.21, "AU", "Australia/Sydney", 5310000),
    ("Melbourne", "Melbourne", "墨尔本,Melbourne", -37.81, 144.96, "AU", "Australia/Melbourne", 5080000),
    ("Auckland", "Auckland", "奥克兰,Auckland", -36.85, 174.76, "NZ", "Pacific/Auckland", 1660000),
    ("New York", "New York", "纽约,New York,NYC", 40.71, -74.01, "US", "America/New_York", 8400000),
    ("Los Angeles", "Los Angeles", "洛杉矶,Los Angeles,LA", 34.05, -118.24, "US", "America/Los_Angeles", 3990000),
    ("San Francisco", "San Francisco", "旧金山,三藩市,San Francisco", 37.77, -122.42, "US", "America/Los_Angeles", 880000),
    ("Chicago", "Chicago", "芝加哥,Chicago", 41.88, -87.63, "US", "America/Chicago", 2710000),
    ("Houston", "Houston", "休斯敦,Houston", 29.76, -95.37, "US", "America/Chicago", 2320000),
    ("Seattle", "Seattle", "西雅图,Seattle", 47.61, -122.33, "US", "America/Los_Angeles", 750000),
    ("Toronto", "Toronto", "多伦多,Toronto", 43.65, -79.38, "CA", "America/Toronto", 2930000),
    ("Vancouver", "Vancouver", "温哥华,Vancouver", 49.28, -123.12, "CA", "America/Vancouver", 675000),
    ("Mexico City", "Mexico City", "墨西哥城,Mexico City,Ciudad de Mexico", 19.43, -99.13, "MX", "America/Mexico_City", 9210000),
    ("Sao Paulo", "Sao Paulo", "圣保罗,Sao Paulo,São Paulo", -23.55, -46.63, "BR", "America/Sao_Paulo", 12330000),
    ("Buenos Aires", "Buenos Aires", "布宜诺斯艾利斯,Buenos Aires", -34.60, -58.38, "AR",
     "America/Argentina/Buenos_Aires", 3080000),
]


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(storage.db_path(), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _create_tables(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS geo_cities (
            name       TEXT NOT NULL,
            asciiname  TEXT NOT NULL,
            alts       TEXT NOT NULL,       -- 别名串, 形如 ',别名1,别名2,' 便于精确LIKE匹配
            lat        REAL NOT NULL,
            lng        REAL NOT NULL,
            country    TEXT NOT NULL,
            timezone   TEXT NOT NULL,
            population INTEGER NOT NULL
        )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_geo_name ON geo_cities(name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_geo_ascii ON geo_cities(asciiname)")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS geo_meta (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            source TEXT NOT NULL,
            count  INTEGER NOT NULL
        )""")


def _download_geonames() -> bytes:
    """下载 cities5000.zip 到 data/ 并返回其字节。授权边界: 仅此一个URL。"""
    data_dir = Path(storage.db_path()).parent
    zip_path = data_dir / _ZIP_NAME
    if zip_path.exists() and zip_path.stat().st_size > 0:
        return zip_path.read_bytes()                       # 已下载过, 直接复用
    req = urllib.request.Request(GEONAMES_URL, headers={"User-Agent": "AnimaCodex/1.0"})
    with urllib.request.urlopen(req, timeout=_DOWNLOAD_TIMEOUT) as resp:
        raw = resp.read()
    zip_path.write_bytes(raw)
    return raw


def _parse_geonames(raw: bytes):
    """解析 GeoNames 制表符文件 → 入库行列表。列序见 GeoNames readme。"""
    rows = []
    with zipfile.ZipFile(io.BytesIO(raw)) as zf, zf.open(_TXT_NAME) as fh:
        for line in io.TextIOWrapper(fh, encoding="utf-8"):
            cols = line.rstrip("\n").split("\t")
            if len(cols) < 18:
                continue
            name, asciiname, alternatenames = cols[1], cols[2], cols[3]
            rows.append((name, asciiname, f",{alternatenames}," if alternatenames else ",",
                         float(cols[4]), float(cols[5]), cols[8], cols[17],
                         int(cols[14] or 0)))
    return rows


def init_geo() -> dict:
    """初始化地理库(幂等, 线程安全)。返回 {"source":…, "count":…}。"""
    global _meta_cache
    if _meta_cache:
        return _meta_cache
    with _init_lock:
        if _meta_cache:
            return _meta_cache
        with _connect() as conn:
            _create_tables(conn)
            row = conn.execute("SELECT source, count FROM geo_meta WHERE id = 1").fetchone()
            if row and row[1] > 0:
                _meta_cache = {"source": row[0], "count": row[1]}
                return _meta_cache
            try:
                rows = _parse_geonames(_download_geonames())
                source = _SOURCE_GEONAMES
            except Exception:
                rows = [(n, a, f",{alts},", lat, lng, c, tz, pop)
                        for (n, a, alts, lat, lng, c, tz, pop) in _BUILTIN_CITIES]
                source = _SOURCE_BUILTIN
            conn.execute("DELETE FROM geo_cities")
            conn.executemany(
                "INSERT INTO geo_cities (name, asciiname, alts, lat, lng, country, timezone, population) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
            conn.execute("INSERT OR REPLACE INTO geo_meta (id, source, count) VALUES (1, ?, ?)",
                         (source, len(rows)))
        _meta_cache = {"source": source, "count": len(rows)}
        return _meta_cache


def search(q: str) -> dict:
    """搜索城市。精确(name/asciiname/别名)优先、前缀次之, 人口降序, ≤10条。"""
    meta = init_geo()
    esc = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    exact_alt = f"%,{esc},%"
    prefix = f"{esc}%"
    # 中文名映射：若查询匹配CN→EN表，同时搜英文名
    en_fallback = _CITY_CN_MAP.get(q, "")
    en_prefix = (en_fallback + "%") if en_fallback else ""
    with _connect() as conn:
        rows = conn.execute("""
            SELECT name, country, lat, lng, timezone, population,
                   CASE WHEN name = :q COLLATE NOCASE OR asciiname = :q COLLATE NOCASE
                             OR alts LIKE :exact ESCAPE '\\' THEN 0 ELSE 1 END AS prio
            FROM geo_cities
            WHERE name = :q COLLATE NOCASE OR asciiname = :q COLLATE NOCASE
               OR alts LIKE :exact ESCAPE '\\'
               OR name LIKE :prefix ESCAPE '\\' OR asciiname LIKE :prefix ESCAPE '\\'
               """ + ("""
               OR name LIKE :en_prefix ESCAPE '\\' OR asciiname LIKE :en_prefix ESCAPE '\\'
            """ if en_fallback else "") + """
            ORDER BY prio ASC, population DESC
            LIMIT 10
        """, ({"q": q, "exact": exact_alt, "prefix": prefix, "en_prefix": en_prefix}
              if en_fallback else
              {"q": q, "exact": exact_alt, "prefix": prefix})).fetchall()
    return {
        "results": [{"city": r[0], "country": r[1], "lat": r[2], "lng": r[3],
                     "timezone": r[4]} for r in rows],
        "meta": {"source": meta["source"], "count": meta["count"]},
    }
