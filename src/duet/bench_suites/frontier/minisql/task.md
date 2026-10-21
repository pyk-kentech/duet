작업 폴더 최상위에 파이썬 패키지 `minisql`(표준 라이브러리만, Python 3.11 이상)을 만든다. SQLite 의 SQL 일부분을 처리하는 인메모리 SQL 엔진이다. 패키지는 작업 폴더 바로 아래 `minisql/` 에 둔다(src 레이아웃 아님). 아래의 이름·시그니처는 그대로 지킨다. 다른 사람이 이 인터페이스로 테스트한다. 테스트도 함께 작성한다.

- **`sqlite3`·`_sqlite3` 모듈은 어떤 방식으로도 쓰지 않는다.** 채점은 `minisql/` 안의 모든 `.py` 파일에 `sqlite3` 라는 글자(대소문자 무시, 주석·문자열 포함)가 하나라도 있으면 실패로 본다. 직접 만드는 테스트는 패키지 밖에 두고, 거기서는 `sqlite3` 와 결과를 비교해도 된다.

## 기준과 채점

- **지원 범위 안에서 결과는 같은 SQL 을 SQLite(파이썬 `sqlite3`, `sqlite3.connect(":memory:")`)에 돌린 결과와 같아야 한다**: 행의 값과 파이썬 타입, 결과 열 이름, 바뀐 행 수(rowcount), 오류가 나는지 여부.
- 채점 테스트는 같은 준비 문장과 질의를 새 `sqlite3` 연결과 새 `minisql.connect()` 에 차례로 돌려 비교한다. 행 순서는 ORDER BY 가 순서를 완전히 정하는 질의에서만 보고, 나머지는 행 묶음(중복 포함)으로 비교한다. REAL 은 아주 작은 상대 오차(1e-9)를 허용한다. 오류 메시지 문구는 보지 않는다.
- 아래에 SQLite 의 규칙을 자세히 적었다. **채점이 확인하는 동작은 모두 이 문서에 적혀 있다.** "범위 밖" 에 적은 것과 이 문서에 없는 기능은 테스트하지 않는다(그런 입력에는 무엇을 해도 된다). SQLite 3.31 이후 버전에서 동작이 같은 것만 테스트한다.

## 공개 API

```python
import minisql

con = minisql.connect()            # 매번 새 빈 데이터베이스 (연결끼리 공유하지 않음)
cur = con.execute(sql, params=())  # 문장 하나를 실행하고 Cursor 를 돌려준다
cur.fetchone()                     # 다음 행(tuple), 없으면 None
cur.fetchall()                     # 남은 행 전부 (list[tuple])
for row in cur: ...                # 남은 행
cur.description                    # SELECT: 결과 열마다 (이름, None, None, None, None, None, None) 인 tuple 들의 tuple. 그 밖의 문장: None
cur.rowcount                       # INSERT: 넣은 행 수, UPDATE: WHERE 에 맞은 행 수, DELETE: 지운 행 수. SELECT·CREATE TABLE: -1
con.executescript(sql)             # ';' 로 나뉜 여러 문장을 차례로 실행 (자리표시자 없음)
minisql.Error                      # 모든 오류의 기반 클래스 (Exception 의 하위 클래스)
```

- `execute`: 문장 하나와, 그 뒤의 `;`·공백·주석만 허용한다. 문장이 둘 이상이면 `Error`. `params` 는 시퀀스이고 `?` 자리표시자를 나온 순서대로 채운다. 개수가 맞지 않으면 `Error`. 값은 `None`, `int`, `float`, `str`.
- `executescript`: 문자열 리터럴·주석 안의 `;` 로는 나누지 않는다.
- 결과 값의 파이썬 타입: NULL → `None`, INTEGER → `int`(**`bool` 이 아니다**: 비교·논리 연산 결과도 `0`/`1` 인 `int`), REAL → `float`, TEXT → `str`.
- SELECT 결과에 행이 없어도 `description` 은 있다.
- 오류는 `minisql.Error`(또는 그 하위 클래스)로 낸다. `execute` 안에서 내는 것이 원칙이고, 늦어도 결과를 가져올 때(`fetch*`) 낸다. **오류가 난 문장은 데이터를 바꾸지 않는다.** **이름·문법 오류는 테이블이 비어 있어도 난다**(계산할 행이 없어도 `SELECT nosuch FROM 빈테이블` 은 오류).

## 어휘

- 키워드는 대소문자를 가리지 않는다. 이 과제의 키워드: `SELECT DISTINCT ALL FROM WHERE GROUP BY HAVING ORDER ASC DESC NULLS FIRST LAST LIMIT OFFSET AS JOIN INNER LEFT OUTER CROSS ON USING UNION INTERSECT EXCEPT INSERT INTO VALUES UPDATE SET DELETE CREATE TABLE AND OR NOT NULL IS IN BETWEEN LIKE ESCAPE EXISTS CASE WHEN THEN ELSE END CAST`. 테스트는 이 낱말과 SQLite 의 다른 키워드를 테이블·열·별칭 이름으로 쓰지 않는다.
- 이름(테이블·열·별칭): `[A-Za-z_][A-Za-z0-9_]*`, 또는 큰따옴표로 감싼 이름(`"Pay Rate"`, 안의 `"` 는 `""`). **이름 비교는 ASCII 대소문자를 가리지 않는다**(`name`, `NAME`, `"Name"` 은 같은 열, 테이블·별칭도 같다). 테스트에서 큰따옴표 이름은 항상 실제로 있는 이름이나 별칭이다.
- 문자열 리터럴: 작은따옴표, 안의 `'` 는 `''`. 백슬래시는 보통 글자다(`'a\b'` 는 세 글자). 닫히지 않은 문자열은 오류.
- 숫자 리터럴: `123` 은 INTEGER. 소수점이나 지수가 있으면 REAL(`1.5`, `.5`, `2.`, `1e3`, `1E-2`). 음수는 단항 `-` 다.
- `NULL`, 자리표시자 `?`, 주석 `-- 줄 끝까지` 와 `/* ... */`.

