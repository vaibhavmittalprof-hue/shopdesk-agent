import json
import tempfile
from pathlib import Path

from data.seed import main as seed_db
from shopdesk.db import get_connection
from shopdesk.tools.refunds import issue_refund

# Use a throwaway copy of the shop, so your real database is never touched
db_path = Path(tempfile.mkdtemp()) / "scratch.db"
seed_db(db_path, verbose=False)
conn = get_connection(db_path)


def show(title, result):
    print(f"\n--- {title} ---")
    print(json.dumps(result, indent=2))


refund = {"order_id": 1001, "amount_cents": 5000, "reason": "Wrong size",
          "idempotency_key": "refund-1001-abc12345"}

show("1. First refund", issue_refund(refund, conn=conn))
show("2. The SAME request again (a retry)", issue_refund(refund, conn=conn))
show("3. A NEW key on the same, now fully refunded, order",
     issue_refund({**refund, "idempotency_key": "refund-1001-zzz99999"}, conn=conn))
show("4. A $2,500 refund on the VIP laptop (order 1010)",
     issue_refund({"order_id": 1010, "amount_cents": 250000, "reason": "Not needed",
                   "idempotency_key": "refund-1010-big00001"}, conn=conn))

count = conn.execute("SELECT COUNT(*) FROM refunds WHERE order_id = 1001").fetchone()[0]
print(f"\nRefund rows for order 1001: {count}")