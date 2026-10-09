# main.py
import stock_backtest
import base64

if __name__ == "__main__":
    # raw = "002497, 002176, 002460"
    raw = "603893, 301536, 688099, 688256, 300458, 300613, 688608"

    result = stock_backtest.run_backtest(
        stock_codes=raw,
        tag="soc",
        title="收益率回测",
        save_dir="./charts",
        # output_mode= 'file'
        output_mode= 'base64'
    )
    # 把 base64 解码成图片，存到本地
    with open("test_output.png", "wb") as f:
        f.write(base64.b64decode(result["image_base64"]))