## 값, 타입, 친화도

값은 NULL, INTEGER(64비트 정수), REAL(배정밀도 실수), TEXT 네 가지다.

### 열 친화도 (CREATE TABLE 의 타입 이름)

타입 이름(없어도 됨, 예 `INTEGER`, `VARCHAR(10)`, `DOUBLE PRECISION`)을 대문자로 바꿔 아래를 **이 순서대로** 본다. 부분 문자열 검사다.

1. `INT` 가 들어 있으면 INTEGER. (`INT`, `BIGINT`, `CHARINT` … 그리고 `FLOATING POINT` 도 `POINT` 안에 `INT` 가 있어서 INTEGER)
2. `CHAR`, `CLOB`, `TEXT` 중 하나가 들어 있으면 TEXT. (`VARCHAR(10)`, `CHARACTER(20)`)
3. `BLOB` 이 들어 있거나 타입 이름이 없으면 BLOB. (BLOB 친화도는 아래 비교 규칙에서 "친화도 없음" 과 다르게 다뤄진다)
4. `REAL`, `FLOA`, `DOUB` 중 하나가 들어 있으면 REAL. (`FLOAT`, `DOUBLE PRECISION`)
5. 그 밖에는 NUMERIC. (`NUMERIC`, `DECIMAL(10,2)`, `BOOLEAN`, `DATE`, `STRING`)

### 숫자 모양 텍스트

앞뒤 공백을 빼면 전체가 `[+-]?(숫자+(.숫자*)?|.숫자+)([eE][+-]?숫자+)?` 인 텍스트. 예: `'5'`, `' 7 '`, `'+3'`, `'-0'`, `'2.50'`, `'.5'`, `'5.'`, `'1e2'`. 16진수(`'0x10'`), 빈 문자열, `'12abc'`, `'1,000'` 은 아니다. 소수점·지수가 없으면 INTEGER, 있으면 REAL 로 읽는다.

### 저장할 때의 변환 (INSERT, UPDATE)

열에 값을 넣을 때 열 친화도에 따라 바꾼다. NULL 은 바뀌지 않는다.

- INTEGER, NUMERIC: 숫자 모양 텍스트는 수로 바꾼다. REAL(텍스트에서 읽은 것 포함)이 정수와 같은 값이면 INTEGER 로 바꾼다: `'5'` → 5, `'5.0'` → 5, `5.0` → 5, `'1e2'` → 100, `'2.5'` → 2.5(REAL), `'0123'` → 123. 다른 텍스트는 그대로 TEXT 로 저장한다(`'abc'`, `''`, `'12abc'`).
- REAL: 숫자 모양 텍스트와 INTEGER 를 REAL 로 바꾼다(`'5'` → 5.0, `3` → 3.0). 다른 텍스트는 그대로.
- TEXT: INTEGER·REAL 을 텍스트로 바꾼다(아래 "수 → 텍스트": `5` → `'5'`, `2.50` → `'2.5'`, `1.0` → `'1.0'`).
- BLOB: 바꾸지 않는다(`'5'` 는 TEXT, `5` 는 INTEGER, `2.0` 은 REAL 그대로).

### 수 → 텍스트

INTEGER 는 10진수 그대로. REAL 은 C 의 `printf("%.15g")`(유효숫자 15자리) 결과에 소수점도 지수도 없으면 `.0` 을 붙인다: `1.0` → `'1.0'`, `2.50` → `'2.5'`, `100.0` → `'100.0'`, `-0.25` → `'-0.25'`. (테스트는 지수 표기가 나오는 값이나 유효숫자 15자리로 정확히 나타나지 않는 값을 텍스트로 바꾸지 않는다)

### 텍스트 → 수 (산술 등)

산술 연산과 몇몇 함수는 TEXT 를 이렇게 수로 바꿔 쓴다: 앞 공백을 건너뛰고, 그 뒤에서 숫자 모양으로 읽을 수 있는 **가장 긴 앞부분**을 쓴다. 그 앞부분에 소수점이나 지수가 있으면 REAL, 없으면 INTEGER. 읽을 수 있는 앞부분이 없으면 INTEGER 0. 예: `'12abc'` → 12, `'1.5kg'` → 1.5, `'abc'` → 0, `''` → 0, `' 7 '` → 7, `'3.0'` → 3.0(REAL), `'2.5e1'` → 25.0.

### 참과 거짓

WHERE·ON·HAVING·`CASE WHEN`·AND·OR·NOT 에서: NULL 은 UNKNOWN(알 수 없음). 수는 0 이 아니면 참. TEXT 는 위 "텍스트 → 수" 로 바꿔 0 이 아니면 참(`'abc'`, `'0'` 거짓, `'1abc'`, `'2x'` 참). 조건이 참인 행·그룹만 남는다(거짓·UNKNOWN 은 버림). (테스트는 -1 과 1 사이의 0 이 아닌 실수를 참·거짓으로 쓰지 않는다)

## 식

### 연산자 우선순위 (높은 것부터)

1. 단항 `-`, `+`
2. `||`
3. `*` `/` `%`
4. `+` `-`
5. `<` `<=` `>` `>=`
6. `=` `==` `!=` `<>` `IS` `IS NOT` `IN` `NOT IN` `LIKE` `NOT LIKE` `BETWEEN` `NOT BETWEEN` (모두 같은 단계)
7. `NOT`
8. `AND`
9. `OR`

