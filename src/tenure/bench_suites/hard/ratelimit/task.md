요청 속도를 제한하는 Python 패키지 `ratelimit` 을 만든다. 여러 스레드가 동시에 써도 안전해야 한다.

- 패키지는 작업 폴더 최상위의 `ratelimit/` 에 둔다 (src 레이아웃을 쓰지 말 것). 표준 라이브러리만 쓴다.
- 아래 이름과 동작을 정확히 지킨다. 다른 사람이 이 인터페이스로 테스트한다(스레드 여러 개로 동시에 부르는 테스트 포함).
- 시각은 생성자에 받은 `clock` 함수(인자 없이 초 단위 float 를 돌려줌)로만 얻는다. 기본값은 `time.monotonic`.

## `ratelimit.TokenBucket(rate, capacity, clock=time.monotonic)`

- `rate`: 초당 채워지는 토큰 수(0 보다 큰 수), `capacity`: 최대 토큰 수(1 이상 정수). 아니면 `ValueError`.
- 처음에는 가득 차 있다.
- `try_acquire(n=1) -> bool`: 지난번 이후 흐른 시간만큼 토큰을 채운 뒤(최대 `capacity`), 토큰이 `n` 개 이상이면 `n` 개를 빼고 `True`, 아니면 아무것도 바꾸지 않고 `False`. `n` 이 1 이상 `capacity` 이하 정수가 아니면 `ValueError`.
- `available() -> float`: 채운 뒤의 현재 토큰 수.
- 시계가 거꾸로 가면(지난번보다 작은 값) 토큰을 더하지도 빼지도 않고 기준 시각도 그대로 둔다. 시계가 기준 시각을 다시 넘을 때부터 그 차이만큼 채운다.
- 스레드 여러 개가 동시에 불러도 허용 횟수가 정확해야 한다(예: 시계가 멈춘 상태에서 용량 1000 이면 몇 개 스레드가 몇 번을 부르든 성공은 정확히 1000번).

## `ratelimit.SlidingWindow(limit, window, clock=time.monotonic)`

- `limit`: 1 이상 정수, `window`: 0 보다 큰 초. 아니면 `ValueError`.
- `try_acquire() -> bool`: 지금 시각 `t` 에 대해 구간 `(t - window, t]` 안의 **성공한** 호출이 `limit` 개보다 적으면 성공으로 기록하고 `True`, 아니면 `False`. 실패한 호출은 기록하지 않는다.
- 즉 시각 `t0` 에 성공한 호출은 `t0 + window` 가 되는 순간부터 세지 않는다.
- 스레드 안전.

## `ratelimit.KeyedLimiter(factory, max_keys=1000)`

- 키마다 리미터를 따로 둔다. `factory()` 는 새 리미터(위의 클래스나 `try_acquire` 가 있는 객체)를 만든다. `max_keys` 는 1 이상 정수, 아니면 `ValueError`.
- `try_acquire(key, *args) -> bool`: 그 키의 리미터의 `try_acquire(*args)` 결과. 처음 보는 키면 리미터를 만든다.
- 한 키의 리미터는 **정확히 한 번만** 만든다. 여러 스레드가 같은 새 키로 동시에 불러도 `factory` 는 한 번만 불린다.
- 새 키 때문에 키 수가 `max_keys` 를 넘게 되면, 가장 오래 쓰지 않은(마지막 `try_acquire` 가 가장 오래된) 키를 먼저 지운다. 지운 키를 다시 쓰면 새 리미터를 만든다.
- `len(limiter)`: 지금 가진 키 수.
