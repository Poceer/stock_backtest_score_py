# stock_backtest.py
import os
import sys

# 兼容直接运行本脚本 / 从 quant 包导入两种方式：
# 把本文件所在目录与项目根目录放进 sys.path，保证 import common / fetch_stock_name 可用
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
for _p in (_HERE, _ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from concurrent.futures import ThreadPoolExecutor, as_completed
import akshare as ak
import pandas as pd
import fetch_stock_name
import common


def _fetch_one(code, name, start_date, end_date, adjust, periods):
    """
    并发单元：拉取单只股票数据，并计算各周期涨幅。
    返回 (name, returns, d_max, n_rows, err)
    """
    try:
        df = ak.stock_zh_a_hist_tx(
            symbol=code,
            start_date=start_date,
            end_date=end_date,
            adjust=adjust,
        )
        df = df.sort_values('date').reset_index(drop=True)
        if len(df) == 0:
            raise ValueError("返回数据为空")

        # 多周期涨幅计算（公用逻辑）
        returns, d_max, n_rows = common.calc_period_returns(
            df, periods, date_col="date", close_col="close")

        return name, returns, d_max, n_rows, None
    except Exception as e:
        return name, [None] * len(periods), None, 0, e


def run_backtest(
        stock_codes,
        tag="",
        periods=(5, 15, 30, 60, 90, 180),
        start_date="20250101",
        end_date="20300101",
        adjust="qfq",
        title="收益率回测",
        save_dir="./charts",
        save_path=None,
        output_mode="file",  # "file" 本地保存 | "base64" 返回 base64 字符串
        max_workers=8,  # 并发线程数
        top_show=None,  # 图表只展示综合得分前 top_show 名；None = 全部展示
):
    assert output_mode in ("file", "base64"), "output_mode 只能是 'file' 或 'base64'"

    # 把用户输入的代码字符串解析成 {带前缀代码: 名称}
    stocks = fetch_stock_name.resolve_stocks(stock_codes)

    if not stocks:
        print("⚠ 没有有效的股票代码，终止。")
        return None

    # 周期标签，如 "5日"、"15日"
    period_labels = [f"{p}日" for p in periods]
    max_period = max(periods)
    max_p_idx = periods.index(max_period)
    print(f"\n>> 最大周期：{max_period}日，业务假设：最大周期有效则全部短周期数据都存在")

    # ========== 获取数据（并发） ==========
    all_returns = {}  # {股票名: [各周期涨幅]}
    actual_end = None  # 所有股票里最新的交易日
    removed_stocks = []

    results = {}  # {股票名: (returns, d_max, n_rows, err)}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [
            ex.submit(_fetch_one, code, name, start_date, end_date, adjust, periods)
            for code, name in stocks.items()
        ]
        for fut in as_completed(futures):
            name, returns, d_max, n_rows, err = fut.result()
            results[name] = (returns, d_max, n_rows, err)

    # 按原始输入顺序重排，保证颜色分配 / 列顺序稳定
    results = {name: results[name] for name in stocks.values()}

    for name, (returns, d_max, n_rows, err) in results.items():
        if err is not None:
            print(f"✗ {name} 数据获取失败: {err}，剔除")
            removed_stocks.append(name)
            continue

        # 只校验最大周期，满足就保留，认为其余周期全部有效
        if returns[max_p_idx] is None:
            print(f"✗ {name} 历史K线不足，不满足最大周期{max_period}日要求，剔除")
            removed_stocks.append(name)
            continue

        all_returns[name] = returns
        if actual_end is None or d_max > actual_end:
            actual_end = d_max
        print(f"✓ {name} 数据获取成功  (最新 {d_max}, {n_rows} 条)")

    print(f"\n>> 本次剔除标的列表：{removed_stocks}")
    if len(all_returns) == 0:
        print("⚠ 所有标的全部被剔除，终止")
        return None

    df_ret = pd.DataFrame(all_returns, index=period_labels)

    # ========= 自动按阈值分组 短/中/长（公用逻辑）=========
    p_groups, group_labels = common.group_periods(periods)
    common.print_groups(p_groups)

    # 计算每个周期的横截面 Z-score（公用逻辑）
    zscore_df = common.calc_zscore(df_ret)

    print(f'Zscore得分表调试\n', zscore_df)

    # 分组聚合 + 固定组权重 短0.3 中0.45 长0.25（长期组为空时自动归一化，公用逻辑）
    stock_group_detail, stock_final_scores, weights, sorted_scores = \
        common.calc_group_scores(zscore_df, periods)

    # 打印输出，展示分项+最终总分（top_show 为 None 时全打印）
    common.print_score_table(sorted_scores, stock_group_detail, weights, top_n=top_show)

    # ========== 三张子图布局（公用逻辑），输出：file 或 base64 ==========
    if output_mode == "base64":
        image_base64 = common.plot_score_chart(
            tag=tag, df_ret=df_ret, zscore_df=zscore_df,
            final_scores=stock_final_scores, sorted_scores=sorted_scores,
            weights=weights, actual_end=actual_end,
            save_path=None, return_base64=True, top_n=top_show,
        )

        return {
            "scores": stock_final_scores,
            "sorted_scores": sorted_scores,
            "df_ret": df_ret,
            "zscore_df": zscore_df,
            "actual_end": actual_end,
            "image_base64": image_base64,
            "group_detail": stock_group_detail
        }

    if save_path is None:
        fname = f"{title}.png"
        # 相对路径统一锚定项目根目录，避免 cwd 不同时生成重复的 charts 目录
        save_path = os.path.join(common.resolve_save_path(save_dir), fname)
    else:
        save_path = common.resolve_save_path(save_path)

    common.plot_score_chart(
        tag=tag, df_ret=df_ret, zscore_df=zscore_df,
        final_scores=stock_final_scores, sorted_scores=sorted_scores,
        weights=weights, actual_end=actual_end,
        save_path=save_path, return_base64=False, top_n=top_show,
    )

    return {
        "scores": stock_final_scores,
        "sorted_scores": sorted_scores,
        "df_ret": df_ret,
        "zscore_df": zscore_df,
        "actual_end": actual_end,
        "save_path": save_path,
        "group_detail": stock_group_detail
    }


