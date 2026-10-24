작업 폴더 최상위에 파이썬 패키지 `tzrule`(표준 라이브러리만, Python 3.11 이상)을 만든다. POSIX TZ 규칙 문자열(TZif 파일 끝에 붙는 형식, POSIX + RFC 8536 확장)을 해석해 지역 시각과 UTC 를 서로 바꾸고, 반복 일정을 펼치는 라이브러리다. 패키지는 작업 폴더 바로 아래 `tzrule/` 에 둔다(src 레이아웃 아님). 아래의 이름·시그니처·동작은 그대로 지킨다. 다른 사람이 이 인터페이스로 테스트한다. 테스트도 함께 작성한다.

- 시간대 데이터베이스가 없는 환경에서도 돌아야 한다. `tzrule/` 안의 소스는 `zoneinfo`, `pytz`, `dateutil` 을 import 하지 않고 `time.tzset` 을 부르지 않는다(검사한다).
- 공개 이름: `tzrule.TZ`. 오류는 내장 예외만 쓴다(`ValueError`, `TypeError`).

## 공통 약속

- 오프셋은 `timedelta` 이고 **UTC 보다 앞서면(동쪽) 양수**다. POSIX 문자열의 부호와 반대다: `EST5` 는 UTC−5 → `timedelta(hours=-5)`, `<+0330>-3:30` 은 `timedelta(hours=3, minutes=30)`.
- UTC 시각은 tzinfo 없는(naive) `datetime` 으로 돌려준다.
- 지역 시각(벽시계)을 받는 메서드(`utcoffset`, `to_utc`, `tzname`, `dst`, `is_gap`, `is_ambiguous`)는 tzinfo 없는 `datetime` 만 받는다. tzinfo 가 있으면 `ValueError`. 지역 시각 객체의 `fold` 속성은 **무시하고** 인자 `fold` 만 쓴다. `fold` 인자는 0 또는 1, 아니면 `ValueError`.
- UTC 시각을 받는 메서드(`from_utc`, `next_transition`)는 naive 면 UTC 로 보고, tzinfo 가 있으면 UTC 로 바꿔서 쓴다.

## TZ 문자열 문법

```
std offset [dst [offset] [,start[/time],end[/time]]]
```

- 공백(줄바꿈 포함)은 어디에도 올 수 없다(앞뒤도 안 된다). 숫자는 ASCII `0`~`9` 만, 영문자는 ASCII `A`~`Z`·`a`~`z` 만 인정한다. 다른 유니코드 숫자·문자는 오류다.
- **이름**(`std`, `dst`)
  - 꺾쇠 없는 형식: 영문자 3자 이상. 영문자가 아닌 첫 글자에서 끝난다.
  - 꺾쇠 형식 `<...>`: 꺾쇠 안은 영문자·숫자·`+`·`-` 로 된 3자 이상. 속성에는 꺾쇠를 뺀 이름을 저장한다(`<+0330>` → `"+0330"`).
- **offset**: `[+|-]hh[:mm[:ss]]`. `hh` 는 1~2자리 0~23, `mm`·`ss` 는 정확히 2자리 00~59. 부호가 없으면 `+`. **부호는 값 전체에 적용된다**: `-0:30` 은 POSIX 값 −30분이므로 동쪽 +30분. (POSIX 는 시를 24 까지 허용하지만 이 패키지에서는 24 이상은 오류다.)
  - std 의 offset 은 반드시 있어야 한다.
  - dst 의 offset 을 생략하면 std 보다 1시간 앞선다: `dst_offset = std_offset + 1시간`.
  - dst_offset 의 크기는 24시간 미만이어야 한다(생략해서 계산한 값도). dst_offset 이 std_offset 과 같으면 오류.
