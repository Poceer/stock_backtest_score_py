# common.py
# 个股/板块回测脚本的公用逻辑：与数据源无关，不调用 akshare
import base64
import io
import os

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np

plt.rcParams['font.sans-serif'] = [
    'WenQuanYi Micro Hei',   # FC 环境用
    'SimHei',                 # Windows 本地用
    'Microsoft YaHei',        # Windows 备选
    'Arial Unicode MS',       # Mac 备选
]
plt.rcParams['axes.unicode_minus'] = False

# 项目根目录（quant 的上级）：所有相对输出路径都锚定到它，
# 避免运行时 cwd 不同（例如从 quant/ 目录里执行）而生成重复的 charts 目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resolve_save_path(path):
    """相对路径统一锚定到项目根目录；绝对路径原样返回"""
    if not path or os.path.isabs(path):
        return path
    return os.path.normpath(os.path.join(PROJECT_ROOT, path))


# 分组阈值：短期 ≤60日，中期 60~120日，长期 >120日
SHORT_MAX = 60
MID_MAX = 120

# 分组固定权重：短0.30 / 中0.45 / 长0.25（某组为空时自动重新归一化）
GROUP_WEIGHTS = {"short": 0.30, "mid": 0.45, "long": 0.25}


def calc_period_returns(df, periods, date_col, close_col):
    """
    多周期涨幅计算（数据源无关）。
    传入已按日期升序排好的 df，计算每个周期相对最新收盘价的涨跌幅(%)。
    返回 (returns, d_max, n_rows)：
      returns: 与 periods 等长的列表，数据不足的周期为 None
      d_max:   最新一条数据的日期字符串（YYYY-MM-DD）
      n_rows:  数据行数
    """
    d_max = str(df[date_col].iloc[-1])[:10]
    today_close = df.iloc[-1][close_col]
    n_rows = len(df)

    returns = []
    for period in periods:
        if len(df) > period:
            past_close = df.iloc[-(period + 1)][close_col]
            change = (today_close - past_close) / past_close * 100
            returns.append(change)
        else:
            returns.append(None)

    return returns, d_max, n_rows


def calc_zscore(df_ret, unit="只"):
    """
    横截面 Z-score：对每个周期（行）的所有标的收益率做标准化。
    df_ret: 行=周期标签，列=标的，值为收益率(%)；返回同结构 Z-score 表。
    有效样本不足 2 个的周期跳过计算（该周期整行为 NaN）。
    """
    zscore_df = pd.DataFrame(index=df_ret.index, columns=df_ret.columns, dtype=float)

    for period in df_ret.index:
        row = df_ret.loc[period].dropna()
        n = len(row)
        if n < 2:
            print(f"⚠ {period} 有效样本不足（{n} {unit}），跳过该周期Z计算")
            continue

        mean = row.mean()
        std = row.std(ddof=0)

        if std == 0 or pd.isna(std):
            z = pd.Series(0.0, index=row.index)
        else:
            z = (row - mean) / std

        zscore_df.loc[period, z.index] = z

    return zscore_df


def group_periods(periods):
    """
    按阈值把周期分到 短/中/长 三组。
    返回 (p_groups, group_labels)：
      p_groups:     {"short": [...], "mid": [...], "long": [...]}
      group_labels: 同结构的周期行标签（如 "5日"）
    """
    p_groups = {
        "short": [p for p in periods if p <= SHORT_MAX],
        "mid": [p for p in periods if SHORT_MAX < p <= MID_MAX],
        "long": [p for p in periods if p > MID_MAX],
    }
    group_labels = {
        gname: [f"{p}日" for p in plist] for gname, plist in p_groups.items()
    }
    return p_groups, group_labels


def print_groups(p_groups):
    """打印 短/中/长 自动分组结果"""
    print("\n===== 自动周期分组 =====")
    print(f"短期组(<={SHORT_MAX}日): {p_groups['short']}")
    print(f"中期组({SHORT_MAX}~{MID_MAX}日): {p_groups['mid']}")
    print(f"长期组(>{MID_MAX}日): {p_groups['long']}")
    print("========================\n")


def calc_group_scores(zscore_df, periods, weights=None):
    """
    分组加权打分：组内各周期 Z-score 取均值，再按 短/中/长 权重加权求和。
    若某组为空（如传入 periods 不含 >120 的周期，长期组为空），
    自动把权重重新归一化到非空组上，空组权重置 0 并打印提示。
    返回 (group_detail, final_scores, weights, sorted_scores)：
      group_detail:  {标的: {"short": 分, "mid": 分, "long": 分}}
      final_scores:  {标的: 综合分}
      weights:       实际使用的权重（可能被重新归一化过）
      sorted_scores: 按综合分从高到低排序的 [(标的, 综合分), ...]
    """
    p_groups, group_labels = group_periods(periods)
    weights = dict(GROUP_WEIGHTS) if weights is None else dict(weights)

    active_groups = [g for g in ("short", "mid", "long") if p_groups[g]]
    if not active_groups:
        raise ValueError("periods 为空，无法分组")

    if len(active_groups) < 3:
        # 有分组为空：权重重新归一化到非空组，空组权重置 0
        total = sum(weights[g] for g in active_groups)
        for g in weights:
            weights[g] = weights[g] / total if g in active_groups else 0.0
        if not p_groups["long"]:
            print("⚠ 长期组为空，权重已重新归一化")
        print(f"   归一化后权重：短{weights['short']:.2f}｜中{weights['mid']:.2f}｜长{weights['long']:.2f}")

    group_detail = {}
    final_scores = {}
    for name in zscore_df.columns:
        detail = {}
        final = 0.0
        for g in ("short", "mid", "long"):
            if p_groups[g]:
                g_score = zscore_df.loc[group_labels[g], name].mean()
            else:
                g_score = 0.0  # 空组记 0 分，配合归一化后权重 0 不参与计算
            detail[g] = g_score
            final += weights[g] * g_score
        group_detail[name] = detail
        final_scores[name] = final

    sorted_scores = sorted(final_scores.items(), key=lambda x: x[1], reverse=True)
    return group_detail, final_scores, weights, sorted_scores