같은 단계의 이항 연산자는 왼쪽부터 묶는다. 그래서 `1 = 2 < 3` 은 `1 = (2 < 3)` 이라 1, `2 + 3 || 'x'` 는 `2 + (3 || 'x')` = `2 + '3x'` = 5, `10 - 2 || 1` 은 `10 - '21'` = -11, `NOT 1 = 2` 는 `NOT (1 = 2)` 다. `x BETWEEN a AND b` 의 a, b 는 5단계 이상의 식이다: `1 BETWEEN 0 AND 2 = 1` 은 `(1 BETWEEN 0 AND 2) = 1`, `2 BETWEEN 1 AND 3 AND 0` 은 `(2 BETWEEN 1 AND 3) AND 0`. `==` 는 `=`, `<>` 는 `!=` 와 같다.

### 산술 `+ - * / %`

- 피연산자 하나라도 NULL 이면 NULL. TEXT 피연산자는 "텍스트 → 수" 로 바꾼다.
- 둘 다 INTEGER: 결과 INTEGER(넘침은 테스트하지 않음). `/` 는 **0 쪽으로 버리는 정수 나눗셈**(`7/2` = 3, `-7/2` = -3, `7/-2` = -3, `1/3` = 0). `%` 의 부호는 **왼쪽 피연산자**를 따른다(`-7 % 3` = -1, `7 % -3` = 1).
- 하나라도 REAL: `+ - * /` 는 실수 연산(`7/2.0` = 3.5). `%` 는 **두 피연산자를 0 쪽으로 버려 정수로 만든 뒤** 나머지를 구하고 결과를 REAL 로 낸다(`5.5 % 2` = 1.0, `-7.5 % 2` = -1.0, `5 % 2.5` = 1.0).
- 0 으로 나누면 NULL: `1/0`, `1%0`, `1.0/0`, `1/0.0`, 그리고 정수로 버린 오른쪽이 0 인 `5 % 0.5`.
- 단항 `-`: NULL → NULL, TEXT 는 수로 바꿔 부호를 바꾼다(`-'3'` = -3, `-'abc'` = 0, `-'1.5'` = -1.5).
- 단항 `+`: **아무것도 바꾸지 않는다**(`+'abc'` = `'abc'`, `typeof(+'5')` = `'text'`).

### 이어 붙이기 `||`

하나라도 NULL 이면 NULL. 아니면 두 값을 텍스트로 바꿔("수 → 텍스트") 잇는다: `1.0 || 'x'` = `'1.0x'`, `5 || 2` = `'52'`, `1e2 || ''` = `'100.0'`. 결과는 TEXT.

### 비교 `= == != <> < <= > >=`

- 하나라도 NULL 이면 결과는 NULL(`NULL = NULL` 도 NULL). 결과는 1, 0, NULL.
- 비교 전에 아래 "비교할 때의 친화도 변환" 을 적용한다.
- 값의 순서: **INTEGER·REAL < TEXT**. 수끼리는 수의 크기로(`1 = 1.0` 참). TEXT 끼리는 유니코드 코드 포인트 순서(대소문자 구분: `'B' < 'a'`, `'10' < '9'`, `'abc' = 'ABC'` 은 0). 변환되지 않은 수와 텍스트는 같지 않고 텍스트가 크다: `'5' = 5` 는 0, `'a' > 99` 는 1, `'' > 0` 은 1.

### 비교할 때의 친화도 변환

모든 식에는 친화도가 있다.

- 열 참조: 그 열의 친화도(INTEGER, REAL, NUMERIC, TEXT, BLOB). FROM 에 쓴 하위 질의의 열은 그 하위 질의 결과 식의 친화도(결과 식이 열 참조면 그 열의 친화도, 다른 식이면 친화도 없음).
- `CAST(x AS T)`: T 의 친화도(열 친화도 규칙).
- 스칼라 하위 질의 `(SELECT e ...)`: e 의 친화도.
- 괄호는 영향이 없다. **그 밖의 모든 식은 친화도가 없다**: 리터럴, 자리표시자, 산술·`||`·비교 결과, 함수·집계 결과, 단항 `+`·`-`, CASE.

두 피연산자를 비교하기 전에:

1. 둘 다 친화도가 있으면(BLOB 포함): 하나라도 INTEGER·REAL·NUMERIC 이면 두 값 모두에 NUMERIC 변환. 아니면(TEXT·BLOB 끼리) 변환하지 않는다.
2. 한쪽만 친화도가 있으면: 그 친화도가 INTEGER·REAL·NUMERIC 이면 두 값에 NUMERIC 변환, TEXT 면 두 값에 TEXT 변환, BLOB 이면 변환하지 않는다.
3. 둘 다 친화도가 없으면 변환하지 않는다.

- NUMERIC 변환: 숫자 모양 텍스트(앞뒤 공백 허용)를 수로 바꾼다. 다른 값은 그대로.
- TEXT 변환: INTEGER·REAL 을 텍스트로 바꾼다("수 → 텍스트"). 다른 값은 그대로.

예: `t(i INTEGER, s TEXT, b)` 에 `i`=5, `s`='5', `b`=5 가 있으면 `i = '5'` 참, `i = '5.0'` 참, `s = 5` 참, `s = 5.0` 은 `'5' = '5.0'` 이라 거짓, `s < 10` 은 `'5' < '10'` 이라 **거짓**, `b = '5'` 거짓, `b = 5` 참, `i = s` 참, `i + 0 = '5'` 거짓(왼쪽은 친화도 없음), `s || '' = 5` 거짓, `'5' = 5` 거짓, `(SELECT s FROM t) = 5` 참, `CAST(i AS TEXT) = '5'` 참. INTEGER 열에 들어 있는 TEXT 값(`'abc'`)은 NUMERIC 변환으로도 바뀌지 않으므로 어떤 수보다 크다.

이 변환은 `IS`, `IS NOT`, BETWEEN 의 두 비교, `CASE x WHEN v`(x 와 v 를 `=` 로 비교), IN(아래), USING 조인 조건에도 똑같이 적용한다.