- **규칙** `,start[/time],end[/time]`: 둘 다 있어야 한다(하나만 있거나 끝에 `,` 가 남으면 오류). dst 이름 없이 규칙이 오면 오류. **dst 가 있는데 규칙이 없으면 미국 규칙 `M3.2.0,M11.1.0`** 을 쓴다(시각은 둘 다 기본값 02:00).
  - `Jn`: `n` 은 1~3자리, 1~365. 2월 29일은 **어느 해에도 세지 않는다**: J59 = 2월 28일, J60 = 해마다 3월 1일, J365 = 12월 31일.
  - `n`: 1~3자리, 0~365. 0부터 세고 2월 29일도 센다: 날짜 = 그해 1월 1일 + n일. 0 = 1월 1일, 59 = 윤년이면 2월 29일·평년이면 3월 1일. 평년의 365 는 다음 해 1월 1일이다.
  - `Mm.w.d`: `m` 은 1~2자리 1~12, `w`·`d` 는 정확히 1자리. `w` 1~5, `d` 0~6(**0 = 일요일**, 6 = 토요일). m월의 w번째 d요일이고, `w = 5` 는 그 달의 마지막 d요일이다(그 달에 d요일이 4번뿐이면 4번째).
  - 날짜 앞 글자는 대문자 `J`, `M` 만 쓴다.
  - `time`: `[+|-]hh[:mm[:ss]]`. `hh` 는 1~3자리 0~167, `mm`·`ss` 는 정확히 2자리 00~59, 부호는 값 전체에 적용. 생략하면 `02:00:00`. 음수이거나 24 이상이면 날짜를 넘어간다: `M3.2.0/-1` 은 둘째 일요일의 전날 23:00, `/25` 는 다음 날 01:00, `/167` 은 6일 뒤 23:00.
- 그 밖의 형식 오류(빈 문자열, 짧은 이름, 닫히지 않은 꺾쇠, 남은 글자, 범위 밖 값, 자릿수가 틀린 숫자, 부호 뒤에 숫자 없음 등)는 모두 `ValueError`. `spec` 이 문자열이 아니면 `TypeError`.

## `tzrule.TZ(spec)`

속성: `spec`(받은 문자열 그대로), `std_abbr`(str), `std_offset`(timedelta), `dst_abbr`(str 또는 None), `dst_offset`(timedelta 또는 None). DST 가 없는 문자열이면 dst 쪽 둘 다 None.

### 정규형 `str(tz)` 와 같음

`str(tz)` 는 같은 규칙을 나타내는 정규 TZ 문자열이다.
- 이름: ASCII 영문자로만 되어 있으면 그대로, 아니면 `<이름>`.
- offset 은 POSIX 값(서쪽이 양수, 즉 `-std_offset`)을 이 형식으로 쓴다: 값이 음수일 때만 `-` 를 붙이고 `+` 는 쓰지 않는다(0 은 `0`). 시는 앞자리 0 없이 쓰고, 분·초 중 하나라도 0 이 아니면 `:mm`, 초가 0 이 아니면 `:ss` 까지 붙인다(분·초는 2자리).
- DST 가 있으면 dst 이름을 쓰고, dst_offset 이 std_offset + 1시간이 **아닐 때만** 그 offset 을 쓴다. 규칙은 문자열에서 생략돼 기본 규칙을 썼더라도 **늘** 쓴다.
- 규칙 날짜는 앞자리 0 없이(`J60`, `59`, `M3.2.0`). time 은 02:00:00 이면 생략하고, 아니면 `/` 뒤에 그 time 값을 위 offset 과 같은 형식으로 쓴다(부호는 뒤집지 않는다: `/-1`, `/2:45`, `/167`, `/0`).
- 예: `str(TZ("EST+05:00EDT4,M03.2.0/2,M11.1.0/02:00:00"))` == `"EST5EDT,M3.2.0,M11.1.0"`.
- 두 `TZ` 는 `str` 이 같으면 `==` 이고 `hash` 도 같다. TZ 가 아닌 값과는 같지 않다(`TZ("UTC0") != "UTC0"`).

### 시각선 (모든 계산의 기준)

- 해 Y 의 DST 시작 순간 `S(Y)` = (start 규칙이 정하는 Y년의 날짜 00:00 + start 의 time) − std_offset. 시작 시각은 **지역 표준시**로 적힌 것이다.
- 해 Y 의 DST 끝 순간 `E(Y)` = (end 규칙이 정하는 Y년의 날짜 00:00 + end 의 time) − dst_offset. 끝 시각은 **지역 일광절약시**로 적힌 것이다.
- 해 Y 의 DST 기간 `P(Y)` 는 `S(Y) < E(Y)` 이면 `[S(Y), E(Y))`, 아니면(남반구처럼 해를 넘기는 경우) `[S(Y), E(Y+1))`.
- 어떤 UTC 순간이 어느 해의 `P(Y)` 에든 들어 있으면 그 순간의 오프셋은 dst_offset, 아니면 std_offset 이다. 기간들이 맞닿거나 겹치면 하나로 이어진 것으로 본다.
- **전이**는 오프셋이 실제로 바뀌는 순간이다. 시각이 ±167시간까지 가능하고 오프셋도 더해지므로, 앞뒤 해의 규칙이 만든 전이가 그해(UTC) 안으로 들어오거나 그해의 규칙이 만든 전이가 이웃 해로 나갈 수 있다.
- DST 1년 내내(RFC 8536): `EST5EDT4,0/0,J365/25` 는 E(Y) 가 S(Y+1) 과 같아 기간이 끊김 없이 이어지므로 전이가 없고 늘 −4시간(EDT)이다.

