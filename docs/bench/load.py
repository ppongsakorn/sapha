"""Load client: N subscribers in one room, 1 sender sends M messages (optionally paced).

usage: python load.py <subs> <messages> <rate_per_sec or 0 for max>
Latency = receive wall-clock - send wall-clock (same machine, same clock).
"""
import asyncio
import json
import os
import statistics
import sys
import time

import websockets

URL = os.environ.get("URL", "ws://127.0.0.1:8765/ws/bench")


async def subscriber(expected: int, lat: list, ready: asyncio.Event, done: list):
    async with websockets.connect(URL, max_queue=None) as ws:
        ready.set()
        got = 0
        while got < expected:
            msg = json.loads(await ws.recv())
            lat.append(time.time_ns() - msg["t"])
            got += 1
        done.append(time.perf_counter())


async def main():
    n_subs, n_msgs, rate = int(sys.argv[1]), int(sys.argv[2]), float(sys.argv[3])
    lat: list[int] = []
    done: list[float] = []
    readies = [asyncio.Event() for _ in range(n_subs)]
    tasks = [asyncio.create_task(subscriber(n_msgs, lat, r, done)) for r in readies]
    await asyncio.gather(*(r.wait() for r in readies))
    await asyncio.sleep(0.3)
    body = "x" * 300  # ~typical short agent message
    async with websockets.connect(URL) as sender:
        start = time.perf_counter()
        for i in range(n_msgs):
            await sender.send(json.dumps({"from": "agent-a", "body": body, "t": time.time_ns()}))
            if rate:
                target = start + (i + 1) / rate
                delay = target - time.perf_counter()
                if delay > 0:
                    await asyncio.sleep(delay)
        await asyncio.gather(*tasks)
    elapsed = max(done) - start
    ms = sorted(x / 1e6 for x in lat)
    p = lambda q: ms[min(len(ms) - 1, int(q * len(ms)))]
    print(
        f"subs={n_subs} msgs={n_msgs} rate={'max' if not rate else int(rate)}/s "
        f"| sent {n_msgs/elapsed:,.0f} msg/s, delivered {len(ms)/elapsed:,.0f} deliveries/s "
        f"| latency ms p50={p(0.50):.2f} p95={p(0.95):.2f} p99={p(0.99):.2f} max={ms[-1]:.2f} "
        f"mean={statistics.fmean(ms):.2f}"
    )


asyncio.run(main())