### IS, IS NOT

`a IS b`: 둘 다 NULL 이면 1, 하나만 NULL 이면 0, 아니면 `a = b` 와 같다(친화도 변환 포함). 결과는 NULL 이 되지 않는다. `IS NOT` 은 그 반대. `x IS NULL`, `x IS NOT NULL` 도 이 규칙이다(`1 IS 1.0` 은 1, `'1' IS 1` 은 0).

### 논리 (3값)

- `AND`: 하나라도 거짓이면 0, 아니면 하나라도 UNKNOWN 이면 NULL, 아니면 1. (`NULL AND 0` = 0, `NULL AND 1` = NULL)
- `OR`: 하나라도 참이면 1, 아니면 하나라도 UNKNOWN 이면 NULL, 아니면 0. (`NULL OR 1` = 1, `NULL OR 0` = NULL)
- `NOT`: 참 → 0, 거짓 → 1, UNKNOWN → NULL.

### BETWEEN

`x BETWEEN a AND b` 는 `x >= a AND x <= b` 와 같다(x 는 한 번만 계산, 두 비교에 각각 친화도 변환). 그래서 `1 BETWEEN NULL AND 0` 은 0, `3 BETWEEN 1 AND NULL` 은 NULL. `x NOT BETWEEN a AND b` 는 `NOT (x BETWEEN a AND b)`.

### IN

- `x IN (v1, v2, ...)`: 목록의 값들은 (열 참조라도) 친화도가 없는 것으로 보고 x 와 각 값을 `=` 로 비교한다. 즉 x 의 친화도만 따른다: `i IN ('5')` 참, `s IN (5)` 참, `'5' IN (i)` 거짓, `5 IN (s, b)` 는 `b` 때문에만 참.
- `x IN (SELECT e ...)`: 하위 질의의 결과 열은 정확히 하나여야 한다(아니면 오류). x 와 각 결과 값을 `x = e` 처럼 비교한다(e 의 친화도 포함): `s IN (SELECT 9)` 는 `s` = '9' 인 행에서 참.
- 결과: **목록이나 하위 질의 결과가 비어 있으면 x 가 NULL 이어도 0**. 아니면, x 가 NULL 이면 NULL. 같은 값이 있으면 1. 없고 목록·결과에 NULL 이 있으면 NULL. 그 밖에는 0.
- `x NOT IN (...)` 은 `NOT (x IN (...))`: `3 NOT IN (1, NULL)` 은 NULL, 빈 목록·빈 결과면 1. 그래서 `WHERE id NOT IN (SELECT 열)` 은 하위 질의 결과에 NULL 이 하나라도 있으면 아무 행도 남기지 않는다.
- 빈 목록 `x IN ()` 도 허용한다(항상 0, `NOT IN ()` 은 항상 1).

### LIKE

`x LIKE p` 또는 `x LIKE p ESCAPE e`: x, p(, e) 중 하나라도 NULL 이면 NULL. x, p 를 텍스트로 바꾼 뒤 **x 전체**가 패턴 p 에 맞으면 1, 아니면 0. `%` 는 0개 이상의 아무 글자, `_` 는 정확히 한 글자(줄바꿈·한글·`é` 도 한 글자). **ASCII 영문자 A–Z/a–z 만 대소문자를 무시**한다(`'abc' LIKE 'ABC'` 참, `'é' LIKE 'É'` 거짓). ESCAPE 의 e 는 한 글자이고, 패턴에서 e 다음 글자는 보통 글자로 맞춘다(`'10%' LIKE '10!%' ESCAPE '!'` 참, `'100' LIKE '10!%' ESCAPE '!'` 거짓). 친화도 변환은 하지 않는다(`12 LIKE '1%'` 참, `2.0 LIKE '2.0'` 참). `x NOT LIKE p` 는 `NOT (x LIKE p)`.

### CASE

- `CASE WHEN c1 THEN r1 [WHEN ...] [ELSE e] END`: 처음으로 참인 c 의 r. 없으면 e, ELSE 가 없으면 NULL.
- `CASE x WHEN v1 THEN r1 ... [ELSE e] END`: x 를 한 번 계산하고, `x = v` 가 1 인 첫 v 의 r. x 가 NULL 이면 어떤 WHEN 에도 맞지 않는다(`CASE NULL WHEN NULL THEN 'x' ELSE 'y' END` 는 `'y'`). `CASE 1.0 WHEN 1 ...` 은 맞고, `CASE '1' WHEN 1 ...` 은 맞지 않는다.

### CAST(x AS 타입)

타입 이름의 친화도(열 친화도 규칙)로 바꾼다. NULL 은 NULL.

- INTEGER: INTEGER 는 그대로, REAL 은 0 쪽으로 버림(`CAST(-2.7 AS INTEGER)` = -2). TEXT 는 앞 공백을 건너뛴 뒤의 `[+-]?숫자+` 부분만 정수로(`'12.7'` → 12, `' 42abc'` → 42, `'-3.9'` → -3, `'+8'` → 8, `'abc'` → 0). (테스트는 지수가 든 텍스트를 쓰지 않는다)
- REAL: INTEGER → REAL, REAL 은 그대로, TEXT 는 "텍스트 → 수" 의 값을 REAL 로(`'1.5abc'` → 1.5, `'abc'` → 0.0, `'12'` → 12.0, `' 2.5 '` → 2.5).
- TEXT: "수 → 텍스트"(`CAST(2.5 AS TEXT)` = `'2.5'`, `CAST(1.0 AS TEXT)` = `'1.0'`).
- NUMERIC: INTEGER·REAL 은 **그대로**(`CAST(3.0 AS NUMERIC)` = 3.0). TEXT 는 "텍스트 → 수" 로 바꾸고, 그것이 정수와 같은 REAL 이면 INTEGER 로(`'3.0'` → 3, `'3.5'` → 3.5, `'12abc'` → 12, `'abc'` → 0).