### 전이

- `transitions(year) -> list[tuple[datetime, timedelta, timedelta]]`: UTC 로 `year` 년 안(그해 1월 1일 00:00 이상, 다음 해 1월 1일 00:00 미만)에 있는 전이를 `(UTC 순간, 이전 오프셋, 이후 오프셋)` 으로, 시간순. 원소는 namedtuple 이어도 된다. DST 가 없거나 1년 내내면 `[]`. `year` 가 1~9999 정수가 아니면 `ValueError`.
- `next_transition(utc)`: `utc` **보다 뒤**(같은 순간은 포함하지 않음)의 첫 전이 하나를 같은 튜플로. 없으면 `None`.

### 지역 시각

전이 순간 T 에서 오프셋이 b 에서 a 로 바뀔 때:
- **틈**(a > b): 지역 시각 `[T+b, T+a)` 는 존재하지 않는다(시작 포함, 끝 제외).
- **겹침**(a < b): 지역 시각 `[T+a, T+b)` 는 두 번 온다. 첫 번째(이른 순간, 오프셋 b)가 fold=0, 두 번째(늦은 순간, 오프셋 a)가 fold=1.

메서드:
- `utcoffset(local, fold=0) -> timedelta`
  - 보통 시각: 그 오프셋(fold 와 상관없이).
  - 겹침: fold=0 → b(이른 순간), fold=1 → a(늦은 순간).
  - 틈: fold=0 → **전이 전 오프셋 b**, fold=1 → **전이 후 오프셋 a** (PEP 495 와 같다).
- `to_utc(local, fold=0) -> datetime` = local − utcoffset(local, fold).
- `tzname(local, fold=0) -> str`: utcoffset 이 고른 오프셋의 이름(std_offset 이면 std_abbr, 아니면 dst_abbr).
- `dst(local, fold=0) -> timedelta` = utcoffset(local, fold) − std_offset. DST 가 없으면 늘 0, 일광절약시가 표준시보다 늦은 문자열(음수 DST)이면 음수가 된다.
- `from_utc(utc) -> tuple[datetime, int]`: (지역 벽시계 시각(naive), fold). fold 는 겹침의 **두 번째 통과** 동안(UTC 로 `[T, T+(b−a))`)만 1, 그 밖에는 0.
- `is_gap(local) -> bool`, `is_ambiguous(local) -> bool`: 틈/겹침에 드는지.

### `tzinfo() -> datetime.tzinfo`

같은 `TZ` 객체에서는 늘 **같은** tzinfo 객체를 돌려준다. `datetime(..., tzinfo=tz.tzinfo())` 처럼 쓴다.
- `utcoffset(dt)`, `dst(dt)`, `tzname(dt)`: dt 의 벽시계와 `dt.fold` 로 위 메서드와 같은 값. `dt` 가 None 이면 None.
- `fromutc(dt)`: dt(tzinfo 가 이 객체이고 벽시계는 UTC 값)를 지역 시각으로 바꾸고 fold 를 `from_utc` 처럼 설정해, tzinfo 가 이 객체인 datetime 으로 돌려준다(그래서 `aware_utc.astimezone(tz.tzinfo())` 가 올바른 fold 를 낸다). `dt.tzinfo` 가 이 객체가 아니면 `ValueError`.

### 반복 일정