def fetch_board_constituents(board_name):
    """
    按板块名称取该板块的全部成分股代码。
    接口同样传板块名称（不是 BK 代码），返回中文列名：代码 / 名称 / 最新价 / 涨跌幅 ...
    返回逗号拼接的 6 位代码字符串，可直接喂给 run_backtest；失败返回 None。
    """
    try:
        df = ak.stock_board_industry_cons_em(symbol=board_name)
    except Exception as e:
        print(f"✗ 板块[{board_name}]成分股获取失败: {e}")
        print(f"  请确认板块名称与 ak.stock_board_industry_name_em() 返回的「板块名称」完全一致")
        return None

    if df is None or "代码" not in df.columns or len(df) == 0:
        print(f"⚠ 板块[{board_name}]没有取到成分股")
        return None

    # 补零成 6 位，防止代码被当数字丢掉前导 0（如 000792）
    codes = [str(code).strip().zfill(6) for code in df["代码"].tolist()]
    print(f">> 板块[{board_name}]成分股 {len(codes)} 只")
    return ",".join(codes)


def run_backtest_by_board(
        board_name,
        periods=(10, 30, 60, 90, 120, 180, 250),
        top_show=10,  # 图表只展示综合得分前 top_show 名；None = 全部展示
        **kwargs):
    """
    输入板块名称 → 自动取该板块全部成分股 → 复用 run_backtest 做个股强弱对比。
    用来在看完板块强弱后，下钻到某个板块内部挑个股。
    其余参数（start_date / adjust / save_dir / output_mode 等）通过 kwargs 透传。
    """
    codes = fetch_board_constituents(board_name)
    if codes is None:
        return None

    kwargs.setdefault("tag", board_name)
    kwargs.setdefault("title", f"{board_name}成分股收益率回测")

    return run_backtest(
        stock_codes=codes,
        periods=periods,
        top_show=top_show,
        **kwargs,
    )

if __name__ == "__main__":
    run_backtest_by_board('辅料')
    run_backtest_by_board('会展服务')
    