### 하위 질의

- 스칼라 `(SELECT ...)`: 결과 열이 하나여야 한다(아니면 오류). 첫 행의 값, 행이 없으면 NULL. 행이 여럿이면 하위 질의 자신의 ORDER BY 로 정해지는 첫 행.
- `EXISTS (SELECT ...)`: 행이 하나라도 있으면 1, 없으면 0(NULL 이 되지 않는다). `NOT EXISTS (...)` 는 `NOT (EXISTS (...))` 이다.
- 하위 질의는 바깥 질의의 열을 참조할 수 있다(상관 하위 질의, 여러 단계 바깥도 가능). 바깥 행마다 다시 계산한 것과 결과가 같아야 한다.

## 함수

이름은 대소문자를 가리지 않는다. 없는 함수나 인자 수가 틀린 호출은 오류. 아래에서 "텍스트로" 는 "수 → 텍스트", "정수로" 는 INTEGER 그대로·REAL 은 0 쪽 버림·TEXT 는 `CAST(... AS INTEGER)` 와 같은 정수 앞부분이다.

- `abs(x)`: NULL → NULL, INTEGER → INTEGER, REAL → REAL. **TEXT 는 "텍스트 → 수" 의 절댓값을 REAL 로**(`abs('-5')` = 5.0, `abs('abc')` = 0.0, `abs('-2.5x')` = 2.5).
- `length(x)`: NULL → NULL. 텍스트로 바꾼 뒤의 글자(코드 포인트) 수(`length(12)` = 2, `length(2.0)` = 3, `length(-1.5)` = 4, `length('héllo')` = 5).
- `upper(x)`, `lower(x)`: NULL → NULL. 텍스트로 바꾼 뒤 **ASCII 영문자만** 바꾼다(`upper('é abc')` = `'é ABC'`, `upper('straße')` = `'STRAßE'`). 결과는 TEXT(`upper(5)` = `'5'`).
- `substr(x, y)`, `substr(x, y, z)`: 인자 중 하나라도 NULL 이면 NULL. x 를 텍스트로, y·z 를 정수로 바꾼다. 글자 단위이며 SQLite 의 계산을 그대로 따른다(y = 0 은 테스트하지 않는다):
  ```
  s = 텍스트(x); L = s 의 글자 수; p1 = 정수(y)
  z 가 있으면 p2 = 정수(z), 없으면 p2 = 무한대;  neg = (z 가 있고 p2 < 0)
  if neg: p2 = -p2
  if p1 < 0:
      p1 = p1 + L
      if p1 < 0: p2 = p2 + p1; (p2 < 0 이면 p2 = 0); p1 = 0
  else:            # p1 > 0
      p1 = p1 - 1
  if neg:
      p1 = p1 - p2
      if p1 < 0: p2 = p2 + p1; p1 = 0
  결과 = s 의 [p1, p1 + p2) 글자 (s 를 벗어나는 부분은 없음)
  ```
  예: `substr('abcde', 2)` = `'bcde'`, `substr('abcde', 2, 2)` = `'bc'`, `substr('abcde', -2)` = `'de'`, `substr('abcde', 3, -2)` = `'ab'`, `substr('abcde', -10, 7)` = `'ab'`, `substr(12345, 2, 3)` = `'234'`, `substr('abcde', 2.7, 1.9)` = `'b'`.
- `trim(x)`, `ltrim(x)`, `rtrim(x)`, `trim(x, y)`, `ltrim(x, y)`, `rtrim(x, y)`: 인자 중 하나라도 NULL 이면 NULL. x 를 텍스트로 바꿔 양 끝(ltrim 은 왼쪽, rtrim 은 오른쪽)에서 y(텍스트로)에 든 글자들을 모두 지운다. **y 가 없으면 공백 `' '` 만** 지운다(탭·줄바꿈은 지우지 않는다). y 가 빈 문자열이면 아무것도 지우지 않는다. 결과는 TEXT(`rtrim(12300, '0')` = `'123'`).
- `replace(x, y, z)`: x 나 y 가 NULL 이면 NULL. y 를 텍스트로 바꾼 것이 빈 문자열이면 **x 를 그대로(타입도 그대로) 돌려준다**(`replace(5, '', 1)` 은 INTEGER 5, z 가 NULL 이어도). 그 밖에 z 가 NULL 이면 NULL. 아니면 모두 텍스트로 바꿔 x 안의 y 를 왼쪽부터 겹치지 않게 모두 z 로 바꾼다(`replace('aaa', 'aa', 'b')` = `'ba'`, 대소문자 구분).
- `instr(x, y)`: 하나라도 NULL 이면 NULL. 텍스트로 바꿔 x 에서 y 가 처음 나오는 글자 위치(1 부터), 없으면 0. y 가 빈 문자열이면 1. 대소문자 구분.
- `round(x)`, `round(x, n)`: x 나 n 이 NULL 이면 NULL. 결과는 **항상 REAL**. n 은 정수로 바꾸고 음수면 0. x 를 REAL 로(TEXT 는 "텍스트 → 수") 바꿔 소수점 아래 n 자리로 반올림하고 **정확히 가운데면 0 에서 먼 쪽**으로(`round(2.5)` = 3.0, `round(-2.5)` = -3.0, `round(0.5)` = 1.0, `round(0.125, 2)` = 0.13, `round(7)` = 7.0, `round(2.5, -1)` = 3.0). (테스트는 이진 실수로 정확히 나타나는 가운데 값이나 가운데에서 떨어진 값만 쓴다)
- `coalesce(a, b, ...)`(인자 2개 이상): NULL 이 아닌 첫 값(타입 그대로), 없으면 NULL. `ifnull(a, b)` 는 인자 2개짜리 coalesce.
- `nullif(a, b)`: a 와 b 가 같으면 NULL, 아니면 a. 같음은 **변환 없이** 비교한다(`nullif(1, 1.0)` 은 NULL, `nullif('1', 1)` 은 `'1'`, `nullif('a', 'A')` 는 `'a'`). b 가 NULL 이면 a.
- `typeof(x)`: `'null'`, `'integer'`, `'real'`, `'text'` 중 하나.
- `max(a, b, ...)`, `min(a, b, ...)`(인자 2개 이상이면 스칼라 함수): **인자 중 하나라도 NULL 이면 NULL**. 아니면 값의 순서(수 < 텍스트, 변환 없음)로 가장 큰·작은 인자(타입 그대로). (같은 순위의 서로 다른 값, 예 2 와 2.0 중 무엇이 나오는지는 테스트하지 않는다) 인자가 하나면 집계 함수다.

