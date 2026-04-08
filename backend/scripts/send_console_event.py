"""Send a debug console event to a training/level for local testing."""
import sys
import httpx

API = "http://localhost:8001/api"

def main():
    if len(sys.argv) < 4:
        print("Usage: send_console_event.py <training_id> <level_idx> <message>")
        return
    training_id = sys.argv[1]
    level_idx = sys.argv[2]
    msg = sys.argv[3]
    r = httpx.post(f"{API}/debug/trainings/{training_id}/levels/{level_idx}/console", json={"msg": msg})
    print(r.status_code, r.text)

if __name__ == '__main__':
    main()
