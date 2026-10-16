텍스트 장부(복식부기)를 읽고 잔액과 환산 보고서를 만드는 Python 패키지 `ledger` 를 만든다.

- 패키지는 작업 폴더 최상위의 `ledger/` 에 둔다 (src 레이아웃을 쓰지 말 것). 표준 라이브러리만 쓴다.
- 파싱, 잔액 계산, 보고서는 서로 다른 모듈로 나눈다. 금액은 모두 `decimal.Decimal` 로 다루고 float 를 쓰지 않는다.
- 아래 이름과 동작을 정확히 지킨다. 다른 사람이 이 인터페이스로 테스트한다.

## 장부 형식

```
; 주석
2026-01-03 Coffee shop
    expenses:food        4.50 USD
    assets:cash
2026-01-04 Salary
    assets:bank      1,200.00 USD
    income:salary   (1,200.00) USD
```

- 거래 머리줄: 들여쓰기 없이 `YYYY-MM-DD 설명`. 설명은 날짜 뒤 나머지를 앞뒤 공백 제거한 것(비어도 됨). 날짜가 달력에 없는 날이면 오류.
- 거래 항목줄: 공백이나 탭으로 들여쓴 줄. `계정`, 그 뒤에 **공백 2개 이상 또는 탭**, 그 뒤에 `금액 통화`(공백 하나로 구분). 금액 없이 계정만 쓸 수도 있다.
- 계정: `:` 로 나눈 이름들. 각 이름은 비어 있지 않고, 안에 공백 하나는 들어갈 수 있다(`expenses:eating out`).
- 금액: 앞에 `-` 를 붙이거나 괄호 `(12.00)` 로 감싸면 음수. 천 단위 `,` 는 쓸 수 있지만 쓰려면 3자리씩 정확히(`1,234.5` 는 되고 `12,34` 는 오류). 소수점은 `.`.
- 통화: 대문자 3글자. 소수 자릿수: JPY·KRW 는 0, 나머지는 모두 2. 금액의 소수 자릿수가 통화 자릿수보다 많으면 오류(`4.505 USD` 는 오류, `4.5 USD` 는 됨).
- 공백을 뺀 첫 글자가 `;` 인 줄은 주석, 빈 줄은 무시한다.
- 거래마다 항목이 2개 이상이어야 하고, **통화별로** 합이 0 이어야 한다.
- 금액을 생략한 항목은 거래당 하나까지. 그 항목은 나머지 항목 합의 반대 금액을 갖는다. 나머지 항목이 두 통화 이상이면 오류.
- 첫 머리줄 앞의 항목줄, 형식이 틀린 줄도 오류.

## 인터페이스

- `ledger.LedgerError` : `ValueError` 의 하위 클래스. 장부 오류면 `lineno` 속성에 1부터 센 줄 번호가 있다. 거래 전체의 오류(합이 0 이 아님, 항목 부족, 생략 항목 2개 등)는 그 거래 머리줄의 번호. 장부와 관계없는 오류(환율 없음 등)는 `lineno` 가 `None`.
- `ledger.parse(text) -> list[Transaction]` : 장부 순서대로. `Transaction` 은 `date`(datetime.date), `description`(str), `postings`(list) 속성. `Posting` 은 `account`(str), `amount`(Decimal), `currency`(str) 속성. 생략된 금액은 채워 넣은 값.
- `ledger.balances(transactions, as_of=None, depth=None) -> dict[str, dict[str, Decimal]]`
  - 계정 → 통화 → 잔액. 0 인 통화는 빼고, 남는 통화가 없는 계정도 뺀다. 계정 이름순으로 정렬된 dict.
  - `as_of`(date) 를 주면 그 날짜 **이하**의 거래만.
  - `depth` 를 주면 계정을 앞에서 `depth` 개 이름까지로 줄여서 합친다(`assets:bank:checking`, depth=1 → `assets`). 1 미만이면 `ValueError`.
- `ledger.report(transactions, currency, rates, as_of=None, depth=None) -> str`
  - `balances(...)` 의 각 계정을 `currency` 하나로 환산한다. `rates` 는 `{("EUR", "USD"): Decimal("1.10")}` 처럼 `1 EUR = 1.10 USD`. 같은 통화는 그대로, `(원래, 목표)` 가 없고 `(목표, 원래)` 가 있으면 그 역수를 쓴다. 둘 다 없으면 `LedgerError`.
  - 환산은 계정마다 정확한 값으로 더한 뒤 **계정마다 한 번만** 목표 통화 자릿수로 반올림한다. 반올림은 `ROUND_HALF_EVEN`(은행가 반올림).
  - 반올림한 값이 0 인 계정은 빼고, 계정 이름순으로 한 줄씩 `계정\t금액`. 마지막 줄은 `TOTAL\t금액`.
  - **TOTAL 은 위에 표시된(반올림된) 금액들의 합이다** (보고서의 숫자가 눈으로 더해 맞아야 한다).
  - 금액 표시: 천 단위 `,`, 소수는 통화 자릿수만큼 고정, 음수는 앞에 `-` (`-1,234.50`, `1,235`).
  - 줄마다 `\n` 으로 끝난다.
