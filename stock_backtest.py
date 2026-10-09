# stock_backtest.py
import base64
import io
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

import akshare as ak
import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
import fetch_stock_name

plt.rcParams['font.sans-serif'] = [
    'WenQuanYi Micro Hei',   # FC 环境用
    'SimHei',                 # Windows 本地用
    'Microsoft YaHei',        # Windows 备选
    'Arial Unicode MS',       # Mac 备选
]
plt.rcParams['axes.unicode_minus'] = False


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

        d_max = str(df['date'].iloc[-1])[:10]
        today_close = df.iloc[-1]['close']

        returns = []
        for period in periods:
            if len(df) > period:
                past_close = df.iloc[-(period + 1)]['close']
                change = (today_close - past_close) / past_close * 100
                returns.append(change)
            else:
                returns.append(None)

        return name, returns, d_max, len(df), None
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
        max_workers=8,       # 并发线程数
):
    assert output_mode in ("file", "base64"), "output_mode 只能是 'file' 或 'base64'"

    # 把用户输入的代码字符串解析成 {带前缀代码: 名称}
    stocks = fetch_stock_name.resolve_stocks(stock_codes)

    if not stocks:
        print("⚠ 没有有效的股票代码，终止。")
        return None

    # 周期标签，如 "5日"、"15日"
    period_labels = [f"{p}日" for p in periods]

    # ========== 获取数据（并发） ==========
    all_returns = {}  # {股票名: [各周期涨幅]}
    actual_end = None  # 所有股票里最新的交易日

    results = {}  # {股票名: (returns, d_max, n_rows, err)}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        # 列表推导式
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
        all_returns[name] = returns
        if err is not None:
            print(f"✗ {name} 数据获取失败: {err}")
            continue
        if actual_end is None or d_max > actual_end:
            actual_end = d_max
        print(f"✓ {name} 数据获取成功  (最新 {d_max}, {n_rows} 条)")

    if actual_end is None:
        print("⚠ 所有股票数据均获取失败，终止。")
        return None

    """
    数据结构说明：
    all_returns: dict
        {
            "贵州茅台": [1.2, 3.5, 5.1, 8.0, 10.2, 15.3],
            "五粮液":   [0.8, 2.1, 4.0, 6.5, 9.1, 12.0],
            "宁德时代": [-1.0, 1.5, 2.2, 3.8, 5.0, 7.5],
        }
        key   = 股票名
        value = 该股票在各周期的涨幅列表，长度和 periods 一致

    df_ret = pd.DataFrame(all_returns, index=period_labels)
        data = all_returns，默认规则：key 当列名，value 当该列数据
        index = period_labels，指定行标签

        结果（行=周期，列=股票名，值=涨幅%）：

                  贵州茅台   五粮液   宁德时代
            5日       1.2      0.8     -1.0
            15日      3.5      2.1      1.5
            30日      5.1      4.0      2.2
            60日      8.0      6.5      3.8
            90日     10.2      9.1      5.0
            180日    15.3     12.0      7.5
    """
    df_ret = pd.DataFrame(all_returns, index=period_labels)

    # 下面是计算zscore
    # 初始化一个所有得分为0的字典
    scores = {name: 0.0 for name in all_returns.keys()}
    # 初始化一个表格, 行: 周期, 列: 公司名称(沿用上面表的列名)
    zscore_df = pd.DataFrame(index=period_labels, columns=df_ret.columns, dtype=float)

    # 值遍历
    for period in period_labels:
        # 取该周期下有效（非 None）的股票
        row = df_ret.loc[period].dropna()
        n = len(row)
        if n < 2:
            print(f"⚠ {period} 有效样本不足（{n} 只），跳过")
            continue

        # 横截面标准化：减去均值，除以标准差
        # 平均值
        mean = row.mean()
        # 标准差
        std = row.std(ddof=0)

        if std == 0 or pd.isna(std):
            # 全部相同，Z-score 统一给 0
            # Series 是带标签的一维数组, 实际意义其实就是表格里的一行或一列数据
            z = pd.Series(0.0, index=row.index)
        else:
            # 同一个周期，每只股票的涨幅，偏离平均值多少个标准差
            # 一行数据可以直接与数值类型进行广播运算
            z = (row - mean) / std

        # 计算完一行以后, 赋值到表格对应行上
        zscore_df.loc[period, z.index] = z

        # 每只股票的分数累加该周期的 Z-score
        for name, zval in z.items():
            scores[name] += zval
    print(f'得分表调试\n', zscore_df)

    # zscore_df.notna()：逐个单元格判断是否不为空，返回布尔值表格（True/False）
    # .sum(axis=0)：0->行方向遍历, 按列求和; 1->列方向遍历, 按行求和
    # 整体：统计每一列非空数据的数量，即每只股票有效数据周期数(zscore的和要除以实际有数据的周期数, 做标准化)
    valid_counts = zscore_df.notna().sum(axis=0)

    for name in scores:
        if valid_counts[name] > 0:
            scores[name] /= valid_counts[name]

    # 按总分从高到低排
    # scores, 就是股票名称:得分的字典
    # x[1]就是取字典第二个值作为排序的值
    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)

    print("\n========== 加权总分（Z-score 等权，从高到低） ==========")
    for name, score in sorted_scores:
        print(f"{name} {score:.2f}")
    print("=============================================\n")

    # ========== 颜色映射 ==========
    # 每只股票固定一个颜色，上下两图保持一致
    color_palette = plt.cm.tab20.colors
    color_map = {name: color_palette[i % len(color_palette)]
                 for i, name in enumerate(all_returns.keys())}

    # ========== 上下双图 ==========
    fig, (ax_top, ax_bottom) = plt.subplots(
        2, 1, figsize=(16, 13),
        gridspec_kw={'height_ratios': [3, 2]}
    )

    # ---------- 上图：各周期收益率明细 ----------
    n_periods = len(period_labels)
    n_stocks = len(stocks)
    bar_width = 0.8 / n_stocks  # 每个周期内每只股票的柱子宽度
    x = np.arange(n_periods)

    # 下标和值一起遍历
    for j, period in enumerate(period_labels):
        row = df_ret.loc[period].dropna()
        row_sorted = row.sort_values(ascending=False)  # 涨幅高的排左边
        for k, (name, val) in enumerate(row_sorted.items()):
            # 计算该股票在该周期内的柱子横坐标
            pos = x[j] - 0.4 + bar_width * (k + 0.5)
            ax_top.bar(pos, val, width=bar_width,
                       color=color_map[name],
                       edgecolor='white', linewidth=0.5)
            # 柱顶标数值，正数朝上、负数朝下
            ax_top.text(pos, val + (0.3 if val >= 0 else -0.8),
                        f'{val:.1f}', ha='center',
                        va='bottom' if val >= 0 else 'top',
                        fontsize=7, rotation=90)

    ax_top.axhline(y=0, color='black', linewidth=0.8)
    ax_top.set_xticks(x)
    ax_top.set_xticklabels(period_labels, fontsize=11)
    ax_top.set_xlabel('统计周期', fontsize=12)
    ax_top.set_ylabel('收益率 (%)', fontsize=12)
    ax_top.set_title(f'{tag} — 各周期收益率明细',
                     fontsize=15, fontweight='bold')
    ax_top.grid(True, axis='y', alpha=0.3, linestyle='--')

    # 用矩形图例代替默认图例，颜色和柱子一致
    handles = [plt.Rectangle((0, 0), 1, 1, color=color_map[name])
               for name in all_returns.keys()]
    ax_top.legend(handles, list(all_returns.keys()),
                  loc='best', fontsize=9, ncol=3)

    # ---------- 下图：Z-score 得分排名 ----------
    names_sorted = [name for name, _ in sorted_scores]
    scores_sorted = [score for _, score in sorted_scores]
    colors_sorted = [color_map[name] for name in names_sorted]

    # 横向条形图，最高分在顶部
    y_pos = np.arange(len(names_sorted))
    ax_bottom.barh(y_pos, scores_sorted,
                   color=colors_sorted, edgecolor='white', linewidth=0.5)
    # 每条尾部标数值
    for i, (name, score) in enumerate(sorted_scores):
        ax_bottom.text(score + 0.05, i, f'{score:.2f}',
                       va='center', ha='left', fontsize=9)

    ax_bottom.set_yticks(y_pos)
    ax_bottom.set_yticklabels(names_sorted, fontsize=10)
    ax_bottom.invert_yaxis()  # 最高分放到最上面
    ax_bottom.set_xlabel('加权总分', fontsize=12)
    ax_bottom.set_title('Z-score得分排名',
                        fontsize=15, fontweight='bold')
    ax_bottom.grid(True, axis='x', alpha=0.3, linestyle='--')

    # ---------- 右上角注释：最新数据日期 ----------
    note = f"数据基准：{actual_end}"
    fig.text(0.99, 0.995, note,
             ha='right', va='top', fontsize=10,
             bbox=dict(boxstyle='round,pad=0.4',
                       facecolor='#fffbe6', edgecolor='#d4b106', alpha=0.95))

    plt.tight_layout(rect=(0, 0, 1, 0.965))

    # ========== 输出：file 或 base64 ==========
    if output_mode == "base64":
        # 画到内存缓冲区，避免落盘
        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=300, bbox_inches="tight")
        buf.seek(0)
        # 转 base64 字符串，便于网络传输
        image_base64 = base64.b64encode(buf.read()).decode("utf-8")
        plt.close(fig)

        print("✓ 图表已生成 base64 字符串")

        return {
            "scores": scores,
            "sorted_scores": sorted_scores,
            "df_ret": df_ret,
            "zscore_df": zscore_df,
            "actual_end": actual_end,
            "image_base64": image_base64,
        }

    # output_mode == "file"
    # 默认文件名：tag_标题.png
    if save_path is None:
        fname = f"{tag}_{title}.png" if tag else f"{title}.png"
        save_path = os.path.join(save_dir, fname)

    # 目录不存在就创建
    save_dir_actual = os.path.dirname(save_path)
    if save_dir_actual:
        os.makedirs(save_dir_actual, exist_ok=True)

    plt.savefig(save_path, dpi=300, bbox_inches='tight')
    print(f"图表已保存到 {save_path}")
    plt.close(fig)

    return {
        "scores": scores,
        "sorted_scores": sorted_scores,
        "df_ret": df_ret,
        "zscore_df": zscore_df,
        "actual_end": actual_end,
        "save_path": save_path,
    }