- `daily(at, start, days, *, gap="shift", ambiguous="first") -> list[datetime]`: `start` 부터 `days` 일 동안(start, start+1일, …, start+(days−1)일) 날마다 지역 시각 `at` 의 UTC 순간들(시간순).
- `monthly(at, start, count, *, day=None, week=None, weekday=None, gap="shift", ambiguous="first") -> list[datetime]`: `start` 가 있는 달부터 달마다 한 번.
  - `day`(1~31) 만 주거나, `week`(1~5)와 `weekday`(0~6) 를 둘 다 준다. week·weekday 의 뜻은 `Mm.w.d` 와 같다(**0 = 일요일**, week 5 = 그 달의 마지막). 이 밖의 조합(둘 다, 아무것도 안 줌, week 나 weekday 하나만)이나 범위 밖 값은 `ValueError`.
  - `day` 가 그 달에 없으면(2월 30일, 4월 31일 등) 그 달은 건너뛴다(말일로 당기지 않는다).
  - `start` 보다 앞선 날짜는 빼고(같은 날은 포함), 일정을 `count` 번 모으면 끝.
- 날짜마다 지역 시각 L = 그 날짜 + `at` 을 이렇게 바꾼다.
  - 보통 시각: `to_utc(L)`.
  - 틈: `gap="shift"` → `to_utc(L, fold=0)`(벽시계로는 L 에 틈 길이를 더한 순간), `gap="skip"` → 그날은 없다.
  - 겹침: `ambiguous="first"` → fold=0 순간, `"last"` → fold=1 순간, `"both"` → 두 순간 모두(이른 것 먼저).
  - `daily` 의 `days` 는 살펴볼 날 수다(skip 하면 목록이 짧아진다). `monthly` 의 `count` 는 일정 수다: skip 된 달은 세지 않고 다음 달로 넘어가며, `both` 의 두 순간은 한 번으로 센다(목록이 count 보다 길 수 있다).
- 인자 검사는 계산 전에 한다(`days`·`count` 가 0 이어도): `at` 은 tzinfo 없는 `time`(`at.fold` 는 무시), `start` 는 `date`(**`datetime` 이면 ValueError** — datetime 은 date 의 하위 클래스다), `days`·`count` 는 0 이상 정수, `gap` 은 `"shift"`·`"skip"`, `ambiguous` 는 `"first"`·`"last"`·`"both"` 중 하나. 어기면 `ValueError`.

## 예

```python
from datetime import datetime, date, time, timedelta as td
from tzrule import TZ

ny = TZ("EST5EDT,M3.2.0,M11.1.0")
ny.std_offset, ny.dst_offset            # td(hours=-5), td(hours=-4)
ny.transitions(2026)                    # [(datetime(2026, 3, 8, 7, 0), td(hours=-5), td(hours=-4)),
                                        #  (datetime(2026, 11, 1, 6, 0), td(hours=-4), td(hours=-5))]
ny.to_utc(datetime(2026, 3, 8, 2, 30))          # 틈: datetime(2026, 3, 8, 7, 30)  (벽시계로는 03:30 EDT)
ny.to_utc(datetime(2026, 3, 8, 2, 30), fold=1)  # datetime(2026, 3, 8, 6, 30)     (01:30 EST)
ny.to_utc(datetime(2026, 11, 1, 1, 30))         # 겹침: datetime(2026, 11, 1, 5, 30)
ny.from_utc(datetime(2026, 11, 1, 6, 30))       # (datetime(2026, 11, 1, 1, 30), 1)
ny.daily(time(2, 30), date(2026, 3, 7), 3)      # [datetime(2026, 3, 7, 7, 30), datetime(2026, 3, 8, 7, 30),
                                                #  datetime(2026, 3, 9, 6, 30)]   (3/8 은 틈 → shift)

syd = TZ("AEST-10AEDT,M10.1.0,M4.1.0/3")
syd.transitions(2026)                   # [(datetime(2026, 4, 4, 16, 0), td(hours=11), td(hours=10)),
                                        #  (datetime(2026, 10, 3, 16, 0), td(hours=10), td(hours=11))]

dub = TZ("IST-1GMT0,M10.5.0,M3.5.0/1")  # 음수 DST: 겨울(GMT)이 '일광절약시'
dub.dst(datetime(2026, 1, 15, 12, 0))   # td(hours=-1)
dub.tzname(datetime(2026, 7, 1, 12, 0)) # "IST"

TZ("XXX3YYY,J60,J300").transitions(2024)[0][0]  # datetime(2024, 3, 1, 5, 0)  (J60 은 윤년에도 3월 1일)
TZ("XXX3YYY,59,300").transitions(2024)[0][0]    # datetime(2024, 2, 29, 5, 0) (n=59 는 윤년에 2월 29일)
TZ("EST5EDT4,0/0,J365/25").transitions(2026)  # [] (1년 내내 EDT)
```
