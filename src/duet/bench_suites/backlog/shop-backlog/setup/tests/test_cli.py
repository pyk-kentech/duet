import json


def _setup(cli):
    assert cli("product-add", "BOOK", "Python Book", "books", "30.00", "--weight", "800").returncode == 0
    assert cli("product-add", "MUG", "Mug", "home", "8.50", "--weight", "350").returncode == 0
    assert cli("receive", "BOOK", "10").stdout.strip() == "재고: BOOK 10"
    cli("receive", "MUG", "10")


def test_products_listing(cli):
    _setup(cli)
    r = cli("products")
    assert r.returncode == 0
    assert r.stdout.splitlines() == ["BOOK\tPython Book\tbooks\t30.00\t10", "MUG\tMug\thome\t8.50\t10"]


def test_order_and_show(cli):
    _setup(cli)
    r = cli("order", "BOOK", "MUG:2", "--customer", "Kim")
    assert r.stdout.strip() == "주문 1001 생성 (합계 58.16)"
    assert cli("pay", "1001").stdout.strip() == "주문 1001: paid"
    out = cli("show", "1001").stdout.splitlines()
    assert out == [
        "주문 1001 (paid)",
        "고객: Kim",
        "날짜: 2026-03-01 12:00",
        "지역: domestic",
        "  BOOK  Python Book  1 x 30.00 = 30.00",
        "  MUG  Mug  2 x 8.50 = 17.00",
        "소계: 47.00",
        "배송: 4.90",
        "세금: 6.26",
        "합계: 58.16",
    ]


def test_error_exit_code_and_file_unchanged(cli):
    _setup(cli)
    before = cli.data.read_bytes()
    r = cli("order", "BOOK:11", "--customer", "Kim")
    assert r.returncode == 1 and r.stderr.startswith("오류:")
    assert cli.data.read_bytes() == before


def test_coupons_listing(cli):
    _setup(cli)
    cli("coupon-add", "save10", "percent", "10", "--max-uses", "3")
    cli("coupon-add", "FIVE", "fixed", "5", "--stackable")
    cli("coupon-add", "SHIP", "free_shipping")
    assert cli("coupons").stdout.splitlines() == ["FIVE\tfixed\t5.00\t0/-", "SAVE10\tpercent\t10%\t0/3",
                                                  "SHIP\tfree_shipping\t-\t0/-"]


def test_report_daily(cli):
    _setup(cli)
    cli("order", "BOOK", "--customer", "Kim")
    cli("pay", "1001")
    out = cli("report", "daily", "2026-03-01").stdout.splitlines()
    assert out == ["date\t2026-03-01", "orders\t1", "gross\t37.93", "refunds\t0.00", "net\t37.93", "tax\t3.03"]


def test_refund_and_orders_listing(cli):
    _setup(cli)
    cli("order", "MUG:3", "--customer", "Kim")
    cli("pay", "1001")
    cli("ship", "1001")
    assert cli("refund", "1001", "MUG:1").stdout.strip() == "환불 1: 10.12"
    assert cli("refund", "1001").returncode == 1
    assert cli("orders").stdout.splitlines() == ["1001\t2026-03-01\tKim\tshipped\t36.18"]


def test_config(cli):
    assert cli("config").stdout.splitlines() == ["locale\tdefault", "tax_display\texclusive"]
    assert cli("config", "locale", "eu").returncode == 0
    assert cli("config", "locale").stdout.strip() == "eu"
    assert cli("config", "locale", "fr").returncode == 1
    data = json.loads(cli.data.read_text(encoding="utf-8"))
    assert data["settings"]["locale"] == "eu"
