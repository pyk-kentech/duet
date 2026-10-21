# stock

작은 재고 관리 라이브러리와 CLI. 표준 라이브러리만 쓴다.

```bash
python -m stock [--db stock.json] add SKU NAME [--cost 단가]
python -m stock receive SKU QTY [--note 메모]
python -m stock ship SKU QTY [--note 메모]
python -m stock adjust SKU DELTA --reason 사유
python -m stock list                # SKU<TAB>NAME<TAB>ON_HAND
python -m stock value               # TOTAL<TAB>금액
python -m stock low THRESHOLD
python -m stock history [SKU]
```

오류는 표준 오류에 `오류: ...`, 종료 코드 1. 데이터는 JSON(`version: 1`).

테스트: `python3 -m pytest -q`
