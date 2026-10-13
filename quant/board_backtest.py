# board_backtest.py
import os
import sys

# 兼容直接运行本脚本 / 从 quant 包导入两种方式：把脚本目录放进 sys.path
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import akshare as ak
import pandas as pd
import common

# 板块日K接口返回中文列名（日期/收盘/开盘/最高/最低/涨跌幅/换手率），不写死英文
DATE_COL = "日期"
CLOSE_COL = "收盘"

FETCH_RETRY_TIMES = 3  # 接口偶发 502，失败重试次数
FETCH_RETRY_INTERVAL = 1.5  # 重试间隔（秒）


def _fetch_board_df(symbol, start_date, end_date):
    """
    拉取单个行业板块日K历史（带重试，3 次，间隔 1.5s）。
    symbol 传板块名称（不是 BK 代码）；不复权，不传 adjust。
    """
    last_err = None
    for attempt in range(1, FETCH_RETRY_TIMES + 1):
        try:
            df = ak.stock_board_industry_hist_em(
                symbol=symbol,
                period="日k",
                start_date=start_date,
                end_date=end_date,
            )
            if df is None or len(df) == 0:
                raise ValueError("返回数据为空")
            return df
        except Exception as e:
            last_err = e
            if attempt < FETCH_RETRY_TIMES:
                print(f"⚠ {symbol} 第{attempt}次拉取失败({e})，{FETCH_RETRY_INTERVAL}s 后重试")
                time.sleep(FETCH_RETRY_INTERVAL)
    raise last_err


def _fetch_one(symbol, start_date, end_date, periods):
    """
    并发单元：拉取单个板块数据，并计算各周期涨幅。
    返回 (symbol, returns, d_max, n_rows, err)
    """
    try:
        df = _fetch_board_df(symbol, start_date, end_date)
        df = df.sort_values(DATE_COL).reset_index(drop=True)

        # 多周期涨幅计算（公用逻辑，中文列名传入）
        returns, d_max, n_rows = common.calc_period_returns(
            df, periods, date_col=DATE_COL, close_col=CLOSE_COL)
        return symbol, returns, d_max, n_rows, None
    except Exception as e:
        return symbol, [None] * len(periods), None, 0, e


def run_board_backtest(
        periods=(5, 10, 15, 20, 30, 60, 90, 120, 180, 250),
        start_date="20250101",
        end_date="20300101",
        tag="板块",
        save_dir="./charts",
        max_workers=8,  # 并发线程数
        top_show=10,  # 图表与明细只展示综合得分前 top_show 名；None = 全部展示
):
    # ========== 拿全量行业板块列表（不去重，原样处理，始终全量算） ==========
    try:
        board_df = ak.stock_board_industry_name_em()
    except Exception as e:
        print(f"✗ 行业板块列表获取失败: {e}，终止")
        return None

    if board_df is None or "板块名称" not in board_df.columns or len(board_df) == 0:
        print("⚠ 行业板块列表为空，终止")
        return None

    board_names = board_df["板块名称"].tolist()
    print(f"\n>> 本次参与计算的板块数：{len(board_names)}")

    if not board_names:
        print("⚠ 没有可计算的板块，终止")
        return None

    # 周期标签，如 "5日"、"10日"
    period_labels = [f"{p}日" for p in periods]
    max_period = max(periods)
    max_p_idx = periods.index(max_period)
    print(f">> 最大周期：{max_period}日，业务假设：最大周期有效则全部短周期数据都存在")

    # ========== 获取数据（并发 + 重试） ==========
    all_returns = {}  # {板块名: [各周期涨幅]}
    actual_end = None  # 所有板块里最新的交易日
    removed_boards = []

    results = {}  # {板块名: (returns, d_max, n_rows, err)}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [
            ex.submit(_fetch_one, name, start_date, end_date, periods)
            for name in board_names
        ]
        for fut in as_completed(futures):
            name, returns, d_max, n_rows, err = fut.result()
            results[name] = (returns, d_max, n_rows, err)

    # 按板块列表原始顺序重排，保证颜色分配 / 列顺序稳定
    results = {name: results[name] for name in board_names}

    for name, (returns, d_max, n_rows, err) in results.items():
        if err is not None:
            print(f"✗ {name} 数据获取失败: {err}，剔除")
            removed_boards.append(name)
            continue

        # 校验周期动态取 periods 最大值（不写死 180）；最大周期取不到值就一开始剔除
        if returns[max_p_idx] is None:
            print(f"✗ {name} 历史K线不足，不满足最大周期{max_period}日要求，剔除")
            removed_boards.append(name)
            continue

        all_returns[name] = returns
        if actual_end is None or d_max > actual_end:
            actual_end = d_max
        print(f"✓ {name} 数据获取成功  (最新 {d_max}, {n_rows} 条)")

    print(f"\n>> 本次剔除板块列表：{removed_boards}")
    if len(all_returns) == 0:
        print("⚠ 所有板块全部被剔除，终止")
        return None

    df_ret = pd.DataFrame(all_returns, index=period_labels)

    # ========= 自动按阈值分组 短/中/长（公用逻辑）=========
    p_groups, group_labels = common.group_periods(periods)
    common.print_groups(p_groups)

    # 计算每个周期的横截面 Z-score（公用逻辑）
    zscore_df = common.calc_zscore(df_ret, unit="个")

    # 分组聚合 + 固定组权重 短0.3 中0.45 长0.25（长期组为空时自动归一化，公用逻辑）
    board_group_detail, board_final_scores, weights, sorted_scores = \
        common.calc_group_scores(zscore_df, periods)

    # Zscore 调试表只打印前 top_show 名（全量会刷屏，top_show=None 时全打印）
    top_names = [name for name, _ in sorted_scores] if top_show is None else \
        [name for name, _ in sorted_scores[:top_show]]
    print(f'Zscore得分表调试（前{len(top_names)}名）\n', zscore_df[top_names])

    # 打印输出：前 top_show 名分项 + 最终总分
    common.print_score_table(sorted_scores, board_group_detail, weights, top_n=top_show)

    # ========== 只保留综合得分前 top_show 名画图存 PNG（公用逻辑） ==========
    date_str = actual_end.replace("-", "") if actual_end else "未知日期"
    top_tag = len(sorted_scores) if top_show is None else top_show
    # 相对路径统一锚定项目根目录，避免 cwd 不同时生成重复的 charts 目录
    save_path = os.path.join(common.resolve_save_path(save_dir),
                             f"board_top{top_tag}_{tag}_{date_str}.png")
    common.plot_score_chart(
        tag=tag, df_ret=df_ret, zscore_df=zscore_df,
        final_scores=board_final_scores, sorted_scores=sorted_scores,
        weights=weights, actual_end=actual_end,
        save_path=save_path, return_base64=False, top_n=top_show,
    )

    return {
        "scores": board_final_scores,
        "sorted_scores": sorted_scores,
        "df_ret": df_ret,
        "zscore_df": zscore_df,
        "actual_end": actual_end,
        "save_path": save_path,
        "group_detail": board_group_detail
    }


if __name__ == "__main__":
    # 始终全量计算；top_show 控制图表与明细展示前几名
    run_board_backtest(
        periods=[10, 30, 60, 90, 120, 180, 250],
        top_show=30,
    )
