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

    # =========【改动1：自动按阈值分组 短/中/长】=======
    # 分组规则：<=31短；31< p <=179中；p >=180长
    p_groups = {
        "short": [p for p in periods if p <= 31],
        "mid": [p for p in periods if 31 < p <= 179],
        "long": [p for p in periods if p >= 180]
    }
    # 转成对应的行标签，用于zscore_df取行
    group_labels = {
        gname: [f"{p}日" for p in plist] for gname, plist in p_groups.items()
    }
    print("\n===== 自动周期分组 =====")
    print(f"短期组(<=31日): {p_groups['short']}")
    print(f"中期组(31~179日): {p_groups['mid']}")
    print(f"长期组(≥180日): {p_groups['long']}")
    print("========================\n")

    # 初始化zscore表格
    zscore_df = pd.DataFrame(index=period_labels, columns=df_ret.columns, dtype=float)

    # 遍历每个周期，计算横截面Z-score
    for period in period_labels:
        row = df_ret.loc[period].dropna()
        n = len(row)
        if n < 2:
            print(f"⚠ {period} 有效样本不足（{n} 只），跳过该周期Z计算")
            continue

        mean = row.mean()
        std = row.std(ddof=0)

        if std == 0 or pd.isna(std):
            z = pd.Series(0.0, index=row.index)
        else:
            z = (row - mean) / std

        zscore_df.loc[period, z.index] = z

    print(f'Zscore得分表调试\n', zscore_df)

    # =========【改动2：分组聚合 + 固定组权重 短0.3 中0.45 长0.25】=======
    w_short = 0.30
    w_mid = 0.45
    w_long = 0.25

    stock_final_scores = {}
    stock_group_detail = {}

    for stock_name in zscore_df.columns:
        # 取出该股票三组对应的z值（业务前提：全部有值，不再做空值判断）
        s_z = zscore_df.loc[group_labels["short"], stock_name]
        m_z = zscore_df.loc[group_labels["mid"], stock_name]
        l_z = zscore_df.loc[group_labels["long"], stock_name]

        s_score = s_z.mean()
        m_score = m_z.mean()
        l_score = l_z.mean()

        stock_group_detail[stock_name] = {
            "short": s_score,
            "mid": m_score,
            "long": l_score
        }

        # 固定权重加权
        final = w_short * s_score + w_mid * m_score + w_long * l_score
        stock_final_scores[stock_name] = final

    # 排序
    sorted_scores = sorted(stock_final_scores.items(), key=lambda x: x[1], reverse=True)

    # =========【改动3：打印输出，展示分项+最终总分】=======
    print("\n========== 分组加权总分【短0.3｜中0.45｜长0.25】从高到低 ==========")
    for name, score in sorted_scores:
        detail = stock_group_detail[name]
        print(f"{name} | 短:{detail['short']:.2f} 中:{detail['mid']:.2f} 长:{detail['long']:.2f} | 综合:{score:.2f}")
    print("==================================================================\n")

    # ========== 颜色映射 ==========
    color_palette = plt.cm.tab20.colors
    color_map = {name: color_palette[i % len(color_palette)]
                 for i, name in enumerate(stock_final_scores.keys())}

    # ======================【3张子图布局】======================
    # 上图原始收益率，中图Z-score，下图综合得分
    fig, (ax_top, ax_mid, ax_bottom) = plt.subplots(
        3, 1, figsize=(16, 16),
        gridspec_kw={'height_ratios': [2, 2, 1.8]}
    )

    # ---------- 上图：各周期收益率明细（原始%） ----------
    n_periods = len(period_labels)
    n_stocks = len(stock_final_scores)
    bar_width = 0.8 / n_stocks
    x = np.arange(n_periods)

    # 只保留通过全部筛选的标的画图
    filter_df_ret = df_ret[list(stock_final_scores.keys())]
    filter_z_df = zscore_df[list(stock_final_scores.keys())] # Z-score表同样过滤

    for j, period in enumerate(period_labels):
        row = filter_df_ret.loc[period]
        row_sorted = row.sort_values(ascending=False)
        for k, (name, val) in enumerate(row_sorted.items()):
            pos = x[j] - 0.4 + bar_width * (k + 0.5)
            ax_top.bar(pos, val, width=bar_width,
                       color=color_map[name],
                       edgecolor='white', linewidth=0.5)
            ax_top.text(pos, val + (0.3 if val >= 0 else -0.8),
                        f'{val:.1f}', ha='center',
                        va='bottom' if val >= 0 else 'top',
                        fontsize=7, rotation=90)

    ax_top.axhline(y=0, color='black', linewidth=0.8)
    ax_top.set_xticks(x)
    ax_top.set_xticklabels(period_labels, fontsize=11)
    ax_top.set_xlabel('统计周期', fontsize=12)
    ax_top.set_ylabel('收益率 (%)', fontsize=12)
    ax_top.set_title(f'{tag} — 各周期原始收益率',
                     fontsize=15, fontweight='bold')
    ax_top.grid(True, axis='y', alpha=0.3, linestyle='--')

    handles = [plt.Rectangle((0, 0), 1, 1, color=color_map[name])
               for name in stock_final_scores.keys()]
    ax_top.legend(handles, list(stock_final_scores.keys()),
                  loc='best', fontsize=9, ncol=3)

    # =====================【新增：中间图 各周期横截面Z-score】=====================
    for j, period in enumerate(period_labels):
        row_z = filter_z_df.loc[period]
        row_z_sorted = row_z.sort_values(ascending=False)
        for k, (name, z_val) in enumerate(row_z_sorted.items()):
            pos = x[j] - 0.4 + bar_width * (k + 0.5)
            ax_mid.bar(pos, z_val, width=bar_width,
                       color=color_map[name],
                       edgecolor='white', linewidth=0.5)
            ax_mid.text(pos, z_val + (0.08 if z_val >= 0 else -0.12),
                        f'{z_val:.2f}', ha='center',
                        va='bottom' if z_val >= 0 else 'top',
                        fontsize=7, rotation=90)

    ax_mid.axhline(y=0, color='black', linewidth=0.8)
    ax_mid.set_xticks(x)
    ax_mid.set_xticklabels(period_labels, fontsize=11)
    ax_mid.set_xlabel('统计周期', fontsize=12)
    ax_mid.set_ylabel('横截面 Z-score（偏离均值标准差）', fontsize=12)
    ax_mid.set_title(f'{tag} — 各周期相对板块强弱(Z-score)',
                     fontsize=15, fontweight='bold')
    ax_mid.grid(True, axis='y', alpha=0.3, linestyle='--')

    # ---------- 下图：Z-score 分组加权得分排名 ----------
    names_sorted = [name for name, _ in sorted_scores]
    scores_sorted = [score for _, score in sorted_scores]
    colors_sorted = [color_map[name] for name in names_sorted]

    y_pos = np.arange(len(names_sorted))
    ax_bottom.barh(y_pos, scores_sorted,
                   color=colors_sorted, edgecolor='white', linewidth=0.5)
    for i, (name, score) in enumerate(sorted_scores):
        ax_bottom.text(score + 0.05, i, f'{score:.2f}',
                       va='center', ha='left', fontsize=9)

    ax_bottom.set_yticks(y_pos)
    ax_bottom.set_yticklabels(names_sorted, fontsize=10)
    ax_bottom.invert_yaxis()
    ax_bottom.set_xlabel('加权综合Z-score得分', fontsize=12)
    ax_bottom.set_title('分组加权Z-score得分排名',
                        fontsize=15, fontweight='bold')
    ax_bottom.grid(True, axis='x', alpha=0.3, linestyle='--')

    # ---------- 右上角注释：最新数据日期 ----------
    note = f"数据基准：{actual_end}"
    fig.text(0.99, 0.995, note,
             ha='right', va='top', fontsize=10,
             bbox=dict(boxstyle='round,pad=0.4',
                       facecolor='#fffbe6', edgecolor='#d4b106', alpha=0.95))

    # =========【左上角说明框，更新分组逻辑】=========
    desc_text = """分组规则：
短期组 ≤31日｜中期组 31~179日｜长期组 ≥180日
权重：短期0.30，中期0.45，长期0.25
计算逻辑：每组内周期Z-score取均值，再加权求和"""
    fig.text(0.01, 0.995, desc_text,
             ha='left', va='top', fontsize=10, linespacing=1.4,
             bbox=dict(boxstyle='round,pad=0.4',
                       facecolor='#f7f7f7', edgecolor='#888888', alpha=0.92))

    plt.tight_layout(rect=(0, 0, 1, 0.965))

    # ========== 输出：file 或 base64 ==========
    if output_mode == "base64":
        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=300, bbox_inches="tight")
        buf.seek(0)
        image_base64 = base64.b64encode(buf.read()).decode("utf-8")
        plt.close(fig)

        print("✓ 图表已生成 base64 字符串")
        return {
            "scores": stock_final_scores,
            "sorted_scores": sorted_scores,
            "df_ret": filter_df_ret,
            "zscore_df": zscore_df,
            "actual_end": actual_end,
            "image_base64": image_base64,
            "group_detail": stock_group_detail
        }

    if save_path is None:
        fname = f"{title}.png"
        save_path = os.path.join(save_dir, fname)
    save_dir_actual = os.path.dirname(save_path)
    if save_dir_actual:
        os.makedirs(save_dir_actual, exist_ok=True)

    plt.savefig(save_path, dpi=300, bbox_inches="tight")
    print(f"图表已保存到 {save_path}")
    plt.close(fig)

    return {
        "scores": stock_final_scores,
        "sorted_scores": sorted_scores,
        "df_ret": filter_df_ret,
        "zscore_df": zscore_df,
        "actual_end": actual_end,
        "save_path": save_path,
        "group_detail": stock_group_detail
    }