def print_score_table(sorted_scores, group_detail, weights, top_n=None):
    """
    打印分组加权总分明细（短/中/长/综合）。
    top_n 为 None 时打印全部，否则只打印前 top_n 名。
    """
    print(f"\n========== 分组加权总分【短{weights['short']:g}｜中{weights['mid']:g}｜长{weights['long']:g}】从高到低 ==========")
    items = sorted_scores if top_n is None else sorted_scores[:top_n]
    for name, score in items:
        detail = group_detail[name]
        print(f"{name} | 短:{detail['short']:.2f} 中:{detail['mid']:.2f} 长:{detail['long']:.2f} | 综合:{score:.2f}")
    print("==================================================================\n")


def plot_score_chart(tag, df_ret, zscore_df, final_scores, sorted_scores, weights,
                     actual_end, save_path, return_base64=False, top_n=None):
    """
    三张子图：各周期原始收益率 / 各周期横截面 Z-score / 综合得分排名。
    保留左上分组说明框、右上数据基准注释、按标的输入顺序的颜色映射。
    top_n 为 None 时画全部标的，否则只画综合得分前 top_n 名。
    只输出 PNG：return_base64=True 时返回 base64 字符串，否则保存到 save_path。
    """
    # 画图标的集合：默认全部，指定 top_n 时只画前 top_n 名
    sorted_plot = sorted_scores if top_n is None else sorted_scores[:top_n]
    plot_names = [name for name, _ in sorted_plot]
    plot_name_set = set(plot_names)

    filter_df_ret = df_ret[plot_names]
    filter_z_df = zscore_df[plot_names]

    # 颜色映射：按标的输入顺序分配（与 final_scores 键序一致）
    color_palette = plt.cm.tab20.colors
    color_map = {name: color_palette[i % len(color_palette)]
                 for i, name in enumerate(final_scores.keys())}

    # ====================== 3张子图布局 ======================
    # 上图原始收益率，中图Z-score，下图综合得分
    fig, (ax_top, ax_mid, ax_bottom) = plt.subplots(
        3, 1, figsize=(16, 16),
        gridspec_kw={'height_ratios': [2, 2, 1.8]}
    )

    # ---------- 上图：各周期收益率明细（原始%） ----------
    period_labels = list(filter_df_ret.index)
    n_periods = len(period_labels)
    n_stocks = len(plot_names)
    bar_width = 0.8 / n_stocks
    x = np.arange(n_periods)

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

    # 图例按标的输入顺序（与颜色分配一致）
    legend_names = [name for name in final_scores.keys() if name in plot_name_set]
    handles = [plt.Rectangle((0, 0), 1, 1, color=color_map[name])
               for name in legend_names]
    ax_top.legend(handles, legend_names, loc='best', fontsize=9, ncol=3)

    # ---------- 中图：各周期横截面 Z-score ----------
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
    names_sorted = [name for name, _ in sorted_plot]
    scores_sorted = [score for _, score in sorted_plot]
    colors_sorted = [color_map[name] for name in names_sorted]

    y_pos = np.arange(len(names_sorted))
    ax_bottom.barh(y_pos, scores_sorted,
                   color=colors_sorted, edgecolor='white', linewidth=0.5)
    for i, (name, score) in enumerate(sorted_plot):
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

    # ---------- 左上角说明框：分组规则与权重 ----------
    desc_text = f"""分组规则：
短期组 ≤{SHORT_MAX}日｜中期组 {SHORT_MAX}~{MID_MAX}日｜长期组 >{MID_MAX}日
权重：短期{weights['short']:.2f}，中期{weights['mid']:.2f}，长期{weights['long']:.2f}
计算逻辑：每组内周期Z-score取均值，再加权求和"""
    fig.text(0.01, 0.995, desc_text,
             ha='left', va='top', fontsize=10, linespacing=1.4,
             bbox=dict(boxstyle='round,pad=0.4',
                       facecolor='#f7f7f7', edgecolor='#888888', alpha=0.92))

    plt.tight_layout(rect=(0, 0, 1, 0.965))

    # ========== 输出：只输出 PNG（本地保存 或 返回 base64） ==========
    if return_base64:
        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=300, bbox_inches="tight")
        buf.seek(0)
        image_base64 = base64.b64encode(buf.read()).decode("utf-8")
        plt.close(fig)

        print("✓ 图表已生成 base64 字符串")
        return image_base64

    save_dir_actual = os.path.dirname(save_path)
    if save_dir_actual:
        os.makedirs(save_dir_actual, exist_ok=True)

    plt.savefig(save_path, dpi=300, bbox_inches="tight")
    print(f"图表已保存到 {save_path}")
    plt.close(fig)

    return save_path
