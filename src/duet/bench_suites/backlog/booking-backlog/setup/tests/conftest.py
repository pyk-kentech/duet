from datetime import datetime

import pytest

from booking import Space

# 2026-10-19 은 월요일
MONDAY = datetime(2026, 10, 19, 9, 0)


class Clock:
    def __init__(self, t=MONDAY):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def space(clock):
    s = Space(clock=clock)
    s.add_resource("room-a", "Room A", capacity=6, credits_per_hour=4)
    s.add_resource("room-b", "Room B", capacity=10, credits_per_hour=6, buffer_minutes=15)
    s.add_resource("desk-1", "Desk 1", kind="desk", credits_per_hour=1, hours="mon-sat 07:00-22:00")
    s.add_member("alice", "Alice")
    s.add_member("bob", "Bob", plan="pro")
    s.add_member("carol", "Carol", plan="payg")
    return s