## 집계

- 집계 함수: `count(*)`, `count(x)`, `sum(x)`, `total(x)`, `avg(x)`, `min(x)`, `max(x)`, `group_concat(x)`, `group_concat(x, sep)`. `count(x)`·`sum`·`total`·`avg`·`min`·`max`·`group_concat(x)` 앞에는 `DISTINCT` 를 붙일 수 있다(`count(DISTINCT x)`): "같은 값"(아래)은 한 번만 쓴다. 모든 집계는 NULL 을 무시한다(`count(*)` 는 행 수).
- `count(x)`: NULL 이 아닌 값의 수.
- `sum(x)`: NULL 이 아닌 값이 없으면 **NULL**. 모두 INTEGER 면 INTEGER, 하나라도 REAL 이면 REAL.
- `total(x)`: 합을 항상 REAL 로. 값이 없으면 **0.0**.
- `avg(x)`: 평균을 항상 REAL 로(정수들의 평균도 REAL). 값이 없으면 NULL.
- `min(x)`, `max(x)`: 값의 순서(수 < 텍스트)로 가장 작은·큰 값. 값이 없으면 NULL.
- `group_concat(x[, sep])`: 텍스트로 바꾼 값들을 sep(기본 `','`)로 잇는다. 값이 없으면 NULL. 잇는 순서는 정해지지 않았다(테스트는 순서에 기대지 않는다).
- (sum·total·avg 에 TEXT 값을 넣는 경우와 정수 넘침은 테스트하지 않는다)
- **집계 질의**: GROUP BY 가 있거나 SELECT 목록에 집계 함수가 있는 SELECT.
  - **GROUP BY 가 없는 집계 질의는 입력 행이 없어도 결과가 정확히 한 행**이다: `SELECT count(*), sum(x), total(x), max(x) FROM t WHERE 0` → `(0, None, 0.0, None)`. FROM 없는 `SELECT count(*)` 는 1.
  - GROUP BY 가 있으면 입력 행이 없을 때 결과 행도 없다.
  - GROUP BY: 키 식들의 값이 모두 "같은 값" 인 행들이 한 그룹이다. NULL 키끼리 한 그룹.
  - HAVING: 그룹을 거른다(조건이 참인 그룹만). SELECT 목록에 없는 집계도 쓸 수 있다. (HAVING 은 GROUP BY 와 함께만 테스트한다)
  - 집계 질의의 SELECT 목록·HAVING·ORDER BY 에서 집계 밖에 나오는 열은 GROUP BY 키에 쓴 것만 테스트한다(`SELECT dept, upper(dept), count(*) ... GROUP BY dept` 처럼).
  - 집계 함수를 WHERE 나 GROUP BY 에 쓰면 오류.

**같은 값** (GROUP BY, DISTINCT, UNION·INTERSECT·EXCEPT, 집계의 DISTINCT): 변환 없이 비교해 같은 값. NULL 과 NULL 은 같다. `1` 과 `1.0` 은 같고 `'1'` 과 `1` 은 다르다. (`1` 과 `1.0` 처럼 같지만 타입이 다른 값 중 어느 것이 결과에 남는지는 테스트하지 않는다)

## 문장

### CREATE TABLE

`CREATE TABLE 이름 (열 [타입], ...)`. 타입은 이름 하나 이상(`DOUBLE PRECISION`)에 `(수)` 또는 `(수, 수)` 가 붙을 수 있다(`VARCHAR(10)`, `DECIMAL(10,2)`). 같은 이름의 테이블이 이미 있거나 열 이름이 겹치면(대소문자 무시) 오류.

### INSERT

- `INSERT INTO t [(열, ...)] VALUES (식, ...), (식, ...), ...` 와 `INSERT INTO t [(열, ...)] SELECT ...`(SELECT 는 복합 SELECT·ORDER BY·LIMIT 포함 무엇이든).
- 열 목록이 없으면 테이블의 모든 열을 정의 순서대로. 열 목록에 없는 열은 NULL. 값의 수가 대상 열 수와 다르거나, VALUES 의 행마다 값 수가 다르거나, 없는 열 이름이면 오류.
- VALUES 의 식은 열을 참조할 수 없다(없는 열 오류). 스칼라 하위 질의는 쓸 수 있다.
- `INSERT ... SELECT` 는 **SELECT 결과를 모두 먼저 구한 뒤** 넣는다(같은 테이블을 읽어도 넣기 전 상태를 읽는다).
- 넣을 때 열 친화도로 변환한다. rowcount 는 넣은 행 수.

### UPDATE

`UPDATE t SET 열 = 식 [, 열 = 식 ...] [WHERE 조건]`.

