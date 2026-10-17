# Benchmark — WebSocket fan-out (Python/FastAPI)

ใช้ตัดสินใจเรื่องภาษา (SPEC.md §3) · รันซ้ำได้เมื่อต้องตัดสินใจใหม่ (เช่น จะย้าย hub ไป Rust/Go)

```bash
cd docs/bench
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python "fastapi>=0.115" "uvicorn[standard]" websockets aiosqlite
.venv/bin/uvicorn server:app --port 8765 --log-level warning            # ไม่บันทึกลง DB
PERSIST=1 .venv/bin/uvicorn server:app --port 8765 --log-level warning  # INSERT + COMMIT ทุกข้อความ (SQLite WAL)
.venv/bin/python load.py <จำนวนผู้ฟัง> <จำนวนข้อความ> <ข้อความ/วินาที หรือ 0 = เต็มที่>
```

## ผล 2026-10-16 (Apple M5 Max 18 core · Python 3.12 · FastAPI 0.143.2 · uvicorn 0.54.0 · 1 process · body 300 ไบต์)

| สถานการณ์ | ส่ง (msg/s) | ส่งถึงผู้ฟัง (deliveries/s) | p50 | p95 | p99 |
|---|---:|---:|---:|---:|---:|
| 20 ผู้ฟัง · 50 msg/s | 50 | 1,004 | 0.80 ms | 1.23 ms | 1.36 ms |
| 50 ผู้ฟัง · 500 msg/s | 500 | 24,998 | 0.75 ms | 1.31 ms | 1.62 ms |
| 50 ผู้ฟัง · 500 msg/s · **บันทึก SQLite ทุกข้อความ** | 500 | 24,992 | 0.81 ms | 1.33 ms | 1.61 ms |
| 50 ผู้ฟัง · ส่งเต็มที่ (อิ่มตัว) | 3,200 | 160,024 | 1,527 ms | 2,894 ms | 3,009 ms |
| 50 ผู้ฟัง · ส่งเต็มที่ · บันทึก SQLite | 2,335 | 116,769 | 2,062 ms | 3,911 ms | 4,126 ms |
| 200 ผู้ฟัง · ส่งเต็มที่ (อิ่มตัว) | 827 | 165,482 | 1,206 ms | 2,276 ms | 2,371 ms |

ตรวจแล้วว่าโหมด PERSIST บันทึกครบ: 12,000 แถว = 2,000 + 10,000 ข้อความ

## แยก process ตามห้อง 2026-10-17 (4 process · พอร์ต 8771–8774 · process ละ 1 ห้อง · รันพร้อมกัน · ไม่บันทึก DB)

```bash
for p in 8771 8772 8773 8774; do .venv/bin/uvicorn server:app --port $p --log-level warning & done
for p in 8771 8772 8773 8774; do URL=ws://127.0.0.1:$p/ws/r$p .venv/bin/python load.py 50 10000 0 & done; wait
```

| สถานการณ์ | ส่งรวม (msg/s) | ส่งถึงผู้ฟังรวม (deliveries/s) | p99 ต่อ process |
|---|---:|---:|---:|
| 1 process ส่งเต็มที่ (วัดซ้ำ) | 3,218 | 160,881 | 2,987 ms (คิว) |
| 4 process ส่งเต็มที่ | 9,455 (2,285–2,431 ต่อ process) | 472,732 | 3,805–4,136 ms (คิว) |
| 4 process × 500 msg/s | 2,000 | 99,999 | 1.17–1.33 ms |

- ได้ประมาณ **2.9 เท่า** ไม่ถึง 4 เท่า เพราะตัวสร้างโหลด 4 ตัว (Python) แย่ง CPU เครื่องเดียวกัน · ยังไม่ได้แยกเครื่องวัด
- ทดสอบแค่การแบ่งตามห้อง (ไม่มีการส่งข้อความข้าม process) · **ยังไม่ได้วัด** Redis pub/sub หรือ PostgreSQL LISTEN/NOTIFY
- `uvicorn --workers N` แบบตรงๆ ใช้กับ hub นี้ไม่ได้ เพราะผู้ฟังจะไปตกอยู่คนละ worker ซึ่งมีหน่วยความจำแยกกัน จึงไม่เห็นข้อความของกันและกัน ต้องแบ่งตามห้องหรือใช้ broker

**ข้อจำกัดของการวัด (อ่านก่อนนำตัวเลขไปใช้)**
- ตัวสร้างโหลดเป็น Python และรันบนเครื่องเดียวกับ server จึงแย่ง CPU กัน ตัวเลข server จริงน่าจะดีกว่านี้ (ถือเป็นค่าต่ำสุด)
- แถว "ส่งเต็มที่" คือจุดอิ่มตัว latency ที่สูงมาจากคิว ไม่ใช่ความเร็วต่อข้อความ ระบบจริงต้องมี rate limit + backpressure เพื่อไม่ให้ถึงจุดนี้
- ใช้ SQLite บนเครื่อง **ยังไม่ได้วัด MySQL ผ่านเครือข่าย (Azure)** ต้องวัดซ้ำตอนทำแกน (เฟส 2)
- เป็น hub ขั้นต่ำ ยังไม่มี auth/validation ระบบจริงจะช้ากว่านี้เล็กน้อย
