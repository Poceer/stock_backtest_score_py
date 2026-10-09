# fetch_stock_name.py
import re

import requests


def parse_stock_codes(raw_input: str) -> list:
    """解析用户输入的股票代码字符串，返回带市场前缀的代码列表"""
    parts = raw_input.split(",")

    codes = []
    for part in parts:
        code = re.sub(r"\s+", "", part)
        if not code:
            continue

        if code.startswith("6"):
            prefix = "sh"
        elif code.startswith(("0", "3")):
            prefix = "sz"
        elif code.startswith(("4", "8")):
            prefix = "bj"
        else:
            print(f"⚠ 跳过未知前缀的代码: {code}")
            continue

        codes.append(f"{prefix}{code}")

    return codes


def get_stock_names(codes: list) -> dict:
    """通过腾讯行情接口批量获取股票名称，返回 {完整代码: 名称}"""
    if not codes:
        return {}

    query = ",".join(codes)
    url = f"http://qt.gtimg.cn/q={query}"

    resp = requests.get(url, timeout=10)
    resp.encoding = "gbk"

    result = {}
    for line in resp.text.strip().split(";"):
        line = line.strip()
        if not line or "=" not in line:
            continue

        key, value = line.split("=", 1)
        full_code = key.replace("v_", "")

        data = value.strip('"').split("~")
        if len(data) > 2:
            name = data[1].strip()
            if name:
                result[full_code] = name

    return result


def resolve_stocks(raw_input: str) -> dict:
    """输入字符串 → 返回 [(6位代码, 名称), ...]，可直接喂给 run_backtest"""
    codes = parse_stock_codes(raw_input)
    print("解析后的代码:", codes)

    stock_dict = get_stock_names(codes)

    missing = [c for c in codes if c not in stock_dict]
    if missing:
        print(f"⚠ 以下代码未获取到数据，已跳过: {missing}")

    return stock_dict

if __name__ == "__main__":
    raw = "600519, 000858, 300750, 430047, 999999, 66666666"
    stocks = resolve_stocks(raw)

    print("\n最终股票字典:", stocks)

    # 后续传给 run_backtest 时，直接转成列表即可：
    # stock_list = list(stocks.items())  # [('sh600519', '贵州茅台'), ...]