- WHERE 가 참인 행만 바꾼다(WHERE 가 없으면 모든 행).
- **모든 SET 식은 그 행의 바뀌기 전 값으로 계산한다**(`SET a = b, b = a` 는 두 값을 맞바꾼다).
- 열 친화도로 변환한다. rowcount 는 WHERE 에 맞은 행 수(값이 그대로여도 센다).
- WHERE 안의 하위 질의는 문장을 시작할 때의 테이블 내용을 본다. SET 식의 하위 질의는 다른 테이블을 읽거나 바꾸는 행의 열을 참조(상관)할 수 있다. (SET 식 안에서 지금 바꾸는 테이블을 읽는 하위 질의는 테스트하지 않는다)
- 없는 열(SET 의 대상이든 식 안이든)은 오류. 열은 `t.열` 처럼 테이블 이름으로 한정할 수 있다.

### DELETE

`DELETE FROM t [WHERE 조건]`. WHERE 가 참인 행(없으면 모든 행)을 지운다. rowcount 는 지운 행 수. WHERE 안의 하위 질의는 문장을 시작할 때의 테이블 내용을 본다.

### SELECT

```
SELECT [DISTINCT | ALL] 결과열, ...
  [FROM 원본 [조인 ...]]
  [WHERE 조건]
  [GROUP BY 식, ...]
  [HAVING 조건]
[{UNION | UNION ALL | INTERSECT | EXCEPT} SELECT ... ]...
[ORDER BY 식 [ASC | DESC] [NULLS FIRST | NULLS LAST], ...]
[LIMIT n [OFFSET m] | LIMIT m, n]
```

- 결과열: `*`, `t.*`, `식 [[AS] 별칭]`. 별칭은 이름이나 큰따옴표 이름이고 `AS` 없이 써도 된다(`SELECT name n`).
- FROM 이 없으면 한 행에서 계산한다(`SELECT 1 + 1`, `SELECT 1 WHERE 0` 은 행 없음). FROM 없는 `*` 는 오류.
- 처리 순서: FROM(조인) → WHERE → GROUP BY → HAVING → SELECT 목록 → DISTINCT → 복합 연산 → ORDER BY → LIMIT/OFFSET.

#### FROM 과 조인

- 원본: `테이블 [[AS] 별칭]` 또는 `(SELECT ...) [[AS] 별칭]`. FROM 하위 질의의 열 이름은 그 하위 질의의 결과 열 이름("결과 열 이름" 참고)이고, 바깥 질의를 참조하지 않는다. (FROM 하위 질의 안에서 결과 열 이름이 겹치는 경우는 테스트하지 않는다)
- 조인: `,`(= CROSS JOIN), `CROSS JOIN`, `[INNER] JOIN`, `LEFT [OUTER] JOIN`. 뒤에 `ON 조건` 또는 `USING (열, ...)` 을 붙인다. ON·USING 이 없는 JOIN 은 CROSS JOIN 과 같다. 조인은 왼쪽부터 차례로 묶는다: `a JOIN b ON ... LEFT JOIN c ON ...` 은 `(a JOIN b) LEFT JOIN c`. ON 조건은 앞에 나온 원본들과 지금 원본의 열을 쓸 수 있다.
- INNER(와 CROSS): 조건이 참인 행 쌍만. LEFT: 왼쪽 행마다 조건이 참인 오른쪽 행들, 하나도 없으면 오른쪽 열이 모두 NULL 인 행 하나. **ON 조건은 조인할 때 거르고 WHERE 는 조인이 끝난 뒤 거른다**(LEFT JOIN 에서는 결과가 다르다: ON 에 쓴 오른쪽 조건은 왼쪽 행을 없애지 않는다).
- `USING (c, ...)`: 왼쪽(지금까지 조인된 원본들 중 c 를 가진 첫 원본)의 열 c 와 오른쪽 원본의 열 c 가 `=` 인 조건(친화도 변환 포함). 그리고 `*` 는 **오른쪽의 c 를 빼고** 보여 주고, 한정하지 않은 `c` 는 왼쪽의 c 다(모호하지 않다). `오른쪽.c` 처럼 한정하면 오른쪽 열이고, `오른쪽.*` 에는 c 가 들어 있다.
- 별칭을 준 테이블은 별칭으로만 한정할 수 있다(`FROM emp AS e` 에서 `emp.name` 은 오류). `t.*` 의 t 가 FROM 에 없으면 오류.

#### 이름 찾기

- 한정된 이름 `q.c`: FROM 에서 이름(별칭이 있으면 별칭)이 q 인 원본의 열 c. 지금 SELECT 에 없으면 바깥 질의에서 찾는다. 끝까지 없으면 오류.
- 한정되지 않은 이름 `c`: 지금 SELECT 의 FROM 원본들의 열에서 찾는다. **둘 이상의 원본에 있으면 오류**(모호한 이름, USING 열은 예외).
- 지금 SELECT 의 원본에 없으면: WHERE·GROUP BY·HAVING·ORDER BY 안에서는 이 SELECT 의 결과 열 별칭을 찾는다(찾으면 그 별칭의 식을 그 자리에 쓴 것과 같다. 집계가 든 별칭은 HAVING·ORDER BY 에서만 쓸 수 있다). 그래도 없으면 바깥 질의에서 같은 순서로 찾는다. 끝까지 없으면 오류.
- 그래서 **테이블 열이 별칭보다 먼저다**: `SELECT name AS dept FROM emp WHERE dept = 'eng'` 의 `dept` 는 emp.dept 다. GROUP BY·HAVING 도 마찬가지(`SELECT count(*), min(salary) AS dept FROM emp GROUP BY dept` 는 emp.dept 로 묶는다).
- SELECT 목록 안에서는 별칭을 쓸 수 없다(`SELECT a AS x, x + 1 FROM t` 는 오류).
- ORDER BY 항이 **이름 하나뿐이고 그 이름이 결과 열 별칭과 같으면, 별칭이 테이블 열보다 먼저**다(`SELECT name AS salary, salary AS name FROM emp ORDER BY salary` 는 첫 결과 열, 곧 emp.name 으로 정렬). ORDER BY 항이 정수 리터럴 k 면 k번째 결과 열(1 부터, `*` 는 펼친 뒤 센다. 범위 밖이면 0 이든 무엇이든 오류). 그 밖의 ORDER BY 식은 위의 일반 규칙(테이블 열 먼저)을 따른다: `ORDER BY salary + 0` 의 salary 는 emp.salary 다.
- GROUP BY 항이 정수 리터럴 k 면 k번째 결과 열의 식으로 묶는다(범위 밖이면 오류). 그 밖에는 일반 규칙.

