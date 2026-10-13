# 股票多周期收益率回测与打分工具

## 📖 项目简介
这是一个基于 Python 的 A 股回测小工具。它可以批量获取指定股票的历史行情，计算它们在多个时间周期（如 5日、15日、30日等）内的涨跌幅，并通过 **Z-score（标准分数）** 进行横向对比打分，最终生成可视化的收益率明细图和得分排名图。

## ⚙️ 核心原理
1. **数据获取**：使用 `akshare` 获取 A 股历史行情（默认前复权），支持多线程并发拉取。
2. **收益率计算**：计算每只股票在指定周期内的涨跌幅（百分比）。
3. **Z-score 打分**：
   - 在每个周期内，对所有股票的收益率进行标准化（减去均值，除以标准差）。
   - 将每只股票在所有周期的 Z-score 累加并求平均，得到最终加权总分。
   - 得分越高，说明该股票在多个周期内相对表现越强。
4. **可视化输出**：生成上下双图（上：各周期收益率明细；下：Z-score 总分排名）。

## 🚀 快速开始

1. 安装依赖：
   ```bash
   pip install -r requirements.txt
   ```

2. 运行
   ```
   python main.py
   ```

## 🛠️ 调用方法与参数说明

核心函数为 `stock_backtest.run_backtest(...)`，常用参数如下：

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `stock_codes` | 股票代码字符串，多个用逗号分隔 | 必填 |
| `tag` | 自定义图表前缀(如板块名称) | `""` |
| `title` | 自定义图表主标题 | `"收益率回测"` |
| `periods` | 统计周期（天） | `(5, 15, 30, 60, 90, 180)` |
| `output_mode` | 输出模式：`"file"` 或 `"base64"` | `"file"` |
| `save_dir` | `output_mode="file"` 时的保存目录（相对路径统一存到项目根目录） | `"./charts"` |
| `top_show` | 图表只展示综合得分前 N 名，`None` 表示全部展示 | `None` |

### 示例 1：直接保存本地 PNG（`output_mode="file"`）
```python
from quant import stock_backtest

result = stock_backtest.run_backtest(
    stock_codes="603893, 688256, 300458",
    tag="soc",
    title="收益率回测",
    output_mode="file",
    save_dir="./charts",
)
# 图片会自动保存到 ./charts/ 目录下，路径在 result["save_path"]
print("图片已保存到:", result["save_path"])
```


### 示例 2：返回 Base64 字符串（`output_mode="base64"`）
适合 Web 服务或不想落盘的场景。

```python
import base64
from quant import stock_backtest

result = stock_backtest.run_backtest(
    stock_codes="603893, 688256, 300458",
    tag="soc",
    title="收益率回测",
    output_mode="base64",
)

# 把 base64 解码成图片，手动存到本地
with open("test_output.png", "wb") as f:
    f.write(base64.b64decode(result["image_base64"]))
```

### 示例 3：按板块名称下钻到成分股（`run_backtest_by_board`）
看完行业板块强弱后，填感兴趣的板块名称，自动拉该板块全部成分股做个股对比。
板块名称需与 `ak.stock_board_industry_name_em()` 返回的「板块名称」完全一致。

```python
from quant import stock_backtest

result = stock_backtest.run_backtest_by_board(
    board_name="元件",                                     # 板块名称
    periods=[5, 10, 15, 20, 30, 60, 90, 120, 180, 250],
    top_show=10,                                           # 图表只展示前 10 名
    save_dir="./charts",
)
# 图片保存到 ./charts/元件成分股收益率回测.png
```

## 📊 行业板块间对比打分

```bash
python quant/board_backtest.py
```

全量拉取所有行业板块（始终全量，不做截断），计算各周期涨幅、横截面 Z-score，
按 短≤60日 / 60~120日 / >120日 三组加权（0.30/0.45/0.25）得到综合得分，
只把前 `top_show`（默认 10）名画图存 PNG，剩余结果在 `sorted_scores` 里返回。

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `periods` | 统计周期（天） | `(5, 10, 15, 20, 30, 60, 90, 120, 180, 250)` |
| `top_show` | 图表与明细展示前 N 名，`None` 表示全部 | `10` |
| `max_workers` | 并发线程数 | `8` |

