import asyncio
import json
import time
import httpx
import websockets

BASE_URL = "http://localhost:8000"


async def api_login(username: str, password: str):
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        resp = await client.post("/api/login", json={"username": username, "password": password})
        data = resp.json()
        assert data.get("success"), f"Login failed for {username}: {data}"
        return data["session_id"]


async def api_logout(session_id: str):
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        # Send logout with cookie session_id
        resp = await client.post("/api/logout", cookies={"session_id": session_id})
        data = resp.json()
        assert data.get("success"), f"Logout failed: {data}"
        return True


async def connect_ws(session_id: str):
    uri = f"ws://localhost:8000/ws/{session_id}"
    ws = await websockets.connect(uri)
    return ws


async def receive_messages(ws, label: str, stop_after: float = 5.0):
    start = time.time()
    while time.time() - start < stop_after:
        try:
            msg = await asyncio.wait_for(ws.recv(), timeout=stop_after - (time.time() - start))
            print(f"[{label}] {msg}")
        except asyncio.TimeoutError:
            break
        except websockets.ConnectionClosed:
            print(f"[{label}] Connection closed")
            break


async def main():
    print("Logging in admin and mama...")
    admin_session = await api_login("admin", "admin")
    mama_session = await api_login("1234", "1234")

    print("Connecting admin WebSocket...")
    admin_ws = await connect_ws(admin_session)

    print("Connecting mama WebSocket...")
    mama_ws = await connect_ws(mama_session)

    # Listen briefly to capture login events
    await asyncio.sleep(0.5)
    await receive_messages(admin_ws, label="ADMIN", stop_after=1.5)

    print("Simulating mama quick reload (disconnect + reconnect < grace period)...")
    await mama_ws.close()
    await asyncio.sleep(1.0)
    mama_ws = await connect_ws(mama_session)

    # Admin should NOT receive mama_logout due to grace period
    await receive_messages(admin_ws, label="ADMIN", stop_after=2.0)

    print("Simulating mama intentional logout via API...")
    await api_logout(mama_session)

    # Admin should receive immediate mama_logout
    await receive_messages(admin_ws, label="ADMIN", stop_after=3.0)

    try:
        await admin_ws.close()
    except Exception:
        pass


if __name__ == "__main__":
    asyncio.run(main())