#### DISTINCT

결과 행들 중 "같은 값" 으로 이루어진 행을 하나만 남긴다(NULL 끼리 같다).

#### ORDER BY

- 기본은 ASC. 값의 순서는 비교와 같다: **NULL < 수 < TEXT**(변환 없음, 수는 크기, TEXT 는 코드 포인트). NULL 은 가장 작은 값이라 **ASC 에서는 맨 앞, DESC 에서는 맨 뒤**. `NULLS FIRST`·`NULLS LAST` 가 있으면 방향과 상관없이 그대로 둔다.
- 앞 항이 같을 때 다음 항으로 정한다. 모든 항이 같은 행들의 순서는 정해지지 않았다(테스트는 순서가 완전히 정해질 때만 순서를 본다).
- ORDER BY 식에는 SELECT 목록에 없는 열·식, 하위 질의, (집계 질의면) 집계도 쓸 수 있다.

#### LIMIT / OFFSET

`LIMIT n OFFSET m` 또는 `LIMIT m, n`(**쉼표 형식은 앞이 OFFSET, 뒤가 개수**). n, m 은 정수 식(리터럴, 자리표시자, `1 + 1` 같은 정수 산술). n 이 음수면 제한 없음, m 이 음수면 0 으로 본다. ORDER BY 다음에 적용한다.

#### 복합 SELECT

- `UNION ALL`(이어 붙임), `UNION`(합친 뒤 같은 행은 하나만), `INTERSECT`(양쪽 모두에 있는 행, 하나씩), `EXCEPT`(왼쪽 행 중 오른쪽에 없는 행, 하나씩). NULL 끼리 같다. 네 연산은 우선순위가 같고 왼쪽부터 묶는다: `A UNION B EXCEPT C` = `(A UNION B) EXCEPT C`, `A EXCEPT B UNION C` = `(A EXCEPT B) UNION C`.
- 각 SELECT 의 결과 열 수가 같아야 한다(아니면 오류). 결과 열 이름은 첫 SELECT 의 것.
- ORDER BY·LIMIT 은 마지막 SELECT 뒤에만 오고 전체 결과에 적용된다. 중간 SELECT 뒤에 ORDER BY 가 있으면 오류. 복합 SELECT 의 ORDER BY 항은 정수 k(k번째 열, 범위 밖이면 오류)나, 첫 SELECT 의 결과 열 이름(별칭 또는 열 이름, 대소문자 무시)과 같은 이름이다. 그 밖의 항은 테스트하지 않는다.
- 복합 SELECT 는 IN 하위 질의, FROM 하위 질의, `INSERT ... SELECT` 에도 쓸 수 있다.

#### 결과 열 이름 (`description` 의 각 항목 [0])

1. 별칭이 있으면 별칭(쓴 대소문자 그대로, 큰따옴표는 벗긴 내용).
2. 별칭 없는 열 참조(`c`, `t.c`, 괄호로 감싼 `(c)`, `((c))`)는 **원본에 정의된 열 이름**(쓴 대소문자가 아니라 CREATE TABLE 이나 FROM 하위 질의 쪽의 이름: emp 를 `name` 으로 만들었으면 `SELECT NAME FROM emp` 의 열 이름은 `'name'`). 집계 질의에서도 같다.
3. `*`, `t.*` 는 각 열의 정의된 이름(조인에서 겹쳐도 그대로, 예 `['id', 'x', 'id', 'y']`. USING 이면 위 규칙대로 하나가 빠진다).
4. 그 밖의 식은 **SQL 원문에서 그 식이 차지하는 텍스트 그대로**: 식의 첫 글자부터 마지막 글자까지, 안의 공백·줄바꿈·주석·대소문자·괄호를 그대로 둔다. 예: `SELECT id+1, id  +  1, COUNT( * ) FROM emp` → `['id+1', 'id  +  1', 'COUNT( * )']`, `SELECT 'x', ?, -1, NULL, 2.50` → `["'x'", '?', '-1', 'NULL', '2.50']`, `SELECT (id + 1)` → `['(id + 1)']`, `SELECT - salary` → `['- salary']`, 스칼라 하위 질의는 괄호까지 포함한 `'(SELECT max(id) FROM emp)'`, `SELECT 1 /* c */ + 2` → `['1 /* c */ + 2']`.

## 범위 밖 (테스트하지 않음)

BLOB 값과 `X'..'` 리터럴, 열 제약 조건(PRIMARY KEY, NOT NULL, DEFAULT …)과 rowid, 인덱스, 트랜잭션 명령, DROP·ALTER, RIGHT·FULL·NATURAL JOIN, 창 함수, 위에 없는 함수·연산자(`GLOB`, `COLLATE`, 비트 연산, `IS DISTINCT FROM`, 후위 `ISNULL`/`NOTNULL`), `TRUE`/`FALSE`, `?NNN`·`:name` 자리표시자, 64비트 정수 넘침, NaN·무한대, 실수 `-0.0`, 정렬 키가 모두 같은 행들의 순서, GROUP BY 키가 아닌 열을 집계 질의에서 집계 밖에 쓰는 경우, 같은 값이지만 타입이 다른 값 중 무엇이 남는지, 상관된 FROM 하위 질의, 오류 메시지 문구.
