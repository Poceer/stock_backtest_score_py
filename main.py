import base64
import stock_backtest

# 从JS迁移过来的板块配置字典
SECTORS = {
    "SOC": "300613,300458,603893,688608,301536,688099",
    "锂矿": "002497,002176,002460,002466,000792,002756,002738,000762,002240,002192,001203",
    "网络安全": "300017,300369,688561,002212,300659,601360,300454,002439",
    "算力": "300017,002396,000938,301165,603019,603881,688158,603220,300209,002929,301396,300442,603629,300857",
}

if __name__ == "__main__":
    # ========== 在这里切换板块，直接改板块名即可 ==========
    # select_sector = "SOC"
    # select_sector = "锂矿"
    # select_sector = "网络安全"
    select_sector = "算力"
    # =====================================================

    stock_raw = SECTORS[select_sector]

    result = stock_backtest.run_backtest(
        stock_codes=stock_raw,
        tag=f"{select_sector}",
        periods=[5, 10, 15, 20, 30, 60, 90, 120, 180, 250],
        title=f"{select_sector}收益率回测",
        save_dir="./charts",
        output_mode='file'
        # output_mode= 'base64'
    )

    # 如果切base64模式，打开下面代码保存图片
    # with open(f"{select_sector}_回测图.png", "wb") as f:
    #     f.write(base64.b64decode(result["image_base64"]))
