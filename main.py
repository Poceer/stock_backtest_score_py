from quant import stock_backtest

# 从JS迁移过来的板块配置字典
SECTORS = {
    "SOC": "300613,300458,603893,688608,301536,688099",
    "锂矿": "002497,002176,002460,002466,000792,002756,002738,000762,002240,002192,001203",
    "网络安全": "300017,300369,688561,002212,300659,601360,300454,002439",
    "算力": "300017,002396,000938,301165,603019,603881,688158,603220,300209,002929,301396,300442,603629,300857",
}

if __name__ == "__main__":
    # ========== 用法二：按板块名称下钻到成分股对比 ==========
    # 看完 board_backtest 的板块强弱后，填感兴趣的板块名，自动拉全部成分股做个股对比
    # result = stock_backtest.run_backtest_by_board(
    #     board_name="元件",
    #     periods=[5, 10, 15, 20, 30, 60, 90, 120, 180, 250],
    #     top_show=10,          # 图表只展示综合得分前 10 名
    #     save_dir="./charts",  # 相对路径统一存到项目根目录下的 charts
    # )

    # ========== 用法一：直接指定个股代码 ==========
    # 在这里切换板块，直接改板块名即可
    select_sector = "SOC"
    # select_sector = "锂矿"
    # select_sector = "网络安全"
    # select_sector = "算力"
    # =====================================================

    stock_raw = SECTORS[select_sector]

    result = stock_backtest.run_backtest(
        stock_codes=stock_raw,
        tag=f"{select_sector}",
        periods=[10, 30, 60, 90, 120, 180, 250],
        title=f"{select_sector}收益率回测",
        save_dir="./charts",
        output_mode='file'
        # output_mode= 'base64'
    )

    # 如果切base64模式，打开下面代码保存图片
    # with open(f"{select_sector}_回测图.png", "wb") as f:
    #     f.write(base64.b64decode(result["image_base64"